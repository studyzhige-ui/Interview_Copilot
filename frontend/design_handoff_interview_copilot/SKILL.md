---
name: interview-copilot-design
description: Use this skill to generate well-branded interfaces and assets for Interview Copilot, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.

Key files:
- `colors_and_type.css` — full token set (colors, type scale, radii, shadows, motion)
- `fonts/` — Inter family (variable + static weights)
- `assets/` — logos (IC + IR monograms, wordmark)
- `preview/` — design-system tab card specimens
- `ui_kits/interview_copilot/` — interactive click-through prototype with all 6 product screens (Auth, Review, Mock, Library, Models, Me) and reusable `ui.jsx` components

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

Visual direction is 温暖、圆角、清晰、优雅 — warm clay-terracotta primary (`#C26A4A`), warm stone neutrals, generous radii (10/14/16/20 px), warm-tinted soft shadows, no gradients except the auth backdrop, lucide outline iconography only, no emoji in product UI.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.
