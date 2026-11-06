"""Native Chromium profiles from the signed Debian security release channel.

The browser supplies UA, Client Hints, TLS and HTTP/2 together. This module
never assembles or overrides those headers. ARM64 uses Debian's actual browser,
since Chrome for Testing does not publish a Linux ARM64 binary.
"""
from dataclasses import dataclass
import asyncio
import hashlib
from importlib.metadata import version as package_version
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import sys
import time

import httpx


@dataclass
class Profile:
    id: str
    executable: str
    version: str
    channel: str
    successes: int = 0
    refusals: int = 0
    quarantine_until: float = 0
    retired: bool = False
    reservations: int = 0
    in_use: int = 0


class NativeProfiles:
    def __init__(self, directory, *, clock=time.monotonic):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock = clock
        self.profiles = []
        self.lock = asyncio.Lock()
        self.last_check = 0
        self.failed_for_iframe = {}
        try:
            self.health = json.loads((self.directory / 'health.json').read_text())
        except (OSError, ValueError):
            self.health = {}

    def restore(self, profile):
        record = self.health.get(profile.id, {})
        profile.successes = int(record.get('successes', 0))
        profile.refusals = int(record.get('refusals', 0))
        profile.retired = bool(record.get('retired', False))
        profile.quarantine_until = self.clock() + max(0, record.get('quarantine_until', 0) - time.time())
        for key, until in record.get('failed_iframes', {}).items():
            self.failed_for_iframe[(key, profile.id)] = self.clock() + max(0, until - time.time())
        return profile

    def save(self, profile):
        self.health[profile.id] = {'successes': profile.successes, 'refusals': profile.refusals,
                                  'retired': profile.retired,
                                  'quarantine_until': time.time() + max(0, profile.quarantine_until - self.clock()),
                                  'failed_iframes': {key: time.time() + until - self.clock()
                                                     for (key, identity), until in self.failed_for_iframe.items()
                                                     if identity == profile.id and until > self.clock()}}
        target = self.directory / 'health.json'
        temporary = target.with_suffix('.pending')
        temporary.write_text(json.dumps(self.health))
        temporary.replace(target)

    async def _command(self, *args, env=None, timeout=15):
        process = await asyncio.create_subprocess_exec(
            *args, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        if process.returncode:
            raise RuntimeError('Cannot verify the installed Chromium package')
        return stdout.decode().strip()

    async def _release(self, codename, architecture):
        root = self.directory / (codename + '-' + architecture)
        root.mkdir(exist_ok=True, mode=0o700)
        release, packages = root / 'InRelease', root / 'Packages.xz'
        base = f'https://deb.debian.org/debian-security/dists/{codename}-security/'
        # Store the signed release and its exact package index as one generation.
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(base + 'InRelease')
            response.raise_for_status()
            if len(response.content) > 512 * 1024:
                raise RuntimeError('Invalid browser release metadata')
            pending = root / 'InRelease.pending'
            pending.write_bytes(response.content)
            await self._command('gpgv', '--keyring', '/usr/share/keyrings/debian-archive-keyring.gpg', str(pending))
            text = response.text
            valid = re.search(r'^Valid-Until: (.+)$', text, re.M)
            if valid:
                from email.utils import parsedate_to_datetime
                if parsedate_to_datetime(valid[1]).timestamp() < time.time():
                    raise RuntimeError('Browser release metadata expired')
            name = f'main/binary-{architecture}/Packages.xz'
            match = re.search(r'^ ([a-f0-9]{64})\s+(\d+)\s+' + re.escape(name) + r'$', text, re.M)
            if not match or int(match[2]) > 16 * 1024 * 1024:
                raise RuntimeError('Missing signed browser package index')
            response = await client.get(base + name)
            response.raise_for_status()
            raw = response.content
            if len(raw) != int(match[2]) or hashlib.sha256(raw).hexdigest() != match[1]:
                raise RuntimeError('Browser package index checksum mismatch')
            staged = root / 'Packages.pending'
            staged.write_bytes(raw)
            staged.replace(packages)
            pending.replace(release)
        text = lzma.decompress(packages.read_bytes(), memlimit=128 * 1024 * 1024).decode()
        packages = {}
        for entry in text.split('\n\n'):
            if entry.startswith(('Package: chromium\n', 'Package: chromium-common\n')):
                fields = dict(re.findall(r'^([A-Za-z0-9-]+): (.+)$', entry, re.M))
                packages[fields['Package']] = fields
        return packages

    async def _native_binary(self, packages, architecture):
        version = packages['chromium']['Version']
        if not re.fullmatch(r'[0-9][0-9A-Za-z.+~:-]{1,100}', version):
            raise RuntimeError('Invalid signed browser version')
        directory = self.directory / ('chromium-' + version + '-' + architecture)
        binary = directory / 'usr/lib/chromium/chromium'
        complete = directory / '.complete'
        if complete.exists() and binary.is_file():
            return str(binary)
        directory.mkdir(exist_ok=True, mode=0o700)
        for name in ('chromium', 'chromium-common'):
            package = packages[name]
            if package['Version'] != version:
                raise RuntimeError('Signed Chromium packages disagree on version')
            filename = package['Filename']
            if not re.fullmatch(r'pool/(?:updates/)?main/c/chromium/[A-Za-z0-9+.~_-]+\.deb', filename):
                raise RuntimeError('Invalid signed browser download path')
            size = int(package['Size'])
            if not 0 < size <= 256 * 1024 * 1024:
                raise RuntimeError('Browser archive exceeds limit')
            archive = self.directory / (name + '-' + version + '-' + architecture + '.deb')
            if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != package['SHA256']:
                staged = archive.with_suffix('.pending')
                digest, loaded = hashlib.sha256(), 0
                async with httpx.AsyncClient(timeout=30) as client:
                    async with client.stream('GET', 'https://deb.debian.org/debian-security/' + filename) as response:
                        response.raise_for_status()
                        with staged.open('wb') as output:
                            async for block in response.aiter_bytes(128 * 1024):
                                loaded += len(block)
                                if loaded > size:
                                    raise RuntimeError('Browser archive exceeds signed size')
                                digest.update(block)
                                output.write(block)
                if loaded != size or digest.hexdigest() != package['SHA256']:
                    staged.unlink(missing_ok=True)
                    raise RuntimeError('Browser archive checksum mismatch')
                staged.replace(archive)
            await self._command('dpkg-deb', '-x', str(archive), str(directory))
        complete.write_text(version)
        return str(binary)

    async def _playwright_profile(self):
        import playwright
        manifest = Path(playwright.__file__).parent / 'driver/package/browsers.json'
        installed = json.loads(manifest.read_text())
        release = package_version('playwright')
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f'https://raw.githubusercontent.com/microsoft/playwright/v{release}/packages/playwright-core/browsers.json')
            response.raise_for_status()
            if response.json() != installed:
                raise RuntimeError('Playwright browser manifest differs from its official release')
        descriptor = next(row for row in installed['browsers'] if row['name'] == 'chromium-headless-shell')
        identifier = 'playwright-chromium-' + descriptor['revision']
        existing = next((p for p in self.profiles if p.id == identifier), None)
        if existing:
            return existing
        root = self.directory / 'playwright'
        scratch = root / 'tmp'
        scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': str(root), 'TMPDIR': str(scratch),
               'TMP': str(scratch), 'TEMP': str(scratch), 'XDG_CACHE_HOME': str(root / 'cache')}
        # The pinned release's installer selects its own platform-specific
        # binary and download URL. No UA or transport parameters are invented.
        directory = root / ('chromium_headless_shell-' + descriptor['revision'])
        if not directory.is_dir():
            await self._command(sys.executable, '-m', 'playwright', 'install', 'chromium-headless-shell', env=env, timeout=180)
        candidates = list(directory.rglob('headless_shell'))
        if len(candidates) != 1:
            raise RuntimeError('Official headless Chromium binary is missing')
        native = await self._command(str(candidates[0]), '--version')
        if descriptor['browserVersion'] not in native:
            raise RuntimeError('Native browser differs from the official release version')
        (self.directory / 'playwright-release.json').write_text(json.dumps(installed))
        return Profile(identifier, str(candidates[0]), descriptor['browserVersion'], 'playwright/' + release)

    async def refresh(self):
        async with self.lock:
            if self.last_check and self.clock() - self.last_check < 3600:
                return
            executable = os.getenv('CHROMIUM_PATH') or shutil.which('chromium')
            if not executable:
                raise RuntimeError('Native Chromium is not installed')
            package, architecture = (await self._command(
                'dpkg-query', '-W', '-f=${Version} ${Architecture}', 'chromium')).split()
            release = Path('/etc/os-release').read_text()
            codename = re.search(r'^VERSION_CODENAME=([a-z]+)$', release, re.M)
            if not codename:
                raise RuntimeError('Unsupported browser release channel')
            packages = await self._release(codename[1], architecture)
            if 'chromium' not in packages or 'chromium-common' not in packages:
                raise RuntimeError('Signed release has no native Chromium packages')
            if package != packages['chromium']['Version']:
                executable = await self._native_binary(packages, architecture)
                package = packages['chromium']['Version']
            native = await self._command(executable, '--version')
            version = re.search(r'\d+\.\d+\.\d+\.\d+', native)
            if not version or not package.startswith(version[0] + '-'):
                raise RuntimeError('Installed browser is not in the signed release channel')
            identifier = f'debian-{architecture}-chromium-{package}'
            if not any(p.id == identifier for p in self.profiles):
                self.profiles.append(self.restore(Profile(identifier, executable, version[0], 'debian-security/' + codename[1])))
            # A package upgrade cannot be used to launch an older fingerprint.
            for profile in self.profiles:
                if profile.channel.startswith('debian-security/') and profile.id != identifier:
                    profile.retired = True
            try:
                fallback = await self._playwright_profile()
                if not any(p.id == fallback.id for p in self.profiles):
                    self.profiles.append(self.restore(fallback))
            except (OSError, RuntimeError, httpx.HTTPError, StopIteration):
                pass  # The signed Debian profile remains a complete native profile.
            self.last_check = self.clock()
            target = self.directory / 'candidates.json'
            temporary = target.with_suffix('.pending')
            temporary.write_text(json.dumps({'id': identifier, 'version': version[0],
                                              'channel': 'debian-security/' + codename[1]}))
            temporary.replace(target)

    def choose(self, iframe):
        now = self.clock()
        identity = hashlib.sha256(iframe.encode()).hexdigest()
        candidates = [p for p in self.profiles if not p.retired and p.quarantine_until <= now
                      and p.successes + p.reservations < 18
                      and self.failed_for_iframe.get((identity, p.id), 0) <= now]
        return min(candidates, key=lambda p: (p.refusals, p.in_use, p.successes)) if candidates else None

    def ready(self, profile):
        profile.successes += 1
        if profile.successes >= 18:
            profile.retired = True
        # Promotion follows a real segment check, never merely a new release.
        target = self.directory / 'active.json'
        temporary = target.with_suffix('.pending')
        temporary.write_text(json.dumps({'id': profile.id, 'version': profile.version, 'channel': profile.channel}))
        temporary.replace(target)
        self.save(profile)

    def refused(self, profile, iframe):
        profile.refusals += 1
        identity = hashlib.sha256(iframe.encode()).hexdigest()
        self.failed_for_iframe[(identity, profile.id)] = self.clock() + 120
        if profile.refusals >= 3:
            profile.quarantine_until = self.clock() + 900
            profile.refusals = 0
        self.save(profile)
