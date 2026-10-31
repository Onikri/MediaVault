# AniView Blossom — COMPONENTS.md

All React components are included as editable TypeScript/TSX files in `src/components`. This document maps each component to its props, source evidence and key states.

| Component | File | Main props | Description | Provenance |
| --- | --- | --- | --- | --- |
| `AnimeCard` | `src/components/AnimeCard.tsx` | `anime:Anime; compact?:boolean; index?:number` | 3:4 poster, animated score ribbon, muted trailer hover, details hover card, favorites | **Recovered** from `anime-card-Cr54_6bV.js`; favorites added |
| `AnimatedNavbar` | `src/components/AnimatedNavbar.tsx` | none | Fixed floating nav, scroll glass, active route, mobile menu, search | **Reconstructed** from main chunk; glide added |
| `SearchDialog` | `src/components/SearchDialog.tsx` | `onClose:()=>void` | Keyboard-accessible modal with local anime search | Reconstructed from main chunk (`j4`) |
| `HeroBanner` | `src/components/HeroBanner.tsx` | `anime:Anime` | Media backdrop, vignette, trailer control, title/synopsis, CTA | **Recovered behavior** from HomePage chunk; flower theme added |
| `AnimeCarousel` | `src/components/AnimeCarousel.tsx` | `title:string; kicker?:string;items:Anime[];path?:string;number?:string` | Section header, rail, prev/next, optional view-more link | From `carousel-image-DTZDTD7Q.js` with native scroll instead of Embla |
| `AnimeHoverPreview` | `src/components/AnimeHoverPreview.tsx` | `anime:Anime; anchor:DOMRect|null;open:boolean` | Portaled metadata panel, avoids scroll rail clipping | Adapted from original Radix HoverCard portal |
| `AnimeGrid` | `src/components/AnimeGrid.tsx` | `anime:Anime[];emptyText?:string` | Responsive poster gallery, empty state | Rebuilt composition |
| `FilterSidebar` | `src/components/FilterSidebar.tsx` | `filters:AnimeFilters;onApply:(f)=>void` | Search, date, genre, status, type, score, sorting, apply/reset | Reconstructed subset of CatalogPage |
| `ProducerCard` | `src/components/ProducerCard.tsx` | `studio:Studio;index?:number` | Editorial studio surface with heart and decorative orbit | **New implementation**, original studio chunk missing |
| `Button`, `Badge`, `Card`, `PageHeader`, `EmptyState`, `ErrorState`, `Pagination`, `SelectField` | `src/components/UIPrimitives.tsx` | See TypeScript exports | Source-inspired reusable UI primitives | Reconstructed APIs |
| `SkeletonCard`, `SkeletonGrid` | `src/components/SkeletonCard.tsx` | `count?:number` | Loading skeletons for future async usage | Rebuilt from original placeholder behavior |

## Data types

Defined in `src/types/anime.ts`. `Anime` is a typed subset of Jikan's response: `mal_id`, `title`, `genres`, `images.webp`, `trailer.embed_url`, `score`, `episodes`, `year`, `status`, `aired`, `studios`, etc. Real Jikan responses can omit optional fields; components guard accordingly.

`AnimeFilters`: `q`, `startDate`, `endDate`, `genre`, `rating`, `status`, `type`, `minScore`, `maxScore`, `order`, `sort`.

`Studio`: `id`, `name`, `subtitle`, `works` (demo metadata).

## Usage

```tsx
import { AnimeCard } from './components/AnimeCard';
import { AnimeCarousel } from './components/AnimeCarousel';
import { AnimeGrid } from './components/AnimeGrid';
import { fallbackAnime } from './data/fallbackAnime';

export function Example() {
  return <>
    <AnimeCarousel title="Most Popular" items={fallbackAnime.slice(0, 10)} path="/most-popular" />
    <AnimeGrid anime={fallbackAnime.slice(0, 12)} />
    <AnimeCard anime={fallbackAnime[0]} />
  </>;
}
```

The example must be rendered under `BrowserRouter` and `FavoritesProvider` because cards use navigation and favorites. All layouts require `src/styles/globals.css`.

### `AnimeCard` anatomy and behavior

- `anime-card`: card 3:4; poster and gradient shade; clipped title, year and genre.
- `anime-cover`: transitions opacity and `scale(1.2)` on hover over 500ms.
- `anime-card-video`: optional YouTube iframe from URL derived by `src/utils/trailer.ts` (300ms delay).
- `card-score`: rating ribbon animates down from outside the card on hover.
- `anime-preview`: metadata overlay appears at left or right depending on viewport space.
- `heart-action`: independent favorite toggle; does not navigate.

