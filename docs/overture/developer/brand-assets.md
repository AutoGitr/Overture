---
sidebar_position: 4
title: Brand assets
description: The logo sources, the exported sets and how they are regenerated.
---

# Brand assets

Run `bun run generate:brand --sync-db` from `frontend/` to regenerate both
products and copy every OvertureDB export to the sibling checkout's
`.github/brand/`. Without `--sync-db`, only Overture's checkout is updated.

`frontend/scripts/generate-brand.ts` owns the palettes, exact mark geometry,
optical sizes and layout. The wordmarks and approved tagline are outlined SVGs
in `frontend/design/`; exported mark SVGs in that directory are generated. The
tagline is **Artwork, collections & themes**. Outlined text needs no fonts on
the browser or build machine.

## Exports

- `*-logo`: the full-size mark, tightly bounded at its natural aspect ratio.
- `*-logo-inline`, `*-logo-stacked`, `*-banner`: measured, centred layouts.
- `*-dark` / `*-light`: explicit palettes for the corresponding backgrounds,
  available as SVG and PNG. Unsuffixed SVGs adapt to the host colour scheme.
- `*-tab.svg`: an optically tuned mark with 1.25px strokes at 16px height;
  PNG versions use square 16, 32 and 48px canvases. Prism keeps its regular
  hexagon proportions, so square canvases have equal space on the left and
  right.
- `favicon.svg`: Overture's square tab SVG; PNG fallbacks cover 16 and 32px.
- PWA icons use the complete square canvas. Maskable icons keep the mark
  inside the 80%-diameter safe circle; Apple icons use an opaque background
  and 10% inset. These backgrounds fill the canvas, and the mark insets
  protect it from device cropping. Social cards keep intentional space around
  the logo.

Composite assets use the painted text bounds, preserve aspect ratios, and
centre the icon and text block vertically or horizontally as appropriate.
Spacing between parts is intentional; there is no additional transparent
border around the composite. Do not stretch Prism to fill a square.

The app caches only the brand assets it uses. Full export sets remain
available for repository headers and other uses without bloating the offline
cache. This site serves them from `frontend/public/brand/` too, so a
regeneration updates the docs as well.
