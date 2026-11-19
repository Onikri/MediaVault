"""Language scope for manga profile discovery, indexing and routine verification."""
LANGUAGES = frozenset({'en', 'ru', 'uk', 'ja', 'ko', 'zh'})
PROFILE_LANGUAGES = LANGUAGES | {'all'}


def primary_language(value):
    return value.lower().replace('_', '-').partition('-')[0] if isinstance(value, str) else ''


def included(value):
    return primary_language(value) in PROFILE_LANGUAGES
