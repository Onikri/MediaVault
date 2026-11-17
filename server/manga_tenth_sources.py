"""Adapters of the tenth migration batch: the Suwayomi-only extensions left
after the ninth batch (package C of the Suwayomi decommission plan).

Their requests use the same ``n9:<name>`` route declarations as the ninth
batch (``manga_ninth_routes``).
"""

import manga_comicfuz
import manga_mangaz
import manga_mehgazone
import manga_pawchive

MODULES = (manga_comicfuz, manga_mangaz, manga_mehgazone, manga_pawchive)
SOURCES = tuple(source for module in MODULES for source in module.SOURCES)
