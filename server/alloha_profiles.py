"""Native Chromium profiles from the signed Debian security release channel.

The browser supplies UA, Client Hints, TLS and HTTP/2 together. This module
never assembles or overrides those headers. ARM64 uses Debian's actual browser,
since Chrome for Testing does not publish a Linux ARM64 binary.
"""
from dataclasses import dataclass, replace
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


PROFILES_PER_CHANNEL = 6
PROFILE_REFRESH_INTERVAL = 3600
PROFILE_RETRY_INTERVAL = 60
PROFILE_SESSION_LIMIT = 18


def profile_ids(identifier):
    return [identifier, *(f"{identifier}-slot-{slot}" for slot in range(2, PROFILES_PER_CHANNEL + 1))]


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
    slot: str = ''
    generation: int = 0


class NativeProfiles:
    def __init__(self, directory, *, clock=time.monotonic):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock = clock
        self.profiles = []
        self.lock = asyncio.Lock()
        self.next_check = 0
        self.failed_for_iframe = {}
        try:
            self.health = json.loads((self.directory / 'health.json').read_text())
        except (OSError, ValueError):
            self.health = {}

    def restore(self, profile):
        record = self.health.get(profile.slot or profile.id, {})
        profile.generation = max(0, int(record.get('generation', 0)))
        if profile.slot and profile.generation:
            profile.id = f'{profile.slot}-renewed-{profile.generation}'
        profile.successes = int(record.get('successes', 0))
        profile.refusals = int(record.get('refusals', 0))
        profile.retired = bool(record.get('retired', False))
        profile.quarantine_until = self.clock() + max(0, record.get('quarantine_until', 0) - time.time())
        for key, until in record.get('failed_iframes', {}).items():
            self.failed_for_iframe[(key, profile.id)] = self.clock() + max(0, until - time.time())
        return profile

    def save(self, profile):
        self.health[profile.slot or profile.id] = {'successes': profile.successes, 'refusals': profile.refusals,
                                  'generation': profile.generation,
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

    async def _debian_profile(self):
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
        return Profile(f'debian-{architecture}-chromium-{package}', executable, version[0],
                       'debian-security/' + codename[1])

    def install(self, release):
        # Old sessions retain their profile objects until they finish.
        family = release.channel.split('/', 1)[0]
        current = {p.slot: p for p in self.profiles if p.channel.split('/', 1)[0] == family}
        updated = [current.get(slot) or self.restore(Profile(slot, release.executable,
                                                             release.version, release.channel, slot=slot))
                   for slot in profile_ids(release.id)]
        self.profiles = [p for p in self.profiles if p.slot not in current] + updated
        for profile in updated:
            if profile.retired and profile.successes >= PROFILE_SESSION_LIMIT:
                self.renew(profile)

    def publish_candidates(self):
        target = self.directory / 'candidates.json'
        temporary = target.with_suffix('.pending')
        temporary.write_text(json.dumps([{'id': p.id, 'slot': p.slot, 'version': p.version, 'channel': p.channel}
                                         for p in self.profiles]))
        temporary.replace(target)

    def renew(self, profile):
        generation = profile.generation + 1
        replacement = replace(profile, id=f'{profile.slot}-renewed-{generation}', generation=generation,
                              successes=0, retired=False, reservations=0, in_use=0)
        for (key, identity), until in list(self.failed_for_iframe.items()):
            if identity == profile.id:
                self.failed_for_iframe.pop((key, identity))
                if until > self.clock():
                    self.failed_for_iframe[key, replacement.id] = until
        self.save(replacement)
        self.profiles[self.profiles.index(profile)] = replacement

    def current_profile(self, profile):
        # A refusal from a live session can arrive after its slot was renewed.
        return next((p for p in self.profiles if profile.slot and p.slot == profile.slot), profile)

    async def refresh(self):
        async with self.lock:
            if self.clock() < self.next_check:
                return
            releases = await asyncio.gather(self._debian_profile(), self._playwright_profile(), return_exceptions=True)
            for release in releases:
                if isinstance(release, Profile):
                    self.install(release)
            retry = any(isinstance(release, BaseException) for release in releases)
            self.next_check = self.clock() + (PROFILE_RETRY_INTERVAL if retry else PROFILE_REFRESH_INTERVAL)
            if self.profiles:
                self.publish_candidates()

    def choose(self, iframe):
        now = self.clock()
        identity = hashlib.sha256(iframe.encode()).hexdigest()
        recent_failures = {}
        candidates = []
        for profile in self.profiles:
            channel = profile.channel
            if self.failed_for_iframe.get((identity, profile.id), 0) > now:
                recent_failures[channel] = recent_failures.get(channel, 0) + 1
            elif (not profile.retired and profile.quarantine_until <= now
                  and profile.successes + profile.reservations < PROFILE_SESSION_LIMIT):
                candidates.append(profile)
        # Prefer another native release after an iframe fails on this one.
        return min(candidates, key=lambda p: (p.refusals, p.in_use, recent_failures.get(p.channel, 0), p.successes),
                   default=None)

    def ready(self, profile):
        profile.successes += 1
        if profile.successes >= PROFILE_SESSION_LIMIT:
            profile.retired = True
        # Promotion follows a real segment check, never merely a new release.
        target = self.directory / 'active.json'
        temporary = target.with_suffix('.pending')
        temporary.write_text(json.dumps({'id': profile.id, 'version': profile.version, 'channel': profile.channel}))
        temporary.replace(target)
        if profile.retired and profile.slot and self.current_profile(profile) is profile and profile in self.profiles:
            self.renew(profile)
            self.publish_candidates()
        else:
            self.save(profile)

    def refused(self, profile, iframe):
        profile = self.current_profile(profile)
        profile.refusals += 1
        identity = hashlib.sha256(iframe.encode()).hexdigest()
        self.failed_for_iframe[(identity, profile.id)] = self.clock() + 120
        if profile.refusals >= 3:
            profile.quarantine_until = self.clock() + 900
            profile.refusals = 0
        self.save(profile)

    def unavailable(self, profile, iframe):
        # Missing pages and malformed metadata concern this URL, not every
        # other title using a healthy browser. Avoid repeated URL probes.
        profile = self.current_profile(profile)
        identity = hashlib.sha256(iframe.encode()).hexdigest()
        self.failed_for_iframe[(identity, profile.id)] = self.clock() + 120
        self.save(profile)


def playback_available(directory=None):
    """False when every known browser profile is retired or quarantined.

    Then AllohaDelivery answers 409 for any title, so discovery should not
    offer Alloha voices. Reads the persisted state only; an unknown state is
    treated as available (playback then reports its own error).
    """
    root = Path(directory) if directory else Path(os.getenv('DATA_DIR') or Path(__file__).resolve().parents[1]) / '.codex-local' / 'alloha-delivery' / 'profiles'
    try:
        health = json.loads((root / 'health.json').read_text())
    except (OSError, ValueError):
        return True
    try:
        candidates = json.loads((root / 'candidates.json').read_text())
    except (OSError, ValueError):
        candidates = None
    if isinstance(candidates, list):
        ids = {str(row.get('slot') or row['id']) for row in candidates if isinstance(row, dict) and row.get('id')}
    else:
        ids = set(health)
        try:
            active = json.loads((root / 'active.json').read_text())
        except (OSError, ValueError):
            active = None
        for row in (candidates, active):
            if isinstance(row, dict) and row.get('id'):
                ids.add(str(row['id']))
        # Old installations recorded only the Debian release in candidates.json.
        # Let discovery offer the new slots while the initial refresh runs.
        for identifier in list(ids):
            if identifier.startswith(('debian-', 'playwright-chromium-')) and '-slot-' not in identifier:
                ids.update(profile_ids(identifier))
    now = time.time()
    return any(i not in health or (not health[i].get('retired') and float(health[i].get('quarantine_until') or 0) <= now
                                   and int(health[i].get('successes') or 0) < PROFILE_SESSION_LIMIT) for i in ids)
