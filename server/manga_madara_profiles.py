"""Source identities and Madara overrides from Keiyoushi 6f345a8."""


PROFILES = (
    # Installed 1.6.56, recovered from fd90fc69d881.
    (('8904806262353429205', 'Anisa Scans', 'https://anisascans.in', True), {
        'chapter_mode': 'manga', 'metadata_interval': 1 / 3,
    }),
    (('2136088453725931591', 'MadaraDex', 'https://madaradex.org', True), {
        'variant': 'madaradex', 'section': 'title', 'genre_section': 'genre',
    }),
    (('7034264791241222160', 'CartoonPorn', 'https://cartoonporn.to', True), {
        'variant': 'cartoon', 'html': True, 'section': 'porncomic', 'uses_post_id': False,
        'selectors': {'cards': 'div.item_content, div.item-thumb', 'card_link': 'a[href*="/porncomic/"]',
                      'next': 'a[href*="/porncomic/page/"]', 'title': 'h1.comic-hero__title',
                      'cover': '.comic-hero__image-wrap img', 'artists': '.meta-tag--artist',
                      'genres': '.meta-tag--genre', 'chapters': 'a[href*="/porncomic/"]',
                      'page_images': 'img.manga-img'},
    }),
    (('7947062020376654174', 'Kun Manga Online', 'https://www.kunmanga.online', True), {
        'variant': 'json_chapters', 'html': True, 'uses_post_id': False, 'metadata_interval': .5,
        'selectors': {'cards': '.c-tabs-item__content, .page-item-detail',
                      'card_link': '.post-title a, h3.h4 a', 'next': 'a[aria-label=Next]'},
    }),
    (('1987105317893699901', 'Zinmanga.net', 'https://www.zinmanga.net', False), {
        'variant': 'json_chapters', 'html': True, 'uses_post_id': False, 'manga_only': False, 'metadata_interval': 1,
    }),
    (('5190569675461947007', 'Toonily', 'https://toonily.com', True), {
        'variant': 'toonily', 'html': True, 'section': 'serie', 'genre_section': 'genre',
        'chapter_mode': 'manga', 'date_format': '%b %d, %y', 'thumbnail_original': True,
        'selectors': {'description': 'div.content-area div.summary__content'},
    }),
    (('6293890187960663957', 'TopManhua.fan', 'https://www.topmanhua.fan', True), {
        'variant': 'topmanhua_fan', 'html': True, 'section': 'manhua', 'date_format': '%m/%d/%Y',
        'selectors': {'chapters': 'div.wp-manga-chapter'},
    }),
    (('1264036757248780997', 'Zazamanga', 'https://www.zazamanga.com', True), {
        'variant': 'zaza', 'html': True, 'selectors': {
            'status': 'div.summary-heading:-soup-contains("Status") + div',
            'genres': 'div.post-content div.tags a', 'chapters': 'div.wp-manga-chapter',
            'next': 'ul.pagination > li:last-child:not(.disabled) > a[href]',
            'description': 'div.summary__content',
        },
    }),
    (('8547397037512613554', 'AllPornComic', 'https://allporncomic.com', True), {'html': True, 'section': 'porncomic', 'uses_post_id': False}),
    (('7848750588298461115', 'AP Comics', 'https://apcomics.org', True), {'chapter_mode': 'manga'}),
    (('6576302499429437207', 'Aunt Manhwa', 'https://auntmanhwa.com', True), {}),
    (('7909401032149692930', 'Borat Scans', 'https://boratscans.com', False), {'chapter_mode': 'manga'}),
    (('5944672760629857205', 'Bun Manga', 'https://bunmanga.com', False), {}),
    (('3890119680043332770', 'Cucumber Manga', 'https://cucumbermanga.com', True), {'chapter_mode': 'manga'}),
    (('7432245132662185058', 'Decadence Scans', 'https://reader.decadencescans.com', True), {'chapter_mode': 'manga'}),
    (('5861653560535486832', 'Ero18x', 'https://ero18x.com', True), {'html': True, 'chapter_mode': 'manga'}),
    (('5246625723235112128', 'GakaMangas', 'https://gakamangas.com', False), {'chapter_mode': 'manga', 'manga_only': False}),
    (('4598626990187882152', 'GalaxyDegenScans', 'https://gdscans.com', True), {'chapter_mode': 'manga'}),
    (('8561426018751869351', 'Hentai1.io', 'https://hentai1.io', True), {'html': True}),
    # Sites that moved their title section (Nov 2026); the extension does not check the path.
    (('7329798563365402763', 'HM2D', 'https://doujindistrict.com', True), {'chapter_mode': 'manga', 'section': 'read'}),
    (('3876544289472679486', 'Hunlight Comics', 'https://hunlightcomics.com', True), {'chapter_mode': 'manga', 'section': 'm'}),
    (('5815628626283130746', 'KaliScan.org (unoriginal)', 'https://kaliscan.org', True), {'chapter_mode': 'manga'}),
    (('4307007494151154546', 'KSGroupScans', 'https://ksgroupscans.com', True), {'chapter_mode': 'manga'}),
    (('8802607595629671202', 'LHTranslation', 'https://lhtranslation.net', False), {'chapter_mode': 'manga'}),
    (('8622937201319058235', 'LinkManga', 'https://linkmanga.com', True), {}),
    (('3971812949560196318', 'Lovesjane Scans', 'https://lovesjane.site', False), {'chapter_mode': 'paged'}),
    (('4446818596127611511', 'Manga18Free', 'https://manga18free.com', True), {'chapter_mode': 'admin'}),
    (('6802623574377987877', 'Manga 18x', 'https://manga18x.net', True), {'chapter_mode': 'manga'}),
    (('5229341270935044914', 'Manga Eclipse', 'https://mangaeclipse.com', False), {}),
    (('1099222169691387069', 'Mangaforfree.com', 'https://mangaforfree.com', True), {'chapter_mode': 'admin'}),
    (('5502656519292762717', 'MangaManiacs', 'https://mangamaniacs.org', True), {}),
    (('2031498907928923621', 'MangaOwl.io (unoriginal)', 'https://mangaowl.io', True), {'chapter_mode': 'manga', 'section': 'read-1'}),
    (('4265503553734005106', 'MangaPark.tv (unoriginal)', 'https://mangapark.tv', True), {'chapter_mode': 'manga', 'section': 'manhwa'}),
    (('3606721916149050760', 'Mangasushi', 'https://mangasushi.org', False), {'chapter_mode': 'manga'}),
    (('7638481723868333116', 'ManhuaHot', 'https://manhuahot.com', False), {}),
    (('4005973248538140146', 'ManhuaUS', 'https://manhuaus.com', False), {'chapter_mode': 'manga', 'manga_only': False}),
    (('6077132944162952766', 'Manhua Zonghe', 'https://www.manhuazonghe.com', True), {'section': 'manhua', 'manga_only': False}),
    (('5795673090229968734', 'Manhwa18.today', 'https://www.manhwa18.today', True), {'chapter_mode': 'manga'}),
    (('7672439791159944710', 'ManhwaDen', 'https://www.manhwaden.com', True), {'html': True, 'chapter_mode': 'manga', 'manga_only': False}),
    (('3868891550336834170', 'ManhwaHub.to', 'https://manhwahub.to', True), {'section': 'manhwa', 'genre_section': 'genre'}),
    (('8935586841672178004', 'ManhwaManhua', 'https://manhwamanhua.com', True), {'chapter_mode': 'manga', 'manga_only': False}),
    (('3315938131690984352', 'Manhwa Reads', 'https://manhwareads.com', True), {'chapter_mode': 'manga'}),
    (('3590279382085161370', 'Manhwa Toon', 'https://www.manhwatoon.me', True), {'chapter_mode': 'manga'}),
    (('5177484976652938680', 'Manhwatop', 'https://manhwatop.com', True), {'chapter_mode': 'manga', 'manga_only': False}),
    (('2527256034272235453', 'OctopusManga', 'https://octopusmanga.com', True), {'chapter_mode': 'manga'}),
    (('4403086215261921832', 'Orchisasia', 'https://www.orchisasia.org', True), {'section': 'comic'}),
    (('3740623306758763677', 'Paritehaber', 'https://www.paritehaber.com', True), {}),
    (('2311025425739352818', 'Pornhwaz', 'https://www.pornhwaz.com', True), {'section': 'webtoon'}),
    (('5756634909776784131', 'Sleepy Translations', 'https://sleepytranslations.com', False), {'chapter_mode': 'manga'}),
    (('6421630287504544593', 'TopManhua.net', 'https://topmanhua.net', True), {'chapter_mode': 'manga'}),
    (('6032516943051342273', 'TritiniaScans', 'https://tritinia.org', False), {'chapter_mode': 'manga'}),
    (('58992897252080929', 'KokoMangas', 'https://kokomangas.com', True), {'chapter_mode': 'manga'}),
    (('3062846066388633553', 'WebtoonScan', 'https://webtoonscan.org', True), {'section': 'manhwa'}),  # .com lost its DNS (Nov 2026)
    (('6540843430852844328', 'WuxiaWorld', 'https://wuxiaworld.site', False), {'chapter_mode': 'manga', 'section': 'novel'}),
    (('4439807782838127935', 'YaoiScan', 'https://yaoiscan.com', True), {}),
    (('5990114708086767078', 'Zinmanga', 'https://mangazin.org', True), {'manga_only': False}),
    (('6660493687892371703', 'AllPornComic.io', 'https://allporncomic.io', True), {'chapter_mode': 'manga', 'date_format': '%d/%m/%Y'}),
    (('4205510315534778593', 'GingeRTooN', 'https://gingertoon.com', True), {'html': True, 'chapter_mode': 'manga', 'date_format': '%m.%d.%Y'}),
    (('7664311260874726882', 'HentaiXComic', 'https://hentaixcomic.com', True), {'chapter_mode': 'manga', 'date_format': '%b %d, %Y'}),
    (('1089473637776666044', 'HentaiXYuri', 'https://hentaixyuri.com', True), {'chapter_mode': 'manga', 'date_format': '%b %d, %Y'}),
    (('2681651342533848540', 'MangaRead.org', 'https://www.mangaread.org', True), {'chapter_mode': 'manga', 'date_format': '%d.%m.%Y'}),
    (('2676315620251021475', 'Manhwa68', 'https://manhwa68.com', True), {'chapter_mode': 'manga', 'manga_only': False, 'date_format': '%b %d, %Y'}),
    (('3386088694317815151', 'Manhwa Comics', 'https://manhwacomics.com', True), {'chapter_mode': 'manga', 'section': 'manhwa', 'date_format': '%d %b %Y'}),
    (('20045885295638720', 'Petrotechsociety', 'https://www.petrotechsociety.org', True), {'date_format': '%d/%m/%Y'}),
    (('2054192099319007885', 'ToonGod', 'https://www.toongod.org', True), {'html': True, 'section': 'webtoons', 'date_format': '%d %b %Y'}),
    (('1103204227230640533', 'Comics Valley', 'https://comicsvalley.com', True), {
        'language': 'all', 'section': 'comics-new', 'chapter_mode': 'manga', 'date_format': '%d/%m/%Y',
    }),
    (('7008887237419113673', 'Grabber Zone', 'https://grabber.zone', False), {
        'language': 'all', 'section': 'comics', 'date_format': '%d.%m.%Y',
        'selectors': {'chapter_name': 'a + a'},
    }),
    (('5617855959190673282', 'Manhwa-raw', 'https://manhwa-raw.com', True), {
        'variant': 'raw', 'language': 'all', 'html': True, 'date_format': '%d/%m/%Y',
        'selectors': {
            'status': '.post-content_item:-soup-contains("Status") > .summary-content',
            'description': '.post-content_item:-soup-contains("Summary") .summary-container',
            'page_images': '.page-break img.wp-manga-chapter-img',
        },
    }),
    (('626267698662819838', 'Aqua Manga', 'https://aquareader.org', False), {
        'variant': 'aqua', 'html': True, 'uses_post_id': False,
        'selectors': {
            'cards': '.aqua-manga-card', 'card_link': '.aqua-manga-card__title a', 'next': 'a.next',
            'title': '.aqua-series-info__title', 'cover': '.aqua-series-cover__img',
            'description': '.aqua-series-synopsis', 'status': '.aqua-series-meta__status',
            'genres': '.aqua-series-genre-pill', 'authors': '.aqua-series-info__creator-value a',
            'artists': '.aqua-series-info__creator-value a', 'chapters': '.aqua-ch-item',
            'chapter_name': '.aqua-ch-item__name', 'chapter_date': '.aqua-ch-item__time',
        },
    }),
    (('7621724834621233483', 'BrainRotComics', 'https://brainrotcomics.com', False), {
        'chapter_mode': 'manga', 'alt_names': False, 'selectors': {'authors': '', 'artists': ''},
    }),
    (('3544369893051520689', 'Cocomic', 'https://cocomic.co', True), {
        'chapter_mode': 'manga', 'metadata_interval': 2,
        'selectors': {
            'title': '.asura-series-title, .post-title h3, .post-title h1',
            'cover': '.asura-poster-img, .summary_image img',
            'description': '.asura-synopsis-content, .description-summary .summary__content',
            'genres': '.asura-genre-tag, .genres-content a', 'status': '.asura-badge-status',
            'chapters': 'li.wp-manga-chapter:not(.premium)',
        },
    }),
    (('6573506892686767219', 'DragonTea', 'https://dragontea.ink', False), {
        'section': 'novel', 'chapter_mode': 'manga', 'date_format': '%m/%d/%Y', 'metadata_interval': 1,
    }),
    (('3956136651279281107', 'GEDE Comix', 'https://gedecomix.com', True), {
        'section': 'porncomic', 'chapter_mode': 'manga',
        'selectors': {'cover': '.summary_image img:not([data-eio])', 'card_cover': 'img:not([data-eio])'},
    }),
    (('3694940277826033657', 'Gourmet Scans', 'https://gourmetsupremacy.com', True), {
        'section': 'project', 'genre_section': 'genre', 'ajax_template': 'wp-manga/content/content-archive',
    }),
    (('3112384885023225761', 'Kissmanga.in', 'https://kissmanga.in', True), {
        'section': 'kissmanga', 'chapter_mode': 'manga',
    }),
    (('4480996639887718467', 'Lily Manga', 'https://lilymanga.net', True), {
        'section': 'gl', 'genre_section': 'gl-genre', 'html': True, 'chapter_mode': 'manga',
        'date_format': '%d.%m.%Y', 'metadata_interval': 2,
    }),
    (('8173282214298911566', 'MangaGG', 'https://mangagg.com', True), {
        'section': 'comic', 'chapter_mode': 'paged', 'date_format': '%m/%d/%Y',
    }),
    (('9030178752551947945', 'Manhua Plus', 'https://manhuaplus.com', False), {
        'manga_only': False, 'selectors': {'page_images': '.read-container img'},
    }),
    (('3663840686576348637', 'ManhwaNex', 'https://manhwanex.com', False), {'chapter_mode': 'manga'}),
    (('4870917758913494428', 'S2Manga', 'https://s2read.com', True), {}),
    (('5404499323728358840', 'Toonizy', 'https://toonizy.com', True), {
        'section': 'webtoon', 'chapter_mode': 'manga', 'date_format': '%b %d, %y',
        'selectors': {'title': '.post-content h3'},
    }),
    (('368848319592333339', 'Top Manhua', 'https://mangatop.org', True), {
        'section': 'series', 'chapter_mode': 'paged', 'date_format': '%m/%d/%y',
        'manga_only': False, 'metadata_interval': 0.5,
    }),
    (('6750082404202711318', 'WebtoonXYZ', 'https://www.webtoon.xyz', True), {
        'section': 'read', 'genre_section': 'webtoon-genre', 'date_format': '%d %b %Y',
        'thumbnail_original': True,
    }),
    (('6718273076571980404', 'Yaoihub', 'https://yaoihub.org', True), {
        'chapter_mode': 'manga', 'metadata_interval': 2, 'section': 'read',
    }),
    (('7450882931813509619', 'MangaForFree.net', 'https://mangaforfree.net', True), {
        'chapter_mode': 'admin', 'metadata_interval': 1, 'raw_marker': 'contains',
    }),
    (('2115363546279045008', 'MangaForFree.net', 'https://mangaforfree.net', True), {
        'language': 'ko', 'chapter_mode': 'admin', 'metadata_interval': 1, 'raw_marker': 'contains',
    }),
    (('3147518065805706', 'MangaForFree.net', 'https://mangaforfree.net', True), {
        'language': 'all', 'chapter_mode': 'admin', 'metadata_interval': 1,
    }),
    (('6720687475375335817', 'ManhwaClub.net', 'https://manhwaclub.net', True), {
        'chapter_mode': 'admin', 'raw_marker': 'suffix',
    }),
    (('3482736208073357647', 'ManhwaClub.net', 'https://manhwaclub.net', True), {
        'language': 'ko', 'chapter_mode': 'admin', 'raw_marker': 'suffix',
    }),
    (('5395306515630347602', 'SeraphicDeviltry', 'https://seraphic-deviltry.com', True), {
        'chapter_mode': 'manga', 'date_format': '%m/%d/%Y', 'metadata_interval': 1 / 3,
    }),
    (('6626112947749020527', 'SeraphicDeviltry', 'https://spanish.seraphic-deviltry.com', True), {
        'language': 'es', 'chapter_mode': 'manga', 'date_format': '%m/%d/%Y', 'metadata_interval': 1 / 3,
        'chapter_volumes': True,
    }),
    (('5727368826344311935', 'Jinmangas', 'https://mangafree.info', True), {'chapter_mode': 'manga'}),
    (('3386549954655095711', 'Mangafree', 'https://mangafree.info', True), {'chapter_mode': 'manga'}),
    (('6812667365653325714', 'MangaCrazy', 'https://mangacrazy.net', True), {
        'language': 'all', 'chapter_mode': 'manga',
    }),
    (('6353068724409812158', 'AllPornComics.co', 'https://allporncomics.co', True), {
        'language': 'all', 'html': True, 'section': 'comic', 'date_format': '%d/%m/%Y',
        'selectors': {'card_link': 'h3 > a[href]:not([target=_self]):last-of-type'},
    }),
    (('1406386535599331231', 'MangaHe', 'https://mangahe.com', True), {'variant': 'mangahe'}),
    (('4046163527731172053', 'Kmansin09', 'https://kmansin09.top', False), {
        'language': 'ja', 'html': True, 'chapter_mode': 'manga',
    }),
    (('6625474581258090106', 'Hentai4Free', 'https://hentai4free.net', True), {
        'variant': 'hentai4free', 'section': 'hentai',
        'selectors': {'cards': '.page-item-detail', 'chapters': 'section.h4f-oneshot-preview',
                      'chapter_link': '.h4f-preview-reader-btn[href]', 'chapter_name': '.h4f-preview-title small'},
    }),
    (('918523496924275699', 'HentaiXDickgirl', 'https://hentaixdickgirl.com', True), {}),
    (('4306337471481207984', 'Lgbtics', 'https://lgbtics.com', True), {
        'variant': 'lgbtics', 'section': 'comic', 'genre_section': 'comic-genre', 'html': True, 'uses_post_id': False,
    }),
    (('2964723819258267786', 'Manga District', 'https://mangadistrict.com', True), {
        'variant': 'district', 'section': 'series', 'genre_section': 'publication-genre', 'html': True,
        'quality_paths': True,
        'selectors': {'next': '.wp-pagenavi a.last', 'chapter_date': '.chapter-release-date .timediff',
                      'page_images': 'div.page-break img:not(noscript img):not(#image-99999)'},
    }),
    (('3544957587727489204', 'Manhuanext', 'https://manhuanext.com', False), {
        'chapter_mode': 'manga', 'selectors': {'chapters': 'li.wp-manga-chapter:not(.premium-block)'},
    }),
    (('5475936177780301452', 'Rose Squad Scans', 'https://rosesquadscans.aishiteru.org', True), {
        'variant': 'rosesquad', 'chapter_mode': 'manga', 'date_format': '%m.%d.%Y', 'metadata_interval': 2, 'section': 'series',
    }),
    (('6792243715659475719', 'Ruby Comics', 'https://rubycomics.net', True), {
        'variant': 'ruby', 'chapter_mode': 'manga', 'thumbnail_original': True,
        'selectors': {'description': 'div.description-summary div.limit-html'},
    }),
    (('8546397272954539389', 'Setsu Scans', 'https://setsuscans.com', False), {
        'variant': 'setsu', 'chapter_mode': 'manga', 'metadata_interval': 0.5,
        'selectors': {'status': 'div.summary-heading:-soup-contains("status", "Status") + div.summary-content'},
    }),
    # goodtoon010 redirects to goodtoon012 (numbered domains rotate).
    (('2738031143723682744', 'GoodToon', 'https://www.goodtoon012.com', True), {
        'variant': 'goodtoon', 'language': 'ko', 'html': True, 'uses_post_id': False, 'chapter_mode': 'manga',
        'date_format': '%y.%m.%d',
        'selectors': {'title': 'h1.summary-title, div.post-title h3, div.post-title h1, #manga-title > h1',
                      'authors': 'div.manga-summary-author .author-text, div.manga-summary-author',
                      'status': 'div.summary-meta-row .meta-value', 'description': 'div.manga-summary-desc',
                      'cover': 'div.manga-summary-cover img', 'next': 'div.pagination a.page-numbers:-soup-contains-own("다음")',
                      'page_images': 'div.reading-content img'},
    }),
)

# The MediaVault registry enables a profile after testing its complete
# search-to-CBZ path. The remaining profiles can be tested independently.
ENABLED = frozenset({
    '5944672760629857205',  # Bun Manga
    '5246625723235112128',  # GakaMangas
    '8802607595629671202',  # LHTranslation
    '3971812949560196318',  # Lovesjane Scans
    '5229341270935044914',  # Manga Eclipse
    '3606721916149050760',  # Mangasushi
    '7638481723868333116',  # ManhuaHot
    '6032516943051342273',  # TritiniaScans
    '7008887237419113673',  # Grabber Zone
    '626267698662819838',  # Aqua Manga
    '9030178752551947945',  # Manhua Plus
    '3663840686576348637',  # ManhwaNex
    '2681651342533848540',  # MangaRead.org
})
