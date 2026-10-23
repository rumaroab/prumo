# UI alignment and link audit

23 October 2026. Follow-up to `UI_UX_AUDIT.md`; the fixes below are implemented.

## Findings and fixes

| Finding | Affected interface | Fix |
| --- | --- | --- |
| Wrapped labels offset adjacent controls by up to 21px | Decision inputs, simulation setup, population forms and shared two/three-column field groups | Labels stretch to their row height; inputs share a baseline without fixing label heights. |
| Slider values sit below their controls | Wind speed and road exposure controls | Values sit beside the label; slider controls use the same 44px row height as numeric inputs. |
| The add action stretches beside a labelled field; stacked mobile fields need consistent separation | Population data editor | Align the button with the bottom of the adjacent input and retain a grid with 12px row gaps on mobile. |
| Different title/description lengths move card footers | Occurrence list | Flexible space precedes metadata so metrics, timestamps and delete actions line up within each card row. |
| The occurrence count breaks into two lines | Search toolbar | Preserve the count's intrinsic width and keep its text on one line. |
| A title-only dialog heading sits above its close button's center | Shared dialogs and drawers | Center the heading block and close button; keep a consistent gap when an eyebrow is present. |
| Blue links remain in several independent styles | Breadcrumbs, downloads, result/source links, map attribution and map popups; supervised app and public replay | Use the shared theme link color. Dark links use primary text; the light theme retains green. Map links use the same rule. Underlines, keyboard focus and anchor behavior remain available. |
| Action buttons overlap zoom controls on mobile and the road legend beside the sidebar | Mobility map | Stack the advisory, map, actions and legend in normal document order below the 1100px workspace breakpoint. Keep the map at least 360px high. |
| The minute label breaks mid-word and overlay fields have inconsistent widths | Modeled-fire advisory | Use stacked labels and flexible field widths, sharing control baselines where fields fit beside each other. |
| The close button stretches across the panel | Journey planner | Give panel close controls an explicit 44px square size at the top right. |

## Verification

- **32 browser checks pass at each size:** 1440×900, 1024×768, 720×450 (reflow), and 390×844. Checks use production components with in-memory responses and reject unexpected API requests. Coverage includes simulation setup/history/result/viewer, mobility map/movements/inventory/updates, decision perspectives/data, overview, archive and standalone briefing.
- Added regression checks for blue links, misaligned adjacent fields, missing spacing between stacked fields, and map actions overlapping zoom controls or information panels.
- Additional visual checks cover the setup wizard, area coverage, Fogos search/preview, scenario manager, inventory dimensions, coordinate dialog, sign-in, light-theme data editor and journey planner. Dialogs were checked at desktop and mobile widths.
- The mobility map was also measured at 1200px with its sidebar visible. Map actions clear the legend and zoom controls; the planner close button measures 44×44px at the top right.
- The public replay has no horizontal overflow or blue link text at 1440px and 390px. Its map attribution uses the shared link color. Light-theme download links retain green.
- The original 21px paired-input offset is now zero. Occurrence cards in the same row have matching metadata and action baselines despite different text lengths.
- Application/public production builds, application/fixture type checks, Portuguese interface checks, and all four static route tests pass. Both local production UI bundles are updated; packaged demo data is retained. The existing application bundle-size warning remains.

Evidence: [aligned decision controls](../tmp/ui-audit/aligned-controls.jpg), [mobile map actions and planner](../tmp/ui-audit/planner-mobile.jpg).

## Limits

The audit checks layout and link styling. Backend submissions, dispatch actions and destructive actions are outside this pass. Browser verification uses the app's Chromium preview; other browser engines are not covered.
