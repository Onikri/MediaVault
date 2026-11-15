"""Installed independent reader profiles matched to their Keiyoushi routes."""

from dataclasses import replace

from manga_webcomic_identities import IDENTITIES
from manga_webcomic_protocols import (
    arknights_archive, arknights_catalogue, arknights_identity, arknights_pages,
    clone_archive, clone_catalogue, clone_identity, collected_archive, collected_identity,
    darklegacy_archive, darklegacy_identity, egs_archive, egs_identity,
    honkai_archive, honkai_catalogue, loading_archive, nux_catalogue, nux_pages, parent_path,
    patch_archive, randowis_archive, random_chat_archive, sandra_archive, single_madara_archive, single_madara_pages, solar_archive, solar_pages,
    supermega_archive, vagabond_archive, vagabond_catalogue, vagabond_identity, vagabond_pages,
    vgperson_archive, vgperson_catalogue, vgperson_identity, vision_archive, vision_pages,
)
from manga_webcomics import Archive, Profile, Reader, Work


BLOG_IMAGES = ('blogger.googleusercontent.com', 'bp.blogspot.com')
DATE_POST = r'/\d{4}/\d{2}/\d{2}/[^/]+/?'


def single(path, title, cover='', *, author='', aliases=(), archive_url='', archive=None, images='', reader=None, **options):
    return Profile((Work(path, title, cover, author=author, aliases=aliases, archive=archive_url),),
                   archive, reader or (Reader(images) if images else None), **options)


def wordpress_series(title, chapter, allowed_hosts, *, selector='.entry-content img'):
    return single('/', title, archive=Archive(f'a[href*="{chapter}"]', number=rf'{chapter}(\d+(?:[.,]\d+)?)'),
                  reader=Reader(selector, image_hosts=(*BLOG_IMAGES, *allowed_hosts), exclude_crop=True),
                  chapter_path=rf'/(?:manga/)?[\w-]*{chapter}[\w.-]+/?', enrich=True)


def sandra(language):
    directory = '/woode' if language == 'de' else ''
    title = 'Sandra und Woo' if language == 'de' else 'Sandra and Woo'
    path = directory + ('/archiv' if language == 'de' else '/archive')
    return single(path, title, '/images/fanart/fanart-contest-2014/pictures/zheng-qu-01-color-corrected.jpg',
                  author='Oliver Knörzer', images='#comic img', chapters=sandra_archive,
                  chapter_path=directory + DATE_POST)


