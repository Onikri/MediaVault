# Vite reverse engineering: provenance & limitations

Source: user-provided `anime-card-Cr54_6bV.zip` containing 27 entries including Vite ESM chunks.

## What is in the original zip

- `anime-card-Cr54_6bV.js` (3,945 bytes): fully visible card implementation.
- `HomePage-Cm0C5Gru.js` (8,320 bytes): hero and multiple front-page sections.
- `CatalogPage-PyaQsbgD.js` (152,016 bytes): sidebar filters and page layout bundled together with third-party form/calendar dependencies.
- `carousel-image-DTZDTD7Q.js` (24,297 bytes): a reusable carousel built on Embla + section template.
- `MostPopularPage-vt3Xg_c5.js` (1,076 bytes): infinite query and responsive grid.
- `common-DmQO_PZF.js` (1,438 bytes): YouTube parser/embed settings and display helpers.
- `index-CnoOAIFE.js` (507,569 bytes): React runtime, router, Jikan API client, shared nav + search UI, helpers, app routes.
- `hover-card-RVrmSy4h.js`, `card-BxWvvcfe.js`, `badge-BlVA-HVZ.js`: primitive component implementations.
- `index-Bsz0MBbc.css` (**0 bytes**): no original bundled styles available in the archive.

## Source-grounded observations

`AnimeCard`: 3:4 aspect, poster object-cover, `group-hover:opacity-0 group-hover:scale-120 duration-500`, score ribbon `-top-8 → top-0 duration-500`, dark gradient `from-black via-black/20 to-transparent`, 300ms delayed trailer mounting, `iframe` with approx. 2.9x scale, Radix hover-card `openDelay=200`, side right offset 10, overlay fields (`JAPANESE`, `AIR DATE`, `STATUS`, `GENRE`) and click route `/anime/${mal_id}`.

`HomePage`: hero pulls current-airing TV via Jikan; if trailer exists it embeds autoplay muted loop and controls pause/mute; if not, falls back to cover; section ordering: hero → Trending → Season Now → Most Popular → Top Upcoming; 7-column desktop popular gallery (`xl:grid-cols-7`).

`Navigation`: original fixed `top-4`, center alignment `left-1/2 -translate-x-1/2`, max `w-7xl`, `transition-all duration-300` with scrolled background `bg-accent/65 backdrop-blur-sm shadow-lg`. Active navigation link is `bg-primary/30 px-4 py-1 rounded-full` without evidence of a gliding shared pill.

`CatalogPage`: main structure `max-w-7xl`, top offset, tinted rounded wrapper, filter controls; canonical possible filters: start/end dates, genres, rating, status, type, min/max score, order_by, sort; results per page 24. This project simplifies to a subset, explicitly documented.

`MostPopular`: `/top/anime?filter=bypopularity&limit=24`, infinite page fetch, loading skeleton, desktop 6 columns on this route.

## Reconstruction mapping

| Original symbol / file | Readable replacement | Degree of fidelity |
| --- | --- | --- |
| `R` / `anime-card-Cr54_6bV.js` | `src/components/AnimeCard.tsx` | High: behavior & anatomy; colors and visuals intentionally re-themed |
| `F` / `HomePage-Cm0C5Gru.js` | `src/components/HeroBanner.tsx` | Moderate: controls/hero; media/background altered to match floral palette |
| `Q` / `HomePage-Cm0C5Gru.js` | `src/pages/HomePage.tsx` + `AnimeGrid` | Moderate: content order, basic layout |
| `oe` / `carousel-image-DTZDTD7Q.js` | `src/components/AnimeCarousel.tsx` | Moderate: section behavior; native scrolling replaces Embla |
| `Rf` / `CatalogPage-PyaQsbgD.js` | `src/pages/CatalogPage.tsx` | Moderate: sidebar + grid; controls reduced from original |
| `L4` / `index-CnoOAIFE.js` | `src/components/AnimatedNavbar.tsx` | Moderate: scroll and route states; gliding indicator newly added |
| `j4` / `index-CnoOAIFE.js` | `src/components/SearchDialog.tsx` | Moderate: keyboard + overlay; local demo search instead of remote Jikan search |
| `I` / `MostPopularPage-vt3Xg_c5.js` | `src/pages/CollectionPage.tsx` | Approximate: offline page with finite sample grid |
| `common` YouTube helpers | `src/utils/trailer.ts` | High: equivalent general helper behavior |
| Missing `AnimeDetailsPage` chunk | `src/pages/AnimeDetailsPage.tsx` | NEW, **not decompiled** |
| Missing `ProducersPage` chunk | `src/pages/ProducersPage.tsx` | NEW, **not decompiled** |

## Deliberate enhancements versus source reconstruction

- The moving nav indicator with interpolated position and width is an **enhancement** requested in the conversation.
- Crimson/petal colors are derived from user-supplied flower photo, not from the original site's CSS.
- Favorite heart buttons and localStorage are new demo features.
- Responsive studio tiles and detail-page structure are newly built replacements.
- Offline fallback dataset is illustrative and includes approximate scores, so it must never be presented as live rankings.

## Original JavaScript included for cross-check

See `original-chunks/` for all 27 source archive entries **without editing**. Their minified identifiers and JSX runtime objects are not repackaged as the runnable implementation. The root Vite app uses readable typed `.tsx` files under `src/`.

## Why exact TSX recovery is impossible

Vite has already erased TypeScript annotations, split files into chunks, renamed local variables, stripped comments, and compiled JSX to `jsx/jsxs` calls. Multiple original TSX sources could produce the same compiled chunk. Recover the *observable behavior and component structure*, but do not promise exact local names, types, author formatting or proprietary missing files.

## Validation record

Code structure, syntax and import consistency are checked during artifact creation. Installing dependencies was blocked here by DNS resolution of `registry.npmjs.org` (`EAI_AGAIN`). Therefore a full Vite build **has not been verified in this environment**. The app is configured for a regular `npm install && npm run dev` on an internet-connected machine.
