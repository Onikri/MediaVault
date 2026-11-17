"""Adapters of the ninth (final) Suwayomi migration batch."""

import manga_hiper
import manga_taddyink

MODULES = (manga_hiper, manga_taddyink)
SOURCES = tuple(source for module in MODULES for source in module.SOURCES)
