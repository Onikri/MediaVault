"""Coverage of the user's 18 requested manga websites.

This is a capability/status audit, not a claim that every upstream is
accessible. Source health and a real sample page are checked by the existing
manga_readability verifier when a title is opened.
"""
from urllib.parse import urlsplit

SOURCES = (
    # Exact requested address, canonical label, integration, native id, extension names, note.
    ('hentailib.me', 'HentaiLib', 'native', 'hentailib', (), 'LibGroup API; source images are verified per title.'),
    ('hentaichan.live', 'HentaiChan', 'native', 'hentaichan', (), 'Native public HTML parser and reader.'),
    ('h-chan.me', 'H-Chan', 'mirror', 'hentaichan', (), 'Only confirmed x17.h-chan.me mirror is allowed; root domain is not assumed equivalent.'),
    ('manga-chan.me', 'MangaChan', 'native', 'mangachan', (), 'Native HTML adapter uses im.manga-chan.me and known mirror host.'),
    ('henchan.pro', 'HenChan', 'extension', None, ('henchan',), 'Suwayomi adapter when installed; source domain must be confirmed.'),
    ('hentaichan.cc', 'HentaiChan.cc', 'native', 'hentaichan-cc', (), 'Native public search and reader.'),
    ('y.hentaichan.live', 'Y-HentaiChan', 'unverified', None, (), 'Distinct subdomain; not an approved HentaiChan reader mirror.'),
    ('yaoi-chan.me', 'YaoiChan', 'extension', None, ('yaoichan', 'yaoi-chan', 'яой-тян'), 'Only if an exact installed Suwayomi source exists.'),
    ('hmanga.su', 'HManga', 'native', 'hmanga', (), 'Native public HTML adapter on current hmanga.me; live reader check still required.'),
    ('hentaros.com', 'Hentaros', 'extension', None, ('hentaros',), 'Extension only if installed; no verified native parser.'),
    ('online.hentaimoody.com', 'HentaiMoody', 'extension', None, ('hentaimoody', 'hentai moody'), 'Extension only if installed; no verified native parser.'),
    ('nude-moon.org', 'Nude-Moon', 'extension', None, ('nude-moon', 'nudemoon'), 'External reader extension exists; installation and live availability vary.'),
    ('20.allhen.online', 'AllHentai', 'extension', None, ('allhentai',), 'Grouple-family Suwayomi source; no session/cookie bypass.'),
    ('mangalib.org', 'MangaLib', 'native', 'mangalib', (), 'LibGroup API uses canonical mangalib.me, with mangalib.org as known mirror.'),
    ('v2.shlib.life', 'SlashLIB', 'native', 'slashlib', (), 'LibGroup API for SlashLIB.'),
    ('remanga.org', 'ReManga', 'extension', None, ('remanga', 'реманга'), 'Suwayomi source only if installed; no undocumented reader API.'),
    ('хентай.онлайн', 'Хентай.онлайн', 'unverified', None, (), 'IDN host not verified; do not auto-route arbitrary aliases.'),
    ('newmanga.org', 'NewManga', 'closed', None, (), 'Website publicly announces permanent closure.'),
)
assert len(SOURCES) == 18

def _host(value):
    # PublicHttp / Suwayomi may report either a root URL or a hostname.
    try:
        return (urlsplit(value if '://' in value else 'https://' + value).hostname or '').lower()
    except (TypeError, ValueError):
        return ''

def _normal(value):
    return ''.join(x for x in str(value or '').casefold() if x.isalnum())

def report(installed=None):
    """Return an ordered snapshot. Never infer install/readability from a name alone.

    If a source is reported under the exact requested hostname, that's stronger
    evidence than an extension name match; both remain only *installed* status.
    """
    if installed is None:
        from suwayomi_bridge import sources
        installed = sources()

    from manga_sources import SITES
    natives = {s.id: s for s in SITES}
    rows = []
    for domain, label, integration, native_id, aliases, note in SOURCES:
        bridge = None
        if integration == 'extension':
            wanted = {_normal(name) for name in aliases}
            exact = [s for s in installed
                     if _host(s.get('baseUrl', '')) == _host(domain)]
            named = [s for s in installed
                     if _normal(s.get('name')) in wanted]
            matches = exact or named
            bridge = matches[0] if matches else None
        if integration == 'native':
            # Detect accidental registry drift instead of advertising a missing adapter.
            site = natives.get(native_id)
            if not site:
                status = 'not_registered'
            else:
                status = 'native_registered'
        elif integration == 'mirror':
            status = 'partial_mirror'
        elif integration == 'extension':
            status = 'extension_installed' if bridge else 'extension_not_installed'
        else:
            status = integration
        rows.append({
            'domain': domain,
            'name': label,
            'integration': integration,
            'status': status,
            'nativeId': native_id if integration in {'native', 'mirror'} else None,
            'sourceId': str(bridge['id']) if bridge and bridge.get('id') is not None else None,
            'installedSourceName': str(bridge.get('name') or '') if bridge else '',
            'siteHostConfirmed': bool(bridge and _host(bridge.get('baseUrl', '')) == _host(domain)),
            'verifiedPages': None,
            'note': note,
        })
    return {
        'count': len(rows),
        'nativeRegistered': sum(row['status'] == 'native_registered' for row in rows),
        'extensionInstalled': sum(row['status'] == 'extension_installed' for row in rows),
        'partialMirrors': sum(row['status'] == 'partial_mirror' for row in rows),
        'closed': sum(row['status'] == 'closed' for row in rows),
        'liveReaderCoverageVerified': False,
        'sources': rows,
    }
