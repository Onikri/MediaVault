"""Private VPN Gate JP -> SOCKS gateway for MediaVault's source transport.

No host routing or TLS interception. The GOST worker cannot send public traffic
outside tun0, even during reconnect. Profiles are public VPN Gate client data,
sanitized before OpenVPN sees them.

Reconnect policy (see docs/source-network-services.md):
- one failed check never drops a working tunnel: the tunnel is torn down after
  TUNNEL_FAILURE_LIMIT consecutive failed checks of https://1.1.1.1 (no DNS),
  or DNS_FAILURE_LIMIT consecutive failed lookups through it;
- endpoints that failed are skipped for BAD_SECONDS, the feed is refreshed when
  older than FEED_MAX_AGE, and the last good endpoint is tried first.

The exit identity (IP + monotonic generation) is served on :8090 (/status,
/health) so clients can bind solver sessions to the current exit.
`python gateway.py rotate` (or SIGUSR1) drops the current endpoint for a new one.
"""
import base64
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request

STATE = Path(os.environ.get('JP_STATE', '/state'))
STATUS_PORT = int(os.environ.get('JP_STATUS_PORT', '8090'))
FEED = 'https://www.vpngate.net/api/iphone/'
TRACE = 'https://1.1.1.1/cdn-cgi/trace'  # by IP: a tunnel check that needs no DNS
CHECK_INTERVAL = 30
TUNNEL_FAILURE_LIMIT = 3
DNS_FAILURE_LIMIT = 6
FEED_MAX_AGE = 900
BAD_SECONDS = 1800
SHORT_SESSION = 300
CONNECT_SECONDS = 24
TUN_RESTORE_SECONDS = 20
FRESH_SECONDS = 120
HOSTS = (
    'comic-ryu.jp', 'youngchampion.jp', 'manga-zegra.com', 'bigcomics.jp', 'comici.jp',
    # The other installed ComiciViewer publishers share the same regional wall.
    'asacomi.jp', 'bibibi-comic.com', 'studio.booklista.co.jp', 'championcross.jp',
    'comic-growl.com', 'comicpash.jp', 'comicride.jp', 'comic-room-base.com', 'comirela.com', 'g-comi.jp',
    'hayacomic.jp', 'heros-web.com', 'hanayume.com', 'comic.j-nbooks.jp', 'kimicomi.com',
    'kansai.mag-garden.co.jp', 'mangaspa.nikkan-spa.jp', 'comics.manga-bang.com',
    'mangabu.jp', 'mangalt.jp', 'namicomic.jp', 'piacomic.jp', 'rimacomiplus.jp',
    'takecomic.jp', 'younganimal.com',
    # Country-limited public catalogues. Account/purchase requirements remain.
    'cmoa.jp', 'novema.jp', 'booklive.jp', 'bookwalker.jp', 'music-book.jp',
    'sokuyomi.jp', 'manga.fod.fujitv.co.jp', 'manga.line.me', 'book.dmm.com',
    'book.dmm.co.jp', 'yomonga.com', 'honto.jp',
    # These public sources returned200 from Japan and403 from Oracle in live checks.
    'mangafire.to', 'soraraw.com', 'mfcdn1.xyz', 'mangarawgo.site',
)
DNS_PROBES = ('comic-ryu.jp', 'soraraw.com', 'sokuyomi.jp', 'manga.line.me')
STOP = False
ROTATE = threading.Event()
LOCK = threading.Lock()
CURRENT = {'ready': False, 'state': 'starting', 'time': 0.0}


class Failure(Exception):
    def __init__(self, kind, detail=''):
        super().__init__(detail or kind)
        self.kind, self.detail = kind, detail


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


