"""Adapters of the tenth migration batch: the Suwayomi-only extensions left
after the ninth batch (package C of the Suwayomi decommission plan).

Their requests use the same ``n9:<name>`` route declarations as the ninth
batch (``manga_ninth_routes``).
"""

import manga_azuki
import manga_comicfuz
import manga_coolmic
import manga_emaqi
import manga_inkr
import manga_jnovel
import manga_kmanga
import manga_mangaup_global
import manga_mangaz
import manga_mehgazone
import manga_pawchive
import manga_tapas
import manga_webnovel

MODULES = (manga_azuki, manga_comicfuz, manga_coolmic, manga_emaqi, manga_inkr, manga_jnovel, manga_kmanga, manga_mangaup_global, manga_mangaz, manga_mehgazone, manga_pawchive, manga_tapas, manga_webnovel)
SOURCES = tuple(source for module in MODULES for source in module.SOURCES)