PROFILES_BY_PACKAGE = {
    'questionablecontent': single('/archive.php', 'Questionable Content', 'https://i.ibb.co/ZVL9ncS/qc-teh.png',
                                  author='Jeph Jacques', archive=Archive('div#container a[href^="view.php?comic="]', number=r'[?&]comic=(\d+)'),
                                  reader=Reader('#strip', notes='#newspost'), chapter_path=r'/view\.php', chapter_query='comic'),
    'battleinfivesecondsaftermeeting': single('/', 'Battle In 5 Seconds After Meeting', aliases=('Deatte 5-byou de Battle', 'Battle Game in 5 Seconds'),
                                              chapters=single_madara_archive, pages=single_madara_pages, enrich=True,
                                              chapter_path=r'/manga/[\w.-]+/?', legacy_chapter_prefix='/manga/',
                                              title_selector='h1', cover_selector='.cover_managa img', description_selector='.synopsis p'),
    'frierenonline': single('/', 'Frieren: Beyond Journey’s End', aliases=('Sousou no Frieren', 'Frieren Online'),
                            chapters=single_madara_archive, pages=single_madara_pages, enrich=True,
                            chapter_path=r'/manga/[\w.-]+/?', legacy_chapter_prefix='/manga/',
                            title_selector='.about h1', cover_selector='.cover_managa img', description_selector='.synopsis', genres_selector='.tags a[rel=tag]'),
    'gwtb': single('/index.php', 'Gone with the Blastwave', '/images/yarr.jpg', author='Kimmo Lemetti',
                   archive=Archive('.fall > option[value]:not(:first-child)', href='value', query_key='nro', number=r'[?&]nro=(\d+)'),
                   images='.comic_title + img', chapter_path=r'/index\.php', chapter_query='nro'),
    'existentialcomics': single('/archive/byDate', 'Existential Comics', 'https://i.ibb.co/pykMVYM/existential-comics.png',
                                author='Corey Mohler', archive=Archive('#date-comics ul li a:first-of-type',
                                                                      reverse=True, number=r'/comic/(\d+)'),
                                images='.comicImg', chapter_path=r'/comic/[\w-]+/?'),
    'supermega': single('/', 'SUPER MEGA', '/runningman.png', author='JohnnySmash', chapters=supermega_archive,
                        images='img[border="4"]', chapter_path='/', chapter_query='i'),
    'gunnerkriggcourt': single('/archives/', 'Gunnerkrigg Court', 'https://i.imgur.com/g2ukAIKh.jpg', author='Tom Siddell',
                               archive=Archive('div.chapters option[value]', href='value', query_key='p', query_path='/', number=r'[?&]p=(\d+)', reverse=True),
                               images='.comic_image', chapter_path=r'/(?:index\.php)?', chapter_query='p'),
    'imanevilgod': single('/', "I'm An Evil God", aliases=('I Am an Evil God', 'Way to Be the Evil Emperor'),
                          archive=Archive('p.has-medium-font-size a[href*="imanevilgod.com"]'),
                          images='div.entry-content img', chapter_path=r'/[\w-]+/?', enrich=True),
    'clonemanga': Profile(browse=clone_catalogue, chapters=clone_archive,
                          reader=Reader('.subsectionContainer img'), title_path=r'/viewer\.php',
                          chapter_path=r'/viewer\.php', chapter_query='page', title_for=clone_identity),
    'honkaiimpact': Profile(browse=honkai_catalogue, chapters=honkai_archive, title_for=parent_path,
                            enrich=True, title_selector='div.title', description_selector='div.detail_info1',
                            cover_selector='img.cover', reader=Reader('img.lazy.comic_img', ('data-original', 'src')),
                            title_path=r'/book/\d+/?', chapter_path=r'/book/\d+/\d+/?'),
    'elanschool': single('/chapters/?dps_paged=1', 'Elan School', '/wp-content/uploads/2018/11/The-Elan-School-Comic-1cNEW-1-768x1491.jpg',
                         author='Joe Nobody', archive=Archive('div.listing-item > a.title', next_page='a.next', reverse=True),
                         images='img[data-orig-file]:not(a *)', chapter_path=r'/[\w/-]+/?',
                         legacy_title={'/chapters': '/chapters/?dps_paged=1'}),
    'oots': single('/comics/oots.html', 'The Order Of The Stick', 'https://i.giantitp.com/redesign/Icon_Comics_OOTS.gif',
                   author='Rich Burlew', aliases=('OOTS',), archive=Archive('p.ComicList a', reverse=True, number=r'oots(\d+)\.html'),
                   images='td[align="center"] > img', chapter_path=r'/comics/oots\d+\.html'),
    'loadingartist': single('/archives', 'Loading Artist', '/img/bg/logo-text_dark.png', author='Loading Artist',
                            chapters=loading_archive, images='div.main-image-container img'),
    'onepunchmanonline': single('/', 'One Punch Man', 'https://1punchman.com/wp-content/uploads/2024/02/9782380712018_1_75.jpg',
                                author='ONE', aliases=('One-Punch Man',), archive=Archive('ul li a[href*="/manga/"]', number=r'chapter-(\d+(?:\.\d+)?)'),
                                images='div.entry-content img, .separator img, p img', chapter_path=r'/manga/[\w.-]+/?'),
    'kaijimangaonline': wordpress_series('Kaiji', 'chapter-', ('img.kaijimanga.com', 'kaijimanga.com')),
    'maidsamamangaonline': wordpress_series('Maid Sama', 'maid-sama-chapter-', ('img.maid-sama.com',)),
    'ruridragonmangaonline': wordpress_series('RuriDragon', 'ruridragon-chapter-', ('img.ruridragon.com', 'ruridragon.com')),
    'theexiledheavyknightmangaonline': wordpress_series('The Exiled Heavy Knight', 'the-exiled-heavy-knight-knows-how-to-game-the-system-chapter-',
                                                       ('pic.readkakegurui.com', 'img.theexiledheavyknight.com', 'theexiledheavyknight.com'),
                                                       selector='.post-single-content img, .entry-content img'),
    'readhorimiyaonline': single('/', 'Horimiya', archive=Archive('div#chapter-list a.chapter-list-item',
                                                                 title='span.chapter-name', number=r'chapter[-/](\d+(?:\.\d+)?)',
                                                                 date='span.chapter-date', date_format='%B %d, %Y'),
                                 images='div.images-container img', cover_selector='img.manga-thumb', description_selector='span.desc',
                                 genres_selector='span.genre-list-item', enrich=True, chapter_path=r'/[\w./-]+/?'),
    'thegirlfromrandomchattingmangaonline': single('/', 'The Girl from Random Chatting', author='Eun Hyuk Park',
                                                  chapters=random_chat_archive, enrich=True,
                                                  cover_selector='figure.wp-block-gallery figure.wp-block-image:last-child noscript img',
                                                  images='p > noscript > img', chapter_path=r'/manga/[\w.-]+/?',
                                                  legacy_title={'/the-girl-from-random-chatting': '/'}, legacy_chapter_prefix='/manga/'),
    'readvagabondmanga': Profile(browse=vagabond_catalogue, chapters=vagabond_archive, pages=vagabond_pages,
                                 title_for=vagabond_identity, title_path='/', chapter_path=r'/volume-(?:\d+|null)/chapter-\d+/?'),
    'vixenlogic': single('/', 'Vixen Logic', '/wp-content/uploads/2026/06/VL_Cover_Toocheke.png',
                         archive_url='/archives/', archive=Archive('a[href]:has(.comic-item)', title='.comic-title', date='.comic-post-date', date_format='%B %d, %Y'),
                         images='#comic p a img'),
    'randowiz': Profile((Work('/category/we-live-in-an-mmo/', 'Randowiz: We live in an MMO!?',
                              '/wp-content/uploads/2016/02/MMO_CHP_001_CSP_000.jpg', author='Randowiz'),
                         Work('/category/short-comics/', 'Randowiz: Short comics', author='Randowiz'),
                         Work('/category/art/', 'Randowiz: Illustrations', author='Randowiz')),
                        chapters=randowis_archive, reader=Reader('.elementor-widget-theme-post-content img')),
    'collectedcurios': Profile((
        Work('/sequentialart.php', 'Sequential Art', '/images/CC_2011_Sequential_Art_Button.jpg', author='Phillip M. Jackson'),
        Work('/battlebunnies.php', 'Battle Bunnies', '/images/CC_2011_Battle_Bunnies_Button.jpg', author='Phillip M. Jackson'),
        Work('/spiderandscorpion.php', 'Spider & Scorpion', '/images/CC_2011_Spider_And_Scorpion_Button.jpg', author='Phillip M. Jackson'),
    ), chapters=collected_archive, reader=Reader('.w3-image, #strip'), title_for=collected_identity,
        chapter_path=r'/(?:sequentialart|battlebunnies|spiderandscorpion)\.php', chapter_query='s'),
    'darklegacycomics': Profile((Work('/archive', 'Dark Legacy Comics', 'https://images2.imgbox.com/5d/d8/BVxRdljH_o.png', author='Arad Kedar'),
                                 Work('/specials/1.php', 'Dark Legacy Comics Specials', 'https://images2.imgbox.com/5d/d8/BVxRdljH_o.png', author='Arad Kedar')),
                                chapters=darklegacy_archive, reader=Reader('.comic > img'), title_for=darklegacy_identity,
                                chapter_path=r'/(?:\d+|specials/[1-3])/?'),
    'egscomics': Profile((Work('/comic/archive', 'El Goonish Shive', author='Dan Shive'),
                          Work('/egsnp/archive', 'El Goonish Shive: NewsPaper', author='Dan Shive'),
                          Work('/sketchbook/archive', 'El Goonish Shive Sketchbook', author='Dan Shive')),
                         chapters=egs_archive, reader=Reader('#cc-comic'), title_for=egs_identity,
                         chapter_path=r'/(?:comic|egsnp|sketchbook)/[\w.-]+/?'),
    'darkscience': single('/category/darkscience/', 'Dark Science', '/wp-content/uploads/2019/03/DC_CastIcon_Kimiko.png',
                          author='Sen (A. Senna Diaz)', archive=Archive('#content article header > h2 > a', next_page='#nav-below .nav-previous > a',
                                                                       number=r'dark-science-?(?:chapter-)?(\d+)'),
                          images='article.post img.aligncenter', chapter_path=DATE_POST),
    'megatokyo': single('/archive.php?list_by=date', 'Megatokyo', 'https://i.ibb.co/yWQM1gY/megatokyo.png',
                        author='Fred Gallagher', archive=Archive('div.content h2:-soup-contains("Comics by Date") + div ul li a[name]',
                                                                number=r'/(\d+)/?$', reverse=True),
                        images='#strip img', chapter_path=r'/(?:strip/)?\d+/?', legacy_title={'/archive.php': '/archive.php?list_by=date'}),
    'sandraandwoo_en': sandra('en'),
    'sandraandwoo_de': sandra('de'),
    'swordscomic': single('/archive/pages/', 'Swords Comic', '/media/ArgoksEdgeEmote.png',
                          archive=Archive('a.archive-tile', title='strong', date='small', date_format='%B %d, %Y', reverse=True),
                          reader=Reader('img#comic-image', notes='img#comic-image', notes_attr='title'),
                          chapter_path=r'/comic/[\w.-]+/?'),
    'saturdaymorningbreakfastcomics': single('/comic/archive', 'Saturday Morning Breakfast Comics', author='Zach Weinersmith',
                                            aliases=('SMBC',), archive=Archive('option[value*="comic/"]', href='value', prefix='/', reverse=True),
                                            reader=Reader('img#cc-comic, #aftercomic > img', notes='img#cc-comic', notes_attr='title'),
                                            chapter_path=r'/comic/[\w.-]+/?', hosts=('www.smbc-comics.com',)),
    'solarandsundry': single('/page', 'Solar and Sundry',
                             'https://imagedelivery.net/zthi1l8fKrUGB5ig08mq-Q/de292ba7-f164-4f43-ec17-1876a7a44600/public',
                             chapters=solar_archive, pages=solar_pages, chapter_path=r'/page/\d+'),
    'arknightscomics': Profile(browse=arknights_catalogue, chapters=arknights_archive, pages=arknights_pages,
                               title_for=arknights_identity, title_path=r'/comic/?', title_query='name',
                               chapter_path=r'/comic-detail/?', chapter_query='chapter'),
    'visionhaze': single('/', 'Vision Haze', '/_assets/media/banners/banner0.png', author='Yttrium',
                         chapters=vision_archive, pages=vision_pages, chapter_path=r'/(?:index\.php)?', chapter_query='p'),
    'patchfriday': single('/', 'Patch Friday', '/patches/68.png', chapters=patch_archive, images='div#strip_image img',
                           chapter_path=r'/\d+/?'),
    'vgperson': Profile(browse=vgperson_catalogue, chapters=vgperson_archive, reader=Reader('img'),
                        title_for=vgperson_identity, enrich=True, title_selector='.title',
                        title_path=r'/other/mangaviewer\.php', title_query='m', chapter_path=r'/other/mangaviewer\.php', chapter_query='c|b'),
    'nuxscans': Profile(browse=nux_catalogue, archive=Archive('.row-chapters .list-item a', reverse=True),
                        pages=nux_pages, reader=Reader('.post-body img:not(.watermark), .holder img:not(.watermark)'),
                        title_path=r'/\d{4}/\d{2}/[\w.-]+\.html', chapter_path=r'/\d{4}/\d{2}/[\w.-]+\.html',
                        hosts=('nuxscans.blogspot.com',), enrich=True,
                        html_redirect=r"""window\.location\.replace\(['"]([^'"]+)['"]\)""",
                        title_selector='h1.post-title', cover_selector='.post-thumbnail img',
                        description_selector='.post-details h3:-soup-contains("Synopsis") + p',
                        genres_selector='.post-tab-genre .post-genre a', author_selector='.post-details p:-soup-contains("Author:")'),
}


# The Kaiji archive uses the arc name before the chapter number.
PROFILES_BY_PACKAGE['kaijimangaonline'] = replace(PROFILES_BY_PACKAGE['kaijimangaonline'],
                                                chapter_path=r'/manga/[\w-]+-chapter-\d+/?')
PROFILES = tuple((IDENTITIES[key], profile) for key, profile in PROFILES_BY_PACKAGE.items())
