---
name: aniview-blossom-ui
version: 1.0.0
description: Build and extend an anime-discovery React/TypeScript interface using the user's flower-image crimson/ink/petal palette, recovered AniView card interactions, responsive galleries, and cinematic non-generic design.
license: MIT
---

# Skill: AniView Blossom Interface Design

## When to activate

Use this skill when the user asks to create, modify, polish or extend UI within this project, or asks for a new anime website screen that should visually match AniView Blossom. Work in React + TypeScript and reuse the local component library.

## Mandatory input files (read in order)

1. `DESIGN.md` — design language, color map, motion contract.
2. `COMPONENTS.md` — concrete component API and route map.
3. `docs/RECOVERY_AUDIT.md` — which parts are source-derived, inferred or new.
4. `src/styles/globals.css` — actual CSS custom properties and selectors.
5. Appropriate existing `.tsx` components before changing functionality.

## Source-of-truth priority

1. User's current requirements and selected reference image.
2. Existing working components and design tokens in this repo.
3. Source-supported behavior recovered from the Vite archive.
4. Design improvements, only when explicitly indicated or compatible.

Never invent original implementation details (internal hooks, original JSX names, missing CSS). The recovered `.tsx` is a maintainable **functional reconstruction**, not necessarily the author's exact TSX.

## Nonnegotiable aesthetic

- **Canvas:** ink `#11191C`.
- **Primary identity:** blossom red `#EE3C35`, burgundy `#89051D`, crimson `#AB1023`.
- **Text:** petal warm white `#E6DDD8`, muted warm gray `#B9A6A4`.
- Keep contrast strong; use red primarily on purposeful actions, highlighted states, tiny accents.
- Typography: bold tightly tracked display headings, small tracked editorial labels, restrained body.
- Cinematic 3:4 cover cards with bottom-up black shade, floating header, oversized hero.
- Use `public/blossom.jpg` sparingly as editorial art, not on every card.
- Never add purple SaaS gradients, generic glass cards across every section, fake KPIs, excessive shadows or random neon.

## Component-selection workflow

Before creating a new UI element, check `COMPONENTS.md`:

- Poster or hover preview → `AnimeCard`.
- Group of posters → `AnimeGrid`.
- Horizontal posters with arrows → `AnimeCarousel`.
- Large featured artwork/video → `HeroBanner`.
- Navigation and search → `AnimatedNavbar` + `SearchDialog`.
- Discovery controls → `FilterSidebar`.
- Studios → `ProducerCard`.
- Async placeholders → `SkeletonGrid`.

Never duplicate these with bespoke markup unless the user demands a materially different variant. Extend typed props and document new variants in `COMPONENTS.md`.

## Design and interaction recipe

1. Identify the screen's *single* dominant content type and priority action.
2. Structure with a visible hierarchy: one hero/heading, one main grid/rail, supporting metadata.
3. Apply existing spacing and radius tokens, not arbitrary hardcoded colors.
4. Preserve original `AnimeCard` interaction: hover 300ms → mount muted trailer; image scales and fades 500ms; score badge slides in; details popover. Provide keyboard/touch fallback.
5. Preserve navbar top offset and scrolled glass. Gliding nav highlight is an enhanced redesign, **not** an original recovered behavior.
6. Include empty/loading/error visual states, real URLs and semantic HTML.
7. Preserve title truncation, reasonable readable sizes and accessible focus.
8. Test at 360px, 768px, 1280px widths; make sure no horizontal page overflow.
9. Respect `prefers-reduced-motion`.
10. If the UI introduces a novel token, add it to both `design-tokens.json` and `DESIGN.md`.

## Animation rules

- Fast microinteractions ~180ms.
- Normal changes/scroll glass ~300ms.
- Card poster and score ~500ms.
- Avoid perpetual or gratuitous movement outside a loading state or intentional media.
- Autoplay trailers muted only; never play sound on hover.
- Motion must preserve clarity and remain optional under reduced-motion settings.

## Anti-slop quality gates

Reject the design until all conditions are true:

- [ ] Screen visibly belongs to the blossom red + ink aesthetic.
- [ ] Distinct editorial layout, not a generic SaaS template.
- [ ] Correct 3:4 anime posters, legible gradients, coherent spacing.
- [ ] Controls have hover/focus/disabled/selected/empty states as applicable.
- [ ] Mobile navigation and filters are operable.
- [ ] Content has actual meaning, no fake social proof or fabricated stats.
- [ ] Jikan failures don't blank the entire UI.
- [ ] Animation is deliberate and not distracting.
- [ ] Existing reusable components are reused.
- [ ] Changes are reflected in appropriate docs.

## Implementation request template

> Implement [feature/page] using this project's AniView Blossom design tokens and existing React TypeScript components. Read `DESIGN.md`, `COMPONENTS.md`, `SKILL.md` and `docs/RECOVERY_AUDIT.md`. Keep ink `#11191C`, blossom `#EE3C35`, burgundy `#89051D` and petal `#E6DDD8`; preserve the 3:4 poster hover/video mechanics and the responsive floating navbar. Provide polished keyboard and mobile states. Do not use generic purple AI-slop patterns. Distinguish reconstructed code from source-verified behavior.

## Output requirements

Return complete `.tsx` component files, any associated CSS/token changes, and brief integration notes. If you cannot validate production build, state that explicitly. Never claim exact recovery of missing chunks.
