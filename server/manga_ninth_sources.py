"""Adapters of the ninth (final) Suwayomi migration batch."""

import manga_hiper
import manga_taddyink
import manga_tappytoon
import manga_yaoime
import manga_nudemoon
import manga_webcomicsapp

MODULES = (manga_hiper, manga_taddyink, manga_tappytoon, manga_yaoime, manga_nudemoon, manga_webcomicsapp)
SOURCES = tuple(source for module in MODULES for source in module.SOURCES)