The source bundle does **not** include any missing image binary: the example gracefully uses CSS artwork when no poster is supplied. Some browsers or content blockers may prohibit embedded YouTube videos; cards continue working without them.

### `AnimatedNavbar` original versus enhancement

Original main chunk shows: fixed `top-4`, `transition-all duration-300`, translucent scrolled surface, fixed rounded active nav class and mobile sheet. A **sliding active indicator**, added for this redesign, uses `offsetLeft` and `ResizeObserver`, with 430ms transitions; treat it as a design enhancement rather than recovered source.

### `SearchDialog` keys

`Ctrl/Cmd+K` toggles, `Escape` closes, `ArrowUp/ArrowDown` changes highlighted hit, `Enter` opens selected item. Search operates over demo titles; Jikan search could be wired via `src/api/jikan.ts`.

### `FilterSidebar` notes

Start/end date filters are applied at **year granularity** for offline seed records (these records do not include full release dates). Genre, rating, status, type, minimum and maximum score, title, order key and sort direction are functional. The original `CatalogPage` bundle uses more granular date/score filtering and form libraries; this rewrite keeps a self-contained typed form without React Hook Form/Zod.

## Page composition

| Route | Page file | Status |
| --- | --- | --- |
| `/` | `pages/HomePage.tsx` | Recovered layout regions; imagery/layout restyled |
| `/catalog` | `pages/CatalogPage.tsx` | Recovered sidebar + grid concept; simpler filtering |
| `/anime/:id` | `pages/AnimeDetailsPage.tsx` | New replacement: original chunk missing |
| `/producers` | `pages/ProducersPage.tsx` | New replacement: original chunk missing |
| `/components` | `pages/ComponentsShowcasePage.tsx` | New documentation/playground route |
| `/most-popular` | `pages/CollectionPage.tsx` | From original MostPopular layout idea |
| `/trending`, `/season-now`, `/top-upcoming` | `pages/CollectionPage.tsx` | New variations from original route structure |

## Supporting modules

- `src/api/jikan.ts`: 6.5s timeout, live endpoint `/top/anime`, detail fetch, offline fallback.
- `src/hooks/useAnimeFeed.ts`: data state with deterministic cached sample fallback.
- `src/context/FavoritesContext.tsx`: localStorage favorite IDs.
- `src/utils/trailer.ts`: readable rewrite of supplied `common-DmQO_PZF.js` YouTube embed helpers.
- `src/utils/display.ts`: titles, ratings, cover URLs, descriptions.
- `src/styles/globals.css`: all design tokens, responsive layout and motion.

## Practical integration checklist

- Include global CSS or extract desired CSS selectors into your design system.
- Install React, React Router and lucide-react (`package.json`).
- Wrap components that require navigation in `BrowserRouter`.
- Wrap components with favorites behavior in `FavoritesProvider`.
- Feed a Jikan-compatible `Anime` object or map your own API to `Anime`.
- Configure CORS/content policy for external images and YouTube embeds if hosting behind strict CSP.
- Avoid marketing a newly authored replacement as byte-identical decompiled source.


## MediaVault adapter APIs

These TSX adapters live under `src/blossom/components/`. They keep the supplied
component anatomy; callbacks replace the demo router and seeded catalog.

| Component | Production inputs / responsibilities |
| --- | --- |
| AnimatedNavbar | links, active, onNavigate, onSearch, brand, children; existing hash navigation and account/server/music controls; Ctrl/Cmd K; collapsed menu |
| SearchDialog | service, onChoose, onBrowse, onClose; existing useCatalog/useSourceTitles; IME-safe keyboard selection; Radix focus trap and dismissal; no sample records |
| AnimeCard | anime, artwork, onOpen/href, onFavorite/favorite, detail/extra; same card for encrypted private items and live search; real scores only |
| AnimeGrid | children, className, id; catalog, collection and entity pages; retains grid/compact/list modes |
| AnimeCarousel | children, title, kicker, onMore; actual recently opened/new library items; snap rail and arrows |
| HeroBanner | title, description, artwork, onOpen; supplied flower by default, optional local wallpaper |
| ProducerCard | name, subtitle, index, onOpen, children; supplied studio anatomy adapted to five existing media sections |
| FilterSidebar | open, onReset, children; existing controlled catalog filters and providers |
| SkeletonGrid | count; async catalog loading, no fabricated counts |
| ThemeProvider / AppearanceSettings | shared semantic palette and local wallpaper/preferences, integrated into the existing profile |

Data adapters do not add Jikan demo data, replace the vault, change online API
sessions or start downloads. Existing title details, watch controls, music,
reader, server import, privacy and account actions retain their implementations.
Keyboard focus, reduced-motion, disabled/error/loading/empty states and
360/768/1280px layouts are verified with browser contract tests.
