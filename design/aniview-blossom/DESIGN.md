# AniView Blossom — DESIGN.md

> **Purpose:** a reusable design language for an anime-discovery UI. **Provenance:** component behavior is recovered from the user-provided 2026 Vite chunks; the red/petal palette is **new**, extracted from the user-provided flower reference. This is not the original CSS or the original app source.

## 1. Art direction

**Core idea:** an editorial anime library where expressive cinematic imagery sits against a restrained, floral red-and-ink visual identity. The app should feel collectible, tactile, and cinematic, **not** like a generic purple-gradient AI SaaS dashboard.

Visual signature:
- A deep ink-black (#11191C) stage, offset by warm burgundy (#89051D) surfaces and vivid blossom red (#EE3C35).
- Porcelain petal text (#E6DDD8) instead of harsh white; warm secondary information (#D7B8AC).
- Singular hero artwork paired with asymmetric editorial typography and small uppercase labels.
- Curated 3:4 anime posters, strong bottom-to-top caption shade, subtle reveal motion.
- Pill navigation floats 16px from the top; translucent dark background emerges on scroll.
- **Hero flower photo is included as a mood/reference asset.** Do not paste the same flower image into every card.

## 2. Color palette — sampled from the supplied image

| Role | Hex | Use |
| --- | --- | --- |
| `--color-canvas` | `#11191C` | site canvas; leaf/stem charcoal |
| `--color-canvas-soft` | `#181F21` | stable dark controls |
| `--color-surface` | `#251B20` | panels and selects |
| `--color-surface-raised` | `#332126` | hover panels |
| `--color-blossom` | `#EE3C35` | primary accent and focus |
| `--color-blossom-light` | `#FF6655` | light accent text |
| `--color-burgundy` | `#89051D` | logo, brand surfaces |
| `--color-crimson` | `#AB1023` | primary actions |
| `--color-red-deep` | `#4E0414` | dark vignette |
| `--color-petal` | `#E6DDD8` | main text and reversed CTAs |
| `--color-petal-shadow` | `#D7B8AC` | metadata |
| `--color-on-muted` | `#B9A6A4` | descriptions |

Image-based sampling was performed using resized RGB clustering, then semantic colors were assigned manually. Use `/reference/flower-original.jpg` for original reference, `/public/blossom.jpg` for optimized runtime decoration.

## 3. Typography

- UI: `DM Sans`, fallback `system-ui`.
- Large headings and logo: `Manrope`, 700–800, tight tracking (`-0.065em` to `-0.08em`).
- Hero heading: responsive `clamp(54px,6.6vw,104px)` (mobile `clamp(42px,11vw,62px)`).
- Page headings: `clamp(46px,6vw,80px)`; section headings: `clamp(30px,3.1vw,47px)`.
- Body: 13–15px, line-height ~1.7–1.85; labels 9–11px bold and wide tracked.
- Original font files were not included in the user archive. These are **replacement fonts**, not recovered original font identity.

## 4. Layout

- Main content max-width: `1268px`, centered; page gutters: desktop 36px, tablet 20px, mobile 14px.
- Header: fixed `top:16px`, floating pill, 58px min-height; background gains blur/shadow after scrolling.
- Hero: viewport-like media stage, rounded 34px, gradient/vignette from left so headings stay readable.
- Main gallery: 6 cards per row on wide desktop, then 5/4/3/2 depending on width.
- Carousel: 7 visible 3:4 cards on wide screens; horizontal snap scrolling with arrow buttons.
- Catalog: 247px filter rail + flexible grid; inset burgundy chrome; 6 columns outer/variable columns inside.
- Producers: 4 columns wide, reducing to 2 on mobile.
- Mobile: nav becomes accessible expanding menu; filter rail becomes collapsible drawer.

### Breakpoints

`<380`, `≤640`, `≤900`, `≤1199`, `≥1200` px. Media queries are implemented in `src/styles/globals.css`.

## 5. Card anatomy

```
AnimeCard (3:4; position: relative)
├── poster (object-fit: cover; transition scale+opacity 500ms)
├── muted trailer iframe (mount after 300ms; only when embed URL exists)
├── top score ribbon (slides from -39px → 0px in 500ms)
├── black bottom gradient
├── caption: title + year/first genre
├── favorite button (additional feature)
└── hover details (to the right or left when near viewport edge)
    ├── title + score
    ├── truncated synopsis
    ├── HD and episodes chips
    └── Japanese title, air date, status, genres
```

The 3:4 ratio, delay, reveal, gradient, video iframe and details are **source-grounded** from `anime-card-Cr54_6bV.js`.

## 6. Motion

| Element | Animation | Dur./delay | Provenance |
| --- | --- | --- | --- |
| header scroll | padding, dark glass and shadow | 300ms | compiled main chunk |
| active nav styling | translucent rounded pill | state-driven | compiled main chunk |
| nav gliding background | translate & width | 430ms | **new enhancement**, not evidenced in original |
| card poster | fade 1→0.05 + scale 1→1.2 | 500ms | compiled AnimeCard |
| hover trailer | mount video, reveal | after 300ms | compiled AnimeCard |
| hover score badge | top -39px → 0 | 500ms | compiled AnimeCard |
| hover popover | right/left, 300+ms hover | 200–300ms approx | behavior adapted from Radix HoverCard |
| route transitions | fade + rise | 450ms | new enhancement |
| skeleton | linear gradient shimmer | 1550ms | new styling; original pulse skeleton documented |
| hero flower parallax | gentle scale hover | 1700ms | new palette-inspired enhancement |

Always respect `prefers-reduced-motion: reduce` by disabling nonessential motion.

## 7. Interaction rules

- Cards navigate to `/anime/{mal_id}`, not `#` anchors.
- Hover trailers are muted; never autoplay sound.
- Do not show empty trailer iframe when a video URL is missing.
- Search opens from the header or `Ctrl/Cmd+K`, supports arrow selection and Escape.
- The demo loads Jikan's public API when available and falls back to seed data offline. It never requires credentials.
- Only real, user-initiated controls should have interactive affordances.
- Use semantic landmarks, keyboard focus and accessible labels on icon-only buttons.

## 8. Component variants

- `AnimeCard`: standard, compact; states rest, hover, focused, trailer available, missing art.
- `HeroBanner`: image only or autoplay muted trailer; loading/empty fallbacks.
- `AnimeCarousel`: optional `path`, `number`, `kicker`; native horizontal scrolling.
- `FilterSidebar`: draft filter form with apply/reset; on mobile show as drawer.
- `SearchDialog`: initial, typed, results, no results, keyboard-active.
- `ProducerCard`: idle, hovered, locally-favorited.
- `AnimatedNavbar`: transparent, scrolled, active, mobile menu, search modal.

## 9. Anti-slop rules for future screens

1. Never swap the warm crimson/ink/petal system back to violet gradients.
2. Do not turn every section into the same rounded dashboard card; vary hero, gallery, and editorial strip.
3. Keep poster artwork dominant; visual hierarchy must read *image → title → metadata*.
4. One accent action per surface; avoid bright red for all text and borders.
5. All interaction states are required: hover/focus/active/empty/loading/error.
6. Use skeletons only while something can truly load; do not leave permanent mock placeholders.
7. No fake stats or fake anime details. Mark sample metadata as demo only.
8. Preserve 3:4 posters and the card hover behavior from the extracted chunk.

## 10. What was not recovered

- The uploaded original `index-Bsz0MBbc.css` is **0 bytes**. Precise original theme CSS is not present.
- `AnimeDetailsPage-DR09yhHX.js` and `ProducersPage-BypqTUXa.js` are referenced but missing from the archive. Both are freshly implemented.
- A compiled bundle cannot uniquely reveal original local variable names, TS interfaces, project file splits, formatting, or author comments. Recovered names are meaningful reconstructions.
- The original navbar's sliding active indicator was **not** visible in the source chunk; the gliding pill is a requested extra.
- Original custom fonts, images and videos are not bundled. Jikan supplies current poster/trailer URLs when reachable.

**Use `COMPONENTS.md` for API contracts, `SKILL.md` for agent instructions and `docs/RECOVERY_AUDIT.md` for file-by-file traceability.**


## MediaVault integration (2026-10-31)

The supplied artwork, Manrope/DM Sans, ink/petal/crimson defaults, card ratio,
300 ms hover delay, 500 ms poster motion, floating header and responsive rail/grid
remain the design source. `reference.css` here is the unmodified supplied CSS;
`src/blossom/reference.css` uses semantic variables in place of repeated exact
palette literals and self-hosts the fonts/artwork. Existing media functionality,
authentication, routing and data providers remain MediaVault's.

Appearance is a local preference in Profile → Оформление. Blossom is the exact
default; Burgundy and Petal use the supplied seeds #AB1023 and #D7B8AC. A custom
seed or background mode derives the whole palette: canvas, soft canvas, surface,
raised surface, text, muted text, accent and action colors. Sampling is 64 × 36;
canvas/surface/raised mix fractions are .08/.12/.15. Neutral images remain neutral.
Derived body contrast is ≥ 7:1 and muted/link/action contrast ≥ 4.5:1. Palette
transitions use the supplied 300 ms expressive motion; reduced motion disables it.
The exact supplied palette is preserved in manual Blossom mode.

Background priority: current title artwork/frame → selected wallpaper → supplied
Blossom artwork. Leaving a title releases its color. No private title pixels are
persisted for theming. Explicit wallpaper uploads stay in browser IndexedDB on
this device; max 20 MiB, longest side 2560px, WebP quality .9. They are never sent
to a server. Preferences use localStorage. No new cloud/account dependency.

Integration tokens: catalog sidebar 247px; mobile header breakpoint 1000px
(to retain MediaVault's server/music/profile controls), search width 550px and
100px top (80px on phones), navbar glide 430ms, page transition 450ms. Compact/list/
table collection modes remain operable. Player/reader chrome adopts the palette;
video pixels, manga paper, translation canvases and subtitle colors retain their
content-specific behavior. All new integration tokens are in design-tokens.json.

Decorative category-panel gradients also follow derived palette roles in custom/background themes; manual Blossom keeps the supplied reference gradient exactly.
