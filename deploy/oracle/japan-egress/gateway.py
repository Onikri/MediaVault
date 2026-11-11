"""Private VPN Gate JP -> SOCKS gateway. No host routing or TLS interception.

The GOST worker cannot send public traffic outside tun0, even during reconnect.
Profiles are public VPN Gate client data, sanitized before OpenVPN sees them.
"""
import base64
import csv
import io
import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

STATE = Path(os.environ.get('JP_STATE', '/state'))
FEED = 'https://www.vpngate.net/api/iphone/'
HOSTS = (
    'comic-ryu.jp', 'youngchampion.jp', 'manga-zegra.com', 'bigcomics.jp', 'comici.jp',
    # The other installed ComiciViewer publishers share the same regional wall.
    'asacomi.jp', 'bibibi-comic.com', 'studio.booklista.co.jp', 'championcross.jp',
    'comicpash.jp', 'comicride.jp', 'comic-room-base.com', 'comirela.com', 'g-comi.jp',
    'hayacomic.jp', 'heros-web.com', 'hanayume.com', 'comic.j-nbooks.jp', 'kimicomi.com',
    'kansai.mag-garden.co.jp', 'mangaspa.nikkan-spa.jp', 'comics.manga-bang.com',
    'mangabu.jp', 'mangalt.jp', 'namicomic.jp', 'piacomic.jp', 'rimacomiplus.jp',
    'takecomic.jp', 'younganimal.com',
    # Country-limited public catalogues. Account/purchase requirements remain.
    'cmoa.jp', 'novema.jp', 'booklive.jp', 'bookwalker.jp', 'music-book.jp',
    'sokuyomi.jp', 'manga.fod.fujitv.co.jp', 'manga.line.me', 'book.dmm.com',
    'book.dmm.co.jp', 'yomonga.com',
)
STOP = False


def profile(text):
    """Rebuild only the supported public profile; never run downloaded directives."""
    if len(text) > 65536:
        raise ValueError('Oversized VPN profile')
    blocks, remote, protocol, inside, lines = {}, None, None, None, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if inside:
            if line == f'</{inside}>':
                blocks[inside] = '\n'.join(lines)
                inside, lines = None, []
            else:
                lines.append(line)
            continue
        if line in ('<ca>', '<cert>', '<key>'):
            inside = line[1:-1]
        elif line.startswith('remote '):
            parts = line.split()
            if len(parts) != 3 or remote:
                raise ValueError('Expected one VPN endpoint')
            address = ipaddress.ip_address(parts[1])
            port = int(parts[2])
            if not address.is_global or address.version != 4 or not 1 <= port <= 65535:
                raise ValueError('Nonpublic VPN endpoint')
            remote = (str(address), port)
        elif line.startswith('proto '):
            protocol = line.split()[1]
        elif line.split()[0] not in {
            'client', 'dev', 'nobind', 'cipher', 'data-ciphers', 'auth',
            'resolv-retry', 'persist-key', 'persist-tun', 'verb',
            'remote-cert-tls', 'verify-x509-name', 'tls-version-min',
            'auth-nocache', 'script-security', 'connect-retry-max', 'connect-timeout', 'hand-window',
        }:
            raise ValueError('Unsupported VPN profile directive')
    if inside or not remote or protocol not in ('tcp', 'tcp-client', 'udp') or set(blocks) != {'ca', 'cert', 'key'}:
        raise ValueError('Incomplete public VPN profile')
    for name, value in blocks.items():
        if not value.startswith('-----BEGIN ') or '\n-----END ' not in value or '<' in value:
            raise ValueError('Invalid inline certificate/key')
    config = '\n'.join([
        'client', 'dev tun', f'proto {protocol}', f'remote {remote[0]} {remote[1]}',
        'nobind', 'cipher AES-128-CBC', 'data-ciphers AES-128-CBC', 'auth SHA1',
        'remote-cert-tls server', 'verify-x509-name opengw.net name', 'tls-version-min 1.2',
        'auth-nocache', 'script-security 1', 'connect-retry-max 1',
        'connect-timeout 6', 'hand-window 15', 'verb 3',
        *[f'<{k}>\n{v}\n</{k}>' for k, v in blocks.items()], '',
    ])
    return config


def candidates(raw):
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Oversized VPN Gate feed')
    rows = csv.DictReader(io.StringIO('\n'.join(l for l in raw.decode('utf-8-sig').splitlines() if not l.startswith('*'))))
    result = []
    for row in rows:
        if row.get('CountryShort') != 'JP':
            continue
        try:
            text = base64.b64decode(row['OpenVPN_ConfigData_Base64'], validate=True).decode()
            result.append((float(row.get('Speed') or 0), profile(text)))
        except (KeyError, ValueError, UnicodeError):
            continue
    return [p for _, p in sorted(result, key=lambda pair: pair[0], reverse=True)[:48]]