def endpoint(config):
    """'ip:port/proto' of a sanitized profile; the quarantine key."""
    remote = proto = ''
    for line in config.splitlines():
        if line.startswith('remote '):
            remote = ':'.join(line.split()[1:3])
        elif line.startswith('proto '):
            proto = line.split()[1]
    return f'{remote}/{proto}'


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
    # Hop whitelist: only these publishers/CDNs use Japan. Other destinations
    # leave directly from the router (the Oracle address).
    return {
        'services': [{'name': 'socks', 'addr': ':1080',
                      'handler': {'type': 'socks5', 'chain': 'japan'}, 'listener': {'type': 'tcp'}},
                     {'name': 'http-connect', 'addr': ':8080',
                      'handler': {'type': 'http', 'chain': 'japan'}, 'listener': {'type': 'tcp'}}],
        'chains': [{'name': 'japan', 'hops': [{'name': 'japan-only', 'bypass': 'publishers',
                    'nodes': [{'name': 'vpn', 'addr': 'jp-vpn:1081',
                               'connector': {'type': 'socks5'}, 'dialer': {'type': 'tcp'}}]}]}],
        'bypasses': [{'name': 'publishers', 'whitelist': True,
                     'matchers': [name for host in HOSTS for name in (host, '.' + host)]}],
    }


def parse_trace(text):
    values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    try:
        ipaddress.ip_address(values.get('ip', ''))
    except ValueError:
        raise Failure('trace', 'Malformed exit trace') from None
    return values


def run(args, timeout=15):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout).stdout


def curl(url, through_vpn=True):
    args = ['curl', '--fail', '--silent', '--show-error', '--connect-timeout', '5',
            '--max-time', '12', '--max-filesize', '2097152']
    if through_vpn:
        args += ['--interface', 'tun0']
    return run([*args, url], timeout=15)


def fetch(url, through_vpn=True):
    return json.loads(curl(url, through_vpn))


def tunnel_trace():
    return parse_trace(curl(TRACE))


