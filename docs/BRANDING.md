# PRUMO brand guidelines

The approved identity is concept 01, **Referência**: a vertical cord and geometric
plumb weight beside the PRUMO wordmark. The approved board is retained in
`branding/prumo-reference.png` for comparison, not interface display.

## Logo and assets

Use `PrumoBrand` for every interface logo. Its vector paths preserve the approved
lettering without depending on an installed font. The component loads its own
design tokens and brand styles. Do not retype, stretch, rotate, crop, or recreate
the mark with CSS. Keep the full symbol, cord, and wordmark together.

The standard height is 28px, or 24px below 600px. The login logo is 44px; shared
briefings use 24px. Width follows the original 1102:276 viewBox. The SVG has the
accessible name **PRUMO**, `role="img"`, and is not a separate keyboard stop.

Transparent exports and browser icons live in `frontend/public/brand/`:

- `prumo-logo.svg`: approved full-color dark-background logo.
- `prumo-logo-mono.svg`: single-color wordmark for light or print contexts.
- `prumo-symbol.svg`: standalone cord and weight.
- `prumo-favicon.svg`, `prumo-favicon.ico`: browser icons; ICO sizes are 16/32/48px.
- `prumo-apple-touch-icon.png`: 180px touch icon.

The favicon intentionally uses a shorter, heavier cord and a fixed #111e28
background for legibility. Do not substitute the reference board for these assets.
Both application HTML entrypoints declare the icons. Vite adjusts their paths
for the build base; the public replay must also work under a hosting subpath.

## Palette and themes

`frontend/src/design-tokens.css` is the source of truth. `brand.css` owns logo
geometry and presentation, not an independent palette.

| Role / token | Dark | Light |
| --- | --- | --- |
| Page / `--ds-surface-page` | #111e28 | #f5f3eb |
| Card / `--ds-surface-card` | #182732 | #fbfaf5 |
| Inset / `--ds-surface-inset` | #14252e | #e7ebe5 |
| Primary text / `--ds-text-primary` | #e1e8eb | #15201b |
| Secondary text / `--ds-text-secondary` | #a2b3bd | #53645b |
| Brand accent / `--ds-brand-accent` | #91c3d5 | Primary text |
| Link text / `--ds-text-link` | Primary text | #2e6d55 |

In the dark logo, the cord and lettering use primary text; the weight uses the
brand accent. Light logos are monochrome primary text. Printed logos are black.
The brand accent is independent of link styling: hyperlinks stay neutral in the
dark theme and green in the light theme. Preserve text-link underlines and
keyboard focus rings. A blue logo or focus ring is not a blue text hyperlink.

Use shared success, warning, and danger tokens for operational states. Green
indicates a positive result, amber uncertainty or a warning, and red an error or
infeasible result. A/B identifiers and map geometry keep their data colors;
they do not set the brand palette. Do not recolor fire, road, route, or confidence
layers as part of a branding change.

## Typography and interface structure

Use the shared Typography, Button/ButtonLink, Card, and SectionContainer
components. Their contract is documented in `frontend/src/components/ui/README.md`.

- Headings: the shared serif stack, weight 600. H1 is 36/48px, H2 28/36px,
  and H3 20/24px at the 768px breakpoint. Dense workspace headings may use H3
  presentation while retaining the correct semantic heading element.
- Body: the shared sans-serif stack, 16px; supporting text 14px.
- Eyebrows: the shared monospace stack, 12px, weight 700, uppercase.
- Controls: 2px corners and the existing 36/44/52px size variants.
- Cards: 3px corners. Pills are reserved for badges and data identifiers.
- Spacing: use the shared 4px scale and the existing compact workspace layouts.

Legacy stylesheets retain layouts and domain states below the shared component
layer. Theme-sensitive UI colors must reference tokens; do not introduce another
palette or override shared control colors with `!important`.

## Naming

The visible product name is always **PRUMO**, including accessible logo names,
page titles, exported branding, and the API service title. Page titles follow
`<page name> · PRUMO`; the loading title may be simply `PRUMO`. Brand asset
filenames use the lowercase `prumo-` prefix. Interface copy uses European
Portuguese; external names such as Fogos.pt, OpenStreetMap, MTT, and Cell2Fire
retain their own spelling.

Technical identifiers are compatibility contracts: `FIRELINE_*` variables,
`fireline_session`, navigation events/history keys, engine adapter entry points,
engine IDs and package names retain their existing values. Rebranding must not
require data migrations, renaming stored records, or re-seeding examples.

## Verification

The navigation browser checks cover the logo's accessible name, approved accent,
page naming, centering, and the absence of blue text links. The static tests in
`frontend/tests/navigation.test.ts` compare component/export geometry and verify
export colors, entrypoint metadata, and icon dimensions. Also inspect dark,
light, mobile, login, public replay, and printed briefing views after changes.
