# Shared UI migration

Implemented 22 October 2026 across the supervised application, public replay,
shared briefing, dialogs, crew interface and retained planning components.

## Code

- [Design tokens](/Users/rabreu/Projects/personal/forest_fire/frontend/src/design-tokens.css) own spacing, typography, surfaces, borders, shadows, control states, theme colors and responsive gutters.
- [Shared UI exports](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ui/index.ts) expose Button, ButtonLink, Card, SectionContainer, Typography, Box and Dialog.
- [Component documentation](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ui/README.md) describes variants, semantic elements, compact layouts, forms, links and dialogs.

All 200 original native application buttons were migrated to Button. Application
div wrappers now use Box for structural layout or Card/SectionContainer for
surfaces and content sections. Native main, section, article, aside, form, details,
summary, fieldset and legend semantics are retained where appropriate. Leaflet
continues to own its map hosts and built-in controls.

Cards support semantic elements, compact 16px padding and the default 24/32px
padding. Content pages use the shared 64/96px section spacing and 16/32px gutters.
Map workspaces retain their grids and use compact panels. Crew actions retain
their larger touch height. Primary, secondary, outline, ghost, destructive and
selected states all use the same control rules.

The four existing stylesheets now sit in `@layer legacy`. Overlapping component
presentation and redundant declarations were removed; remaining layout spacing
uses the token scale. Compatibility variables live in the central token file.
The public entry point uses the same page baseline, eliminating its default body
margin. Source files were formatted without adding a project dependency.

## Preservation

A syntax-tree comparison against the source snapshot verified equivalent
non-rendering application logic in all 23 inspected application modules, and
preservation of:

- 578 existing event and callback props;
- 857 checked value/configuration props, including map styles and geometry inputs;
- 1,719 dynamic rendering expressions, excluding formatting-only whitespace.

Existing API calls, calculations, routes, state updates and submission payloads
are preserved. Native submit buttons explicitly retain `type="submit"`.
Navigation/download links remain anchors. The preparation wizard's selection
handler is now on an explicit keyboard-operable Button, and scenario opening is
on the card's heading action. Dialogs reuse their existing close callbacks.

Workflow changes identified in the prior audit—such as route-preview invalidation,
archive error handling and cancellation semantics—are separate from this visual
migration.

## Verification

- TypeScript and Portuguese interface checks pass.
- Both application and public production builds pass. The existing large-chunk
  warning remains for the main application bundle.
- Desktop 1440px and mobile 390px browser passes cover scenario management,
  simulation setup/detail/viewer, decisions and all perspectives, archive,
  mobility tabs, planner, inventory, login, preparation and public replay.
- The checked pages have no page-level horizontal overflow or missing control
  labels. Sampled visible text no longer includes the forecast contrast failure.
- Shared component checks cover both themes, all button variants/sizes/intents,
  disabled states, selection, hover/focus, native form behavior, semantic cards,
  dialog Tab/Escape/focus return, reduced motion and responsive token spacing.
- Populated movement/report/crew/briefing and Fogos import views are exercised
  with temporary response fixtures; no operational records are written.

Build outputs and browser fixtures are kept outside the source tree. Existing
public demo data and backend files are preserved.
