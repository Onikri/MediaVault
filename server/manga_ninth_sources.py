"""Adapters of the ninth (final) Suwayomi migration batch."""

import manga_hiper
import manga_taddyink
import manga_tappytoon
import manga_yaoime
import manga_nudemoon
import manga_webcomicsapp
import manga_kisslove
import manga_supabase_scans
import manga_gravureprincess

MODULES = (manga_hiper, manga_taddyink, manga_tappytoon, manga_yaoime, manga_nudemoon, manga_webcomicsapp, manga_kisslove, manga_supabase_scans, manga_gravureprincess)
SOURCES = tuple(source for module in MODULES for source in module.SOURCES)
