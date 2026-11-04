# Room playback and library layout regression fixes

Room snapshots now share one pending play request per media element, defer playback until media data is available, and pause only when required. Normal interrupted starts (`AbortError`) are superseded commands, while autoplay denial offers an explicit activation button. Room playback no longer competes with independent player autoplay. Readiness acknowledges buffering without repeatedly forcing timeline seeks. The local clock extrapolates the latest playing state rather than capping elapsed time at two seconds. Guests cannot use local controls to start playback when the room is paused.

The guest page uses the title showcase geometry, backdrop/video service, cover, description, genres and participant information. Background availability still depends on title metadata and the existing background service; missing artwork is not fabricated.

The online library's external-filter content explicitly uses a single content column. This overrides the stronger shared catalogue grid selector that continued reserving an unused inner sidebar. Outer sidebars and mobile navigation remain in place.

Validation: 284 Node tests; real FastAPI WebSocket/Range room with two Chromium pages, pause, seek and four repeated play/pause cycles; room widths390/768/1440; library layout390/768/1024/1440; source catalogue and import browser contracts. All media in room tests is fixture video. No production user's credentials or decrypted library files enter tests. Frontend-only fix; no Oracle deployment or data migration is required.
