# PRUMO branding re-audit

23 October 2026. Reference: the approved **01 / Referência** board and the
[brand guidelines](BRANDING.md). This pass rechecked the current source and
rendered UI after the alignment audit.

## Findings resolved

| Finding | Correction |
| --- | --- |
| The UI logo's blue weight had become white after link colors changed | Added an independent `--ds-brand-accent` token and disconnected the logo from hyperlink styling. Dark logos again match the approved blue/white exports; links retain the requested neutral styling. |
| The logo component depended on its caller to load palette tokens | `PrumoBrand` now loads its token dependency directly, like the shared UI primitives. |
| Decision/public styles contained a second hardcoded UI palette | Moved UI colors to shared surface, text, border and status tokens. Kept the intentional A/B comparison colors and map data colors. |
| Light views inherited pale dark-theme metrics, labels and metadata, plus dark-only panels | Corrected effective colors in overview, simulation history/setup/viewer, mobility and decisions. Removed forced dark experiment-row colors. Shared alert and feedback colors now follow the theme as well. |
| Native controls did not consistently inherit the selected color scheme | Theme boundaries now set `color-scheme`, keeping browser-provided controls consistent with their surrounding UI. |
| Some decision labels, text sizes and corners bypassed the shared presentation | Migrated all four decision/public eyebrows to Typography and replaced independent decision/public text sizes and radii with existing tokens. Result headings wrap their actions before squeezing title words. |
| Unused CSS still described a text logo and imitation brand marks | Removed the five obsolete rules; the approved component and exported artwork remain the logo sources. |
| The branding guide coupled the logo accent to hyperlinks and omitted important usage rules | Updated the guide with palette roles, logo sizes/themes, asset use, naming, typography, semantic-color boundaries and verification rules. |
| Tests did not protect the brand's visual contract | Added runtime logo color/name checks and a static check comparing component/export geometry, approved colors, title/icon declarations and icon dimensions. |

## Naming and asset structure

- The product name is **PRUMO** in interface logos, accessible names, document
  titles, public replay, README and API service title.
- Interface logos use `PrumoBrand`; exports use lowercase `prumo-` filenames.
  Full and monochrome logos share the component's exact paths, and the symbol
  shares its cord/weight paths. ICO and touch-icon dimensions are verified.
- Existing application/public copies of the six source brand assets matched.
  The production-media logo was also visually checked against the approved mark.
- `FIRELINE_*`, `fireline_session`, navigation/history keys, package names and
  engine IDs are compatibility identifiers explicitly retained by the guidelines.
  Saved scenario names/descriptions are user content, not replacement brand labels.

## Verification

- **128 browser checks pass:** 32 at 1440×900/dark, 1024×768/light,
  720×450/dark, and 390×844/light. The existing navigation/alignment suite now
  also checks the approved logo accent and accessible name throughout navigation.
- **Five static tests pass**, including the new artwork/icon consistency test.
  Application and fixture type checks, PT-PT language checks, and both production
  builds pass. The existing application bundle-size warning remains.
- Effective UI text colors were inspected across 12 light-theme destinations:
  overview, history, setup, simulation viewer, four mobility views, three decision
  perspectives and data. Remaining non-UI text colors are intentional A/B identifiers.
- Login logos measure 44px in both themes. The public mobile logo measures 24px.
  Dark accents resolve to #91c3d5; light logos resolve to #15201b.
- The print-style briefing preview uses black logo paths, footer text and warning
  border, with a transparent warning background. No background graphics are
  needed to read the warning.
- The rebuilt public replay was checked at desktop/mobile sizes under `/replay/`.
  Branding/icons resolve below that subpath, text links stay neutral, and there is
  no horizontal overflow. Its eyebrow uses the approved 12px monospace style.
- Both local production UI bundles were refreshed while retaining the demo data.

Evidence: [dark login](../tmp/brand-audit/login-dark.jpg),
[light decisions](../tmp/brand-audit/decisions-light.jpg),
[public mobile replay](../tmp/brand-audit/public-mobile.jpg),
[print-style briefing](../tmp/brand-audit/print-brief.jpg).

## Scope and limits

No business rules, calculations, API payloads, stored records or map geometry
were changed. Browser checks use Chromium and controlled fixtures; live dispatch
and destructive operations were not exercised. Existing presentation/advert
videos were inspected through their shared logo and source assets, not re-rendered.
