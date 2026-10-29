# Music in the navigation

`MiniMusicPlayer placement="nav"` is the single playback controller. Desktop
shows cover/title, play/pause and seek in the navbar. Below 900 px it becomes an
icon immediately before the profile; tapping opens the detail sheet. A downward
swipe of 70 px closes the sheet. Native/Spotify audio can continue in the compact
bar; the official YouTube video is paused when the sheet is closed or the document
becomes hidden. The sheet is portalled to `document.body` so page stacking contexts
cannot cover its controls. Reduced-motion preference disables the opening animation.

## Official playback

YouTube playback still uses `YouTubeEmbed` and the IFrame Player API. The visible
video viewport stays at least 200×200. The original video title/author selector is
preserved separately from song metadata. This implementation does not hide an
actively playing video, extract audio, block advertisements or assert that Google
sign-in enables Premium benefits inside an embed. Video ads remain under YouTube's
control. Media Session integration is used only for native/Spotify audio.

Spotify uses its Web Playback SDK, not a hidden Spotify iframe. It needs a
registered public client ID, allowed callback URI/user and Spotify Premium.
`MusicConnections` in Profile and the music sheet supplies explicit OAuth PKCE
connection, playlist listing, creation, selected recording addition and first-50
playlist-track loading. Creation uses `POST /me/playlists` with `public:false`;
addition uses `/playlists/{id}/items`. YouTube playlists use separate YouTube OAuth
consent, not the existing MediaVault Google login. Account connections and SDK
playback require actual user/provider authorization; their success is not inferred
from a configured client ID. No credentials have been provisioned for Spotify by
this change.

OAuth access tokens and PKCE verifier remain in tab memory. Only the public Spotify
client ID persists. Expired connections require explicit reconnect; logout/library
lock and profile change clear the in-memory music connection. Provider playlist
changes happen only after the corresponding button is pressed.

## Song metadata and remote artwork

`GET /music/metadata?title=…&artist=…` searches MusicBrainz for a title/artist match.
It returns identifiers, title, artist, release/date, duration, confidence and a
Cover Art Archive URL; it never downloads artwork or audio. Artwork loads directly
from that provider. Spotify artwork also uses Spotify's returned remote URL.
When song artwork is unavailable, YouTube recordings use their official i.ytimg.com thumbnail URL. Failed artwork uses a neutral music icon. Metadata does not overwrite
the YouTube video's title.

The server cache is memory-only, limited to 256 small metadata entries for six
hours. Empty matches expire after five minutes and provider failures after one
minute. MusicBrainz's shared request limiter is reused with artist lookup, plus
a non-queueing metadata slot to bound load. A failed metadata service does not
stop playback. On 2026-10-28 an actual Otonoke/Creepy Nuts request received the
upstream MusicBrainz HTTP 503 busy response; no successful live metadata/cover
lookup is claimed for that attempt.

## Validation boundaries

- `test_music_metadata.py`: five matching/cache/rate-limit/failure/URL contracts.
- `music-nav-browser.cjs`: navbar at 360/1440 px, official iframe dimensions,
  pause-on-collapse, reuse and missing-client-ID/account UI.
- `spotify-playback-browser.cjs`: actual PKCE/UI/adapter lifecycle with mocked
  OAuth, Spotify API and SDK; Premium scopes, private playlist creation, SDK
  playback, compact audio, disconnect and token non-persistence.
- Existing `music-browser.cjs` and `online-browser.cjs` continue to pass.

These browser tests simulate provider replies. They do not prove a real Spotify
account is authorized or that an official YouTube embed is ad-free.

## Primary documentation

- [YouTube developer policies](https://developers.google.com/youtube/terms/developer-policies-guide)
- [YouTube IFrame API](https://developers.google.com/youtube/iframe_api_reference)
- [Spotify Web Playback SDK](https://developer.spotify.com/documentation/web-playback-sdk/reference)
- [Spotify create playlist](https://developer.spotify.com/documentation/web-api/reference/create-playlist)
- [MusicBrainz rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)
- [Cover Art Archive API](https://musicbrainz.org/doc/Cover_Art_Archive/API)
