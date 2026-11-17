"""Every direct adapter written for the Suwayomi migration, keyed by source ID.

``profiles()`` imports all ported families (activated or not); the reader,
search and catalogue only use the IDs listed in ``manga_native_activation.json``
after a live check of catalogue, chapter list and pages on the server.
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def profiles():
    import manga_fifth_batch_profiles
    import manga_additional_catalogues
    import manga_booru_pools
    import manga_bookwalker_jp
    import manga_akuma
    import manga_cubari
    import manga_japanese_readers
    import manga_mangack
    import manga_mangahere
    import manga_pornpics
    import manga_sugocomics
    import manga_ninth_sources
    import manga_tenth_sources
    import manga_mangalix
    import manga_toonz
    import manga_viz
    import manga_comicklive
    import manga_japanese_next
    import manga_asura_native
    import manga_alphapolis
    import manga_blacktoon
    import manga_ciaoplus
    import manga_clipstudio_sources
    import manga_corocoro
    import manga_coronaex
    import manga_dle_readers
    import manga_dynasty
    import manga_drecomics
    import manga_docomo
    import manga_dmm
    import manga_ebookrenta
    import manga_flower_comics
    import manga_lusttoon
    import manga_mangabox
    import manga_mangameets
    import manga_mangaone
    import manga_mangafive
    import manga_mangaplaza
    import manga_publus_sources
    import manga_pixivcomic
    import manga_momonga
    import manga_mokuro
    import manga_nicomanga
    import manga_park_publisher
    import manga_toomics
    import manga_toonkotsu
    import manga_fourkhd
    import manga_honeytoon_native
    import manga_hakusensha
    import manga_honto
    import manga_jjcos
    import manga_multporn
    import manga_ososedki
    import manga_twicomi
    import manga_voyceme
    import manga_alpha_manga
    import manga_catalogue_api_ports
    import manga_comic_museum
    import manga_comic_grast
    import manga_comics_kingdom
    import manga_ksbd
    import manga_korean_seventh
    import manga_ninehentai
    import manga_toon11
    import manga_girlstop
    import manga_manhwazone
    import manga_rawkuma_overlay
    import manga_reimanga
    import manga_vyvy
    import manga_gallery_archive_ports
    import manga_klto9
    import manga_mangaplus
    import manga_mangamee
    import manga_manta_native
    import manga_omega
    import manga_rinko
    import manga_unicomics
    import manga_webnex
    import manga_yellownote
    import manga_nexus_reader
    import manga_rayuba
    import manga_seventh_data
    import manga_seventh_html
    import manga_zerosum
    import manga_small_readers
    import manga_scan_api_ports
    import manga_luscious_native
    import manga_pandachaika
    import manga_simply_native
    import manga_toonlook
    import manga_wordpress_locales
    import manga_niadd_novelcool
    import manga_sixth_profiles
    import manga_speedbinb_sources
    import manga_webtoons_native
    import manga_fourth_batch_profiles
    import manga_archive_ports
    import manga_bakkin
    import manga_comicfury
    import manga_comici
    import manga_dbmultiverse
    import manga_direct_articles
    import manga_direct_catalogues
    import manga_direct_payloads
    import manga_foolslide
    import manga_gigaviewer
    import manga_globalcomix
    import manga_gallery_adults
    import manga_guya
    import manga_hentaihand
    import manga_html_families
    import manga_individual_catalogues
    import manga_json_families
    import manga_loluniverse
    import manga_mangadventure
    import manga_mangaball_native
    import manga_mangadex_native
    import manga_mangadot
    import manga_mangamillion
    import manga_mangatoon
    import manga_mangak
    import manga_masonry
    import manga_multichan
    import manga_namicomi
    import manga_saymanhwa
    import manga_ru_families
    import manga_mangashi, manga_mangahub, manga_madara, manga_themesia, manga_iken, manga_mangacatalog
    import manga_keyoapp, manga_vinetheme
    import manga_webcomics
    import manga_xcomic
    import manga_yii

    profiles = {manga_mangashi.SOURCE_ID: manga_mangashi}
    for module in (manga_madara, manga_themesia, manga_keyoapp, manga_vinetheme,
                   manga_mangacatalog, manga_iken, manga_mangahub, manga_hentaihand,
                   manga_comici, manga_gigaviewer, manga_yii, manga_guya, manga_mangadventure,
                   manga_mangak, manga_masonry, manga_multichan, manga_bakkin, manga_loluniverse,
                   manga_mangadex_native, manga_foolslide, manga_mangaball_native, manga_mangamillion,
                   manga_mangadot, manga_namicomi, manga_globalcomix, manga_dbmultiverse,
                   manga_saymanhwa, manga_mangatoon, manga_xcomic, manga_comicfury):
        profiles.update((adapter.SOURCE_ID, adapter) for adapter in module.SOURCES)
    profiles.update((adapter.SOURCE_ID, adapter) for adapter in manga_webcomics.adapters())
    profiles.update((adapter.SOURCE_ID, adapter) for adapter in manga_fourth_batch_profiles.sources())
    profiles.update((adapter.SOURCE_ID, adapter) for adapter in manga_fifth_batch_profiles.sources())
    for group in (manga_archive_ports.SOURCES, manga_html_families.SOURCES, manga_individual_catalogues.SOURCES,
                  manga_json_families.sources(), manga_ru_families.SOURCES, manga_direct_articles.sources(),
                  manga_direct_catalogues.sources(), manga_direct_payloads.sources(), manga_gallery_adults.sources(),
                  manga_speedbinb_sources.SOURCES, manga_webtoons_native.SOURCES, manga_niadd_novelcool.SOURCES,
                  manga_sixth_profiles.SOURCES, manga_wordpress_locales.SOURCES, manga_simply_native.SOURCES,
                  manga_luscious_native.SOURCES, manga_additional_catalogues.SOURCES, manga_pandachaika.SOURCES,
                  manga_toonlook.SOURCES, manga_alpha_manga.SOURCES, manga_catalogue_api_ports.SOURCES,
                  manga_gallery_archive_ports.SOURCES, manga_klto9.SOURCES, manga_mangaplus.SOURCES,
                  manga_small_readers.SOURCES, manga_scan_api_ports.SOURCES, manga_manta_native.SOURCES,
                  manga_comic_museum.SOURCES, manga_mangamee.SOURCES, manga_omega.SOURCES,
                  manga_rinko.SOURCES, manga_unicomics.SOURCES, manga_webnex.SOURCES, manga_yellownote.SOURCES,
                  manga_seventh_data.SOURCES, manga_seventh_html.SOURCES, manga_rayuba.SOURCES,
                  manga_zerosum.SOURCES, manga_nexus_reader.SOURCES, manga_comics_kingdom.SOURCES,
                  manga_comic_grast.SOURCES, manga_ksbd.SOURCES, manga_girlstop.SOURCES,
                  manga_reimanga.SOURCES, manga_vyvy.SOURCES, manga_manhwazone.SOURCES,
                  manga_rawkuma_overlay.SOURCES, manga_korean_seventh.SOURCES, manga_toon11.SOURCES,
                  manga_ninehentai.SOURCES, manga_comicklive.SOURCES, manga_jjcos.SOURCES,
                  manga_twicomi.SOURCES, manga_booru_pools.SOURCES, manga_ososedki.SOURCES,
                  manga_honeytoon_native.SOURCES, manga_fourkhd.SOURCES, manga_voyceme.SOURCES, manga_multporn.SOURCES,
                  manga_japanese_next.SOURCES, manga_mangameets.SOURCES, manga_momonga.SOURCES,
                  manga_park_publisher.SOURCES, manga_toomics.SOURCES, manga_mangaone.SOURCES,
                  manga_mangabox.SOURCES, manga_asura_native.SOURCES, manga_corocoro.SOURCES,
                  manga_ciaoplus.SOURCES, manga_lusttoon.SOURCES, manga_blacktoon.SOURCES, manga_nicomanga.SOURCES,
                  manga_dle_readers.SOURCES, manga_dynasty.SOURCES, manga_mokuro.SOURCES, manga_toonkotsu.SOURCES,
                  manga_clipstudio_sources.SOURCES, manga_honto.SOURCES, manga_hakusensha.SOURCES,
                  manga_mangaplaza.SOURCES, manga_ebookrenta.SOURCES, manga_drecomics.SOURCES,
                  manga_flower_comics.SOURCES, manga_alphapolis.SOURCES, manga_coronaex.SOURCES, manga_publus_sources.SOURCES,
                  manga_docomo.SOURCES, manga_mangafive.SOURCES, manga_dmm.SOURCES, manga_pixivcomic.SOURCES,
                  manga_bookwalker_jp.SOURCES, manga_mangalix.SOURCES, manga_toonz.SOURCES, manga_cubari.SOURCES,
                  manga_mangahere.SOURCES, manga_mangack.SOURCES, manga_viz.SOURCES, manga_pornpics.SOURCES,
                  manga_akuma.SOURCES, manga_japanese_readers.SOURCES, manga_sugocomics.SOURCES,
                  manga_ninth_sources.SOURCES, manga_tenth_sources.SOURCES):
        profiles.update((adapter.SOURCE_ID, adapter) for adapter in group)
    standby = manga_mangahub.MANGA_HERE
    profiles[standby.SOURCE_ID] = standby
    return profiles