def routing_config():
    # Hop whitelist: only these publishers/CDNs use Japan. Other sources are direct.
    return {
        'services': [{'name': 'suwayomi', 'addr': ':1080',
                      'handler': {'type': 'socks5', 'chain': 'japan'}, 'listener': {'type': 'tcp'}},
                     {'name': 'origin-diagnostics', 'addr': ':8080',
                      'handler': {'type': 'http', 'chain': 'japan'}, 'listener': {'type': 'tcp'}}],
        'chains': [{'name': 'japan', 'hops': [{'name': 'japan-only', 'bypass': 'publishers',
                    'nodes': [{'name': 'vpn', 'addr': 'suwayomi-jp-vpn:1081',
                               'connector': {'type': 'socks5'}, 'dialer': {'type': 'tcp'}}]}]}],
        'bypasses': [{'name': 'publishers', 'whitelist': True,
                     'matchers': [name for host in HOSTS for name in (host, '.' + host)]}],
    }


def run(args, timeout=15):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout).stdout


def write(name, data):
    dest = STATE / name
    temp = STATE / (name + '.tmp')
    temp.write_text(data)
    temp.chmod(0o600)
    temp.replace(dest)


def status(ready, **extra):
    write('status.json', json.dumps({'ready': ready, 'time': time.time(), **extra}))
    print(json.dumps({'ready': ready, **extra}), flush=True)


def stop_child(child):
    if child and child.poll() is None:
        child.terminate()
        try:
            child.wait(5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(3)


def fetch(url, through_vpn=True):
    args = ['curl', '--fail', '--silent', '--show-error', '--connect-timeout', '5',
            '--max-time', '12', '--max-filesize', '2097152']
    if through_vpn:
        args += ['--interface', 'tun0']
    return json.loads(run([*args, url], timeout=15))


def pause(seconds, children=()):
    end = time.monotonic() + seconds
    while not STOP and time.monotonic() < end and all(child.poll() is None for child in children):
        time.sleep(0.25)


def main():
    global STOP
    def shutdown(*_):
        global STOP
        STOP = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The SOCKS worker runs as nobody. Only its replies to the private Docker
    # client can use eth0; new public connections MUST use the VPN interface.
    for rule in [
        ['-o', 'lo', '-j', 'ACCEPT'], ['-o', 'tun0', '-j', 'ACCEPT'],
        ['-p', 'tcp', '--sport', '1081', '-m', 'conntrack', '--ctstate', 'ESTABLISHED', '-j', 'ACCEPT'],
        ['-j', 'REJECT'],
    ]:
        run(['iptables', '-A', 'OUTPUT', '-m', 'owner', '--uid-owner', '65534', *rule])
    pool = []
    while not STOP:
        status(False, state='connecting')
        saved = STATE / 'last-good.ovpn'
        pool = []
        if saved.exists():
            try:
                pool.append(profile(saved.read_text()))
            except ValueError:
                print(json.dumps({'savedProfileInvalid': True}), flush=True)
        try:
            with urllib.request.urlopen(FEED, timeout=15) as response:
                pool += candidates(response.read(4 * 1024 * 1024 + 1))
        except Exception as error:
            print(json.dumps({'feedError': type(error).__name__}), flush=True)
        for config in dict.fromkeys(pool):
            if STOP:
                break
            vpn = socks = None
            try:
                write('current.ovpn', config)
                with (STATE / 'openvpn.log').open('w') as log:
                    vpn = subprocess.Popen(['openvpn', '--config', str(STATE / 'current.ovpn')], stdout=log, stderr=log)
                    deadline = time.monotonic() + 24
                    while not STOP and vpn.poll() is None and time.monotonic() < deadline:
                        if 'Initialization Sequence Completed' in (STATE / 'openvpn.log').read_text():
                            break
                        pause(0.5)
                    else:
                        raise RuntimeError('VPN connection failed')
                    if STOP:
                        break
                    geo = fetch('https://ipwho.is/')
                    if geo.get('country_code') != 'JP' or not geo.get('success'):
                        raise RuntimeError('VPN exit is not confirmed Japanese')
                    for host in HOSTS[:4]:
                        result = fetch(f'https://{host}/api/search?q=test&page=1&size=1')
                        if 'searchResult' not in result:
                            raise RuntimeError('Publisher search failed')
                    socks = subprocess.Popen(['/usr/local/bin/gost', '-L', 'socks5://:1081'], user=65534, group=65534,
                                             env={**os.environ, 'HOME': '/tmp'})
                    write('last-good.ovpn', config)
                    status(True, country='JP', exit=geo['ip'])
                    while not STOP and vpn.poll() is None and socks.poll() is None:
                        pause(45, (vpn, socks))
                        if not STOP and vpn.poll() is None and socks.poll() is None:
                            fetch('https://comic-ryu.jp/api/search?q=test&page=1&size=1')
                            write('status.json', json.dumps({'ready': True, 'time': time.time(), 'country': 'JP', 'exit': geo['ip']}))
            except Exception as error:
                detail = str(error) if isinstance(error, RuntimeError) else getattr(error, 'stderr', '') or ''
                status(False, state='reconnecting', reason=type(error).__name__, detail=detail[-400:])
            finally:
                stop_child(socks)
                stop_child(vpn)
                status(False, state='stopped' if STOP else 'reconnecting')
        if not STOP:
            pause(30)


if __name__ == '__main__':
    main()