def resolves(host):
    try:
        return bool(run(['getent', 'ahostsv4', host], timeout=12).strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def write(name, data):
    dest = STATE / name
    temp = STATE / (name + '.tmp')
    temp.write_text(data)
    temp.chmod(0o600)
    temp.replace(dest)


def log(event, **fields):
    print(json.dumps({'event': event, 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **fields}), flush=True)


def status(ready, state, quiet=False, **extra):
    with LOCK:
        changed = CURRENT.get('state') != state or CURRENT.get('generation') != extra.get('generation', CURRENT.get('generation'))
        CURRENT.clear()
        CURRENT.update({'ready': ready, 'state': state, 'time': time.time(), **extra})
        data = json.dumps(CURRENT)
    write('status.json', data)
    if changed or not quiet:
        print(data, flush=True)


def snapshot():
    with LOCK:
        body = dict(CURRENT)
    body['age'] = round(time.time() - body.get('time', 0), 1)
    body['fresh'] = bool(body.get('ready')) and body['age'] < FRESH_SECONDS
    return body


def next_generation():
    path = STATE / 'generation'
    try:
        value = int(path.read_text().strip()) + 1
    except (OSError, ValueError):
        value = 1
    write('generation', str(value))
    return value


def current_generation():
    try:
        return int((STATE / 'generation').read_text().strip())
    except (OSError, ValueError):
        return 0


class StatusHandler(BaseHTTPRequestHandler):
    timeout = 5
    server_version = 'mediavault-jp-gateway'
    sys_version = ''

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path not in ('/status', '/health'):
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        body = snapshot()
        code = 200 if path == '/status' or body['fresh'] else 503
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


def serve_status():
    server = ThreadingHTTPServer(('0.0.0.0', STATUS_PORT), StatusHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name='status', daemon=True).start()
    return server


def stop_child(child):
    if child and child.poll() is None:
        child.terminate()
        try:
            child.wait(5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(3)


def tun_up():
    return Path('/sys/class/net/tun0').exists()


def pause(seconds, children=(), tunnel=False):
    end = time.monotonic() + seconds
    while (not STOP and not ROTATE.is_set() and time.monotonic() < end
           and all(child.poll() is None for child in children) and (not tunnel or tun_up())):
        time.sleep(0.25)


def firewall():
    # The SOCKS worker runs as nobody. Only its replies to the private Docker
    # client can use eth0; new public connections MUST use the VPN interface.
    for rule in [
        ['-o', 'lo', '-j', 'ACCEPT'], ['-o', 'tun0', '-j', 'ACCEPT'],
        ['-p', 'tcp', '--sport', '1081', '-m', 'conntrack', '--ctstate', 'ESTABLISHED', '-j', 'ACCEPT'],
        ['-j', 'REJECT'],
    ]:
        run(['iptables', '-A', 'OUTPUT', '-m', 'owner', '--uid-owner', '65534', *rule])
    # The volunteer server must not reach the SOCKS worker or the status port.
    for rule in [['-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED', '-j', 'ACCEPT'], ['-j', 'DROP']]:
        run(['iptables', '-A', 'INPUT', '-i', 'tun0', *rule])


def connect(config):
    write('current.ovpn', config)
    log_file = (STATE / 'openvpn.log').open('w')
    vpn = subprocess.Popen(['openvpn', '--config', str(STATE / 'current.ovpn')], stdout=log_file, stderr=log_file)
    log_file.close()
    deadline = time.monotonic() + CONNECT_SECONDS
    while not STOP and vpn.poll() is None and time.monotonic() < deadline:
        if 'Initialization Sequence Completed' in (STATE / 'openvpn.log').read_text(errors='replace'):
            return vpn
        time.sleep(0.5)
    stop_child(vpn)
    raise Failure('vpn-connect', 'VPN connection failed')


def accept(vpn):
    """Exit must be Japanese and the regional publishers must answer search."""
    trace = tunnel_trace()
    if trace.get('loc') != 'JP':
        raise Failure('country', 'VPN exit is not Japanese: ' + trace.get('loc', '?'))
    for host in HOSTS[:4]:
        try:
            result = fetch(f'https://{host}/api/search?q=test&page=1&size=1')
        except subprocess.CalledProcessError as error:
            raise Failure('publisher', f'{host}: {(error.stderr or "").strip()[-160:]}') from None
        if 'searchResult' not in result:
            raise Failure('publisher', f'{host}: unexpected search response')
    return trace


def session(config):
    """Run one endpoint. Returns 'failed', 'ended', 'rotated' or 'stopped'."""
    vpn = socks = None
    ready_at = None
    ep = endpoint(config)
    try:
        vpn = connect(config)
        if STOP:
            return 'stopped'
        trace = accept(vpn)
        socks = subprocess.Popen(['/usr/local/bin/gost', '-L', 'socks5://:1081'], user=65534, group=65534,
                                 env={**os.environ, 'HOME': '/tmp'})
        write('last-good.ovpn', config)
        generation, exit_ip = next_generation(), trace['ip']
        ready_at = since = time.time()
        tunnel_failures = dns_failures = 0
        probe = 0
        ROTATE.clear()

        def ready():
            status(True, 'ready', quiet=True, country='JP', exit=exit_ip, generation=generation, since=since,
                   endpoint=ep, failures={'tunnel': tunnel_failures, 'dns': dns_failures})

        ready()
        while True:
            pause(CHECK_INTERVAL, (vpn, socks), tunnel=True)
            if STOP:
                return 'stopped'
            if vpn.poll() is None and not tun_up():
                # OpenVPN restarts the tunnel itself (ping-restart); say so at once.
                status(False, 'reconnecting', reason='tun-down', endpoint=ep, generation=generation, lastExit=exit_ip)
                deadline = time.monotonic() + TUN_RESTORE_SECONDS
                while not STOP and vpn.poll() is None and not tun_up() and time.monotonic() < deadline:
                    time.sleep(0.5)
                if not tun_up():
                    raise Failure('tunnel', 'tun0 went down')
                log('tunRestored', endpoint=ep)
            if ROTATE.is_set():
                ROTATE.clear()
                log('rotate', endpoint=ep, exit=exit_ip, generation=generation)
                status(False, 'reconnecting', reason='rotate', endpoint=ep, generation=generation, lastExit=exit_ip)
                return 'rotated'
            if vpn.poll() is not None:
                raise Failure('vpn-exit', 'OpenVPN exited')
            if socks.poll() is not None:
                raise Failure('socks-exit', 'SOCKS worker exited')
            try:
                trace = tunnel_trace()
                tunnel_failures = 0
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, Failure) as error:
                tunnel_failures += 1
                log('tunnelCheckFailed', count=tunnel_failures, detail=(getattr(error, 'stderr', '') or str(error)).strip()[-160:])
                trace = None
            if trace is not None:
                if trace.get('loc') != 'JP':
                    raise Failure('country', 'Exit left Japan: ' + trace.get('loc', '?'))
                if trace['ip'] != exit_ip:
                    log('exitChanged', previous=exit_ip, exit=trace['ip'])
                    generation, exit_ip, since = next_generation(), trace['ip'], time.time()
            if resolves(DNS_PROBES[probe % len(DNS_PROBES)]):
                dns_failures = 0
            else:
                dns_failures += 1
                log('dnsCheckFailed', host=DNS_PROBES[probe % len(DNS_PROBES)], count=dns_failures)
            probe += 1
            if tunnel_failures >= TUNNEL_FAILURE_LIMIT:
                raise Failure('tunnel', f'{tunnel_failures} consecutive tunnel checks failed')
            if dns_failures >= DNS_FAILURE_LIMIT:
                raise Failure('dns', f'{dns_failures} consecutive lookups failed')
            ready()
    except Exception as error:
        if isinstance(error, Failure):
            kind, detail = error.kind, error.detail
        elif isinstance(error, subprocess.CalledProcessError):
            kind, detail = 'check', (error.stderr or '').strip()
        else:
            kind, detail = type(error).__name__, str(error)
        status(False, 'reconnecting', reason=kind, detail=detail[-300:], endpoint=ep,
               generation=current_generation(), lastExit=CURRENT.get('exit') or CURRENT.get('lastExit'))
        if ready_at is None or time.time() - ready_at < SHORT_SESSION:
            return 'failed'
        return 'ended'
    finally:
        stop_child(socks)
        stop_child(vpn)


def load_feed():
    try:
        with urllib.request.urlopen(FEED, timeout=15) as response:
            return candidates(response.read(4 * 1024 * 1024 + 1))
    except Exception as error:
        log('feedError', reason=type(error).__name__)
        return None


def saved_profile():
    saved = STATE / 'last-good.ovpn'
    if not saved.exists():
        return None
    try:
        return profile(saved.read_text())
    except ValueError:
        log('savedProfileInvalid')
        return None


def main():
    global STOP

    def shutdown(*_):
        global STOP
        STOP = True

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGUSR1, lambda *_: ROTATE.set())
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    firewall()
    status(False, 'connecting', generation=current_generation())
    serve_status()
    bad, feed, feed_time = {}, [], 0.0
    while not STOP:
        if not feed or time.time() - feed_time > FEED_MAX_AGE:
            fetched = load_feed()
            if fetched is not None:
                feed, feed_time = fetched, time.time()
        now = time.time()
        bad = {key: until for key, until in bad.items() if until > now}
        pool = [c for c in dict.fromkeys([p for p in [saved_profile(), *feed] if p]) if endpoint(c) not in bad]
        if not pool:
            log('noCandidates', quarantined=len(bad), feed=len(feed))
            pause(30)
            continue
        for config in pool:
            if STOP:
                break
            outcome = session(config)
            log('session', endpoint=endpoint(config), outcome=outcome)
            if outcome in ('failed', 'rotated'):
                bad[endpoint(config)] = time.time() + BAD_SECONDS
            if outcome in ('ended', 'rotated') or time.time() - feed_time > FEED_MAX_AGE:
                break  # rebuild: last good endpoint first, fresh feed
        else:
            pause(30)
    status(False, 'stopped', generation=current_generation())


def command(argv):
    if argv == ['rotate']:
        os.kill(1, signal.SIGUSR1)
        return 0
    if argv == ['healthcheck']:
        try:
            value = json.loads((STATE / 'status.json').read_text())
            return 0 if value['ready'] and time.time() - value['time'] < FRESH_SECONDS else 1
        except (OSError, ValueError, KeyError):
            return 1
    main()
    return 0


if __name__ == '__main__':
    sys.exit(command(sys.argv[1:]))
