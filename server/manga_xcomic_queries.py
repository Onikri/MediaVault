"""Public read-only GraphQL documents from Keiyoushi's XCOMIC adapter."""

BROWSE = 'get_title_browse_items'
PAGER = 'get_title_browse_pager'
TITLE = 'get_title_titleNode'
EDITION = 'get_comicNode'
PROBE = 'comic_probe'
UNIQUE = 'get_comic_chapterList_uniqList'
FULL = 'get_comic_chapterList_fullList'
PAGES = 'get_chapterNode'

TITLE_FIELDS = '''
    id title alt_titles native_title romanized_title original_language
    translated_languages authors artists year type status description
    cover_local_url cover_url is_merged merged_to comic_ids
    content_rating_id type_id demographic_ids genre_ids format_ids
    tracking_sites { anilist myanimelist mangaupdates kitsu animeplanet shikimori mangabaka }
'''
CHAPTER_FIELDS = '''
    id dbStatus isFinal volume serial dname title urlPath
    dateCreate datePublic dateModify chaNum volNum count_images srcName
'''

QUERIES = {
    BROWSE: '''query get_title_browse($select: Title_Browse_Select) {
        get_title_browse_items(select: $select) { id data {
            title native_title romanized_title original_language translated_languages
            type cover_local_url cover_url comic_ids chap_last_public_at
        } }
    }''',
    PAGER: '''query get_title_browse_pager($select: Title_Browse_Select) {
        get_title_browse_pager(select: $select) { next total }
    }''',
    TITLE: 'query get_title_titleNode($id: ID!) { get_title_titleNode(id: $id) { id data {' + TITLE_FIELDS + '} } }',
    EDITION: '''query get_comicNode($id: ID!) { get_comicNode(id: $id) { id data {
        id name subName altNames originalLanguage translatedLanguage originalStatus uploadStatus type
        demographics contentRating genres tags dbStatus isPublic chaps_normal
        summary { text } readDirection urlCover
        title_titleNode { id data {''' + TITLE_FIELDS + '''} }
    } } }''',
    PROBE: '''query get_comicNode($id: ID!) { get_comicNode(id: $id) {
        id data { subName dbStatus isPublic translatedLanguage chaps_normal }
    } }''',
    UNIQUE: '''query get_comic_chapterList_uniqList($select: Select_Comic_ChapterList_UniqList) {
        get_comic_chapterList_uniqList(select: $select) { paging { next total } items { id data {'''
        + CHAPTER_FIELDS + '''} } }
    }''',
    FULL: '''query get_comic_chapterList_fullList($select: Select_Comic_ChapterList) {
        get_comic_chapterList_fullList(select: $select) { paging { next total } items { id data {'''
        + CHAPTER_FIELDS + '''} } }
    }''',
    PAGES: 'query($id: ID!) { get_chapterNode(id: $id) { id data { imageUrls } } }',
}
QUERIES = {key: ' '.join(value.split()) for key, value in QUERIES.items()}
OPERATIONS = {value: key for key, value in QUERIES.items()}
