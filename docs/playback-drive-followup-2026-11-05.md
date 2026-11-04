# Playback preparation, lyrics and background Drive status

The watch page warms only the selected episode's resolver and HLS manifests when
the watch control comes into view, after an idle delay, or on focus/hover. It does
not download video segments. Repeated preparation is deduplicated for 45 seconds;
changing the source or starting playback cancels speculative work. Save-Data and
hidden tabs skip it. The short preview capability is closed immediately.

Real playback invalidates its owner's pending preview reservations and releases
that owner's preview leases before checking session capacity. Existing manga,
music, real playback and other users' sessions remain intact. Resolver singleflight
still shares in-flight work. VOD/master caches last at most 90 seconds, explicitly
signed expiry shortens this, and live media playlists last at most five seconds.
All qualities, external audio and subtitle groups remain supported. This reduces
repeated work; it does not guarantee a fast cold response from every provider.
First episode-card capture seeks at most two seconds into the video, rather than
eight percent of the episode. Further hover frames remain available.

The profile distinguishes browser Drive access from the VM's offline grant.
Protected status/check endpoints expose no tokens, use a bounded Google refresh,
and retain rejected credentials and unfinished jobs. A rejected old token cannot
mark a newly replaced grant invalid. Job polling updates the connection badge;
the waiting-auth queue shows a reconnect action. No jobs are cancelled to free
capacity. An invalid_grant still requires fresh consent through the VM connection.

Lyrics can start using verified catalogue or selected-record duration before audio
has loaded. Actual media duration takes precedence once available, followed by
the selected upload; catalogue duration is a last resort because it can name a TV
edit rather than the full song. MusicBrainz
artist aliases and sort names participate in matching, including native/Latin
forms. An empty, restricted or failed server lookup can consult public LRCLIB
and AMLL independently; this does not bypass provider restrictions. Plain text is
never presented as synchronized words. Expired YouTube cookies are not repaired
by metadata changes; the server session must be renewed when YouTube rejects it.

Validation: 38 focused Python tests, 15 Node tests, a React browser contract check
at 390/1440 pixels, and a production build. Browser providers/Google refresh are
fixtures: these checks establish cancellation, grant state, lookup without audio
and fallback behavior, not successful live YouTube authentication or real ML
inference. This change adds no model or changes to neural inference.

Live VM verification: all 72 tasks and encrypted configuration survived the update.
The WORLD returned plain LRCLIB lyrics; Otonoke and IRIS OUT returned timed
Musixmatch lines. The saved background Drive grant still returns needs_consent,
and an actual Otonoke audio preparation still receives YouTube's sign-in challenge.
These authentication requirements remain visible and require renewed consent;
successful lyric lookup does not establish playable audio.
