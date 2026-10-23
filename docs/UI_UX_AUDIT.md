# Platform UI/UX audit and proposed refactor

Audited 22 October 2026. **Plan only: no section, component, stylesheet, or application behavior was changed during this audit.**

Implemented alignment and link fixes are recorded in the [23 October follow-up](UI_ALIGNMENT_AUDIT.md).

## Scope and evidence

The audit covers every route in `RoutedApp`, the separate public demo, dialogs and drawers, shared map/result controls, and retained planning screens. Source inspection was supplemented by desktop (1440px) and mobile (390px) browser checks against an isolated, read-only copy of the platform data. External map tiles were blocked. No creation, deletion, dispatch, report submission, or other write action was exercised.

**Browser + source** below means the view was opened and its implementation inspected. **Source** means the conditional view was inspected in code; it was not available with the saved data. Login and the empty crew view were opened using simulated session responses. Populated crew/movement/brief views and live Fogos integration results require later validation with suitable fixtures. Retained screens are explicitly identified; this plan does not reactivate them.

The frontend uses plain CSS, not Tailwind. No native HTML JSX element in the inspected source has an inline `style` prop. The apparent inline styles belong to Leaflet geometry and markers. The replacement targets are legacy CSS classes and wrappers; map geometry styles must retain their operational meaning.

The new primitives currently have no consumers in the existing sections. This explains why the token system has not yet unified the visible platform.

### Route coverage

| Route / entry | Current screen | Audit entries |
| --- | --- | --- |
| Session gate | Login and authentication loading | 01–02 |
| `/scenarios`, `/` fallback | Scenario list | 03–05 |
| `/scenarios/:id` | Overview, preparation wizard, external context | 06–08 |
| `/scenarios/:id/experiments/new` | Simulation setup | 09 |
| `/scenarios/:id/experiments/:run` | Simulation detail | 10 |
| `/scenarios/:id/decisions` | Compare, Simulation, Data; water, access, population perspectives | 11–19 |
| `/scenarios/:id/simulation` | Advanced simulation viewer | 20–22 |
| `/scenarios/:id/mobility` and its subpaths | Map, movements, updates, sources; crew view by session role | 23–31 |
| `/brief/:token` | Shared/print briefing | 32 |
| `public-demo.html` | Public replay, both exercises and all perspectives | 33 |
| `/scenarios/:id/{map,missions,plans,resources,updates,response-experiments,rehearsals}` and nested archive links | Read-only planning archive | 34 |
| `/scenarios/:id/{water-planning,decision-support}` | Read-only planning archive | 34 |
| Retained components without an active entry point | Exercise workspace, Operations page, old manager/area settings and point helpers | 35–41 |

Routing source: [App.tsx](/Users/rabreu/Projects/personal/forest_fire/frontend/src/App.tsx:588) and [management route parser](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ManagementApp.tsx:314).

## Highest-priority findings

| Priority | Finding | Evidence and consequence |
| --- | --- | --- |
| P1 | Mobile decision page overflows | Loaded decision workspace is **434px wide at a 390px viewport**. Header metadata is visibly clipped; fixed/intrinsic widths need correction. Public replay also reaches 393px at 390px. |
| P1 | Incomplete modal behavior | New-scenario modal and preparation wizard remain open on Escape. Their wrappers lack dialog semantics and focus containment. Fogos import declares a dialog but does not implement its keyboard/focus lifecycle. |
| P1 | Missing accessible names | Scenario search, movement-board organisation filter, and wizard ignition name lack labels. Planner/inventory close controls expose only “×”. |
| P1 | Insufficient forecast text contrast | Selected `+30` forecast control: `#fff0cf` on `#b77b35`, approximately **3.16:1**, at 9px. Normal text needs 4.5:1. [WCAG contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html). |
| P1 | Pointer-only essential actions | Wizard ignition selection uses a clickable div; movement destinations and some road/ignition placement operations depend on map clicks. Provide equivalent keyboard-operable location/road selection. |
| P1 | Misleading movement preview state | Departure and map destination changes do not clear the previously calculated route in `MovementPlanner`. Require a new preview and renewed acknowledgements before assignment. This is a UI finding, not a claim that the server accepts an outdated signature. |
| P1 | Hidden error states | Archive request failures become empty arrays and can display “No saved records”. In the crew view without an assigned movement, geolocation errors are stored but never rendered. |
| P2 | Competing visual systems | Four legacy stylesheets override typography, spacing, backgrounds and borders. Management cards can be square; decision cards use 11px radii; the agreed card token is 3px. |
| P2 | Selection and action feedback | Several tabs/choice buttons only expose `.active`/`.chosen` visually. Many mutations lack a pending state or accessible completion/error feedback. |

P1 should be resolved in the first migration pass. P2 is the visual and interaction consolidation. Retained, unreachable interfaces are P3 unless reused by an active screen.

## Foundation rules for the migration

Use the existing [token contract](/Users/rabreu/Projects/personal/forest_fire/frontend/src/design-tokens.css:1) and [component API](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ui/README.md:1):

- **Content pages:** keep the `main` landmark and put one `SectionContainer` inside it. It supplies 64/96px section spacing, a 1280px maximum width, and 16/32px gutters. Do not repeat that spacing around every card.
- **Cards:** standard 24/32px padding, 3px corners, subtle border, `shadow="card"`; use `shadow="none"` for grouped information and `raised` for floating panels. Preserve `article`, `section`, `aside`, `details`, `summary`, `fieldset` and `legend` semantics. The current Card renders a div; put it inside the semantic element, or add a typed semantic-element option before replacing that element.
- **Map workspaces:** retain their full-width grid and map sizing. Use token spacing on structural panels and Card for genuinely separate surfaces. Do not insert a 64/96px SectionContainer into a map, narrow sidebar, timeline, drawer, or modal. If compact cards are needed, define one documented density variant centrally before using it; do not invent per-page padding overrides.
- **Actions:** primary for the main commit/calculate action, secondary for supporting operations, outline for alternate/cancel actions, ghost for close/back/reveal controls. Default to `md` (44px minimum); use `sm` (36px) only where compact controls remain usable. Preserve the crew view's larger touch action through a central documented rule.
- **Deletion:** the four current Button variants do not encode danger. Add semantic destructive intent to the shared foundation before migrating `.danger`/`.quiet-danger`; retain confirmations and pending locks. Do not make destructive actions look like ordinary secondary actions.
- **Navigation:** retain real anchors, including downloads and external sources. Add a shared anchor styling helper or typed ButtonLink using the same tokens. Do not turn every link into a native Button. Keep a single primary action per local task; selection is not a primary action.
- **Forms:** set `type="submit"` explicitly on migrated submit buttons because the new Button defaults to `type="button"`. Keep native labels, validation and fieldsets. Add common field/error/help styles to the same token configuration; Typography's `label` variant is not an HTML label.
- **Typography:** page title `h1`; section title `h2`; subsection `h3`; explanatory text `body`/`subtitle`; metadata `small`; eyebrow `label`. In dense panels use `Typography as="h2" variant="h3"` while preserving heading hierarchy. A brand label should not be the only page h1.
- **Interaction:** introduce a shared accessible Dialog lifecycle, and a deliberate selection pattern. Use tabs with keyboard navigation/associated panels for panel switching, or `aria-pressed` for independent toggle choices. Styling a Button alone does not provide either pattern.
- **CSS removal:** migrate each section with removal of its conflicting legacy presentation declarations. Retain necessary layout, responsive and domain-status rules. Avoid combining new buttons with `.run`, `.primary-action`, `.decision-primary`, or other old visual classes.

Dialog acceptance criteria follow the [WAI-ARIA modal pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/): named dialog, initial focus inside, contained Tab navigation, Escape dismissal when permitted, inert background, and focus returned to the opener.

## Section-by-section findings and exact replacement plan

### 01. Login and session gate — browser + source

Source: [App.tsx](/Users/rabreu/Projects/personal/forest_fire/frontend/src/App.tsx:604).

- **Visual:** `.login-page` and its form use separate page/card/button rules. Authentication loading is unstructured text.
- **UX/accessibility:** login errors use `.inline-error` without an alert or field association. Preserve the existing native username/password labels.
- **Replacement:** `main.login-page` keeps its landmark; its content becomes `SectionContainer > Card > form`. Heading/subtitle become Typography. The form's `.primary-action` becomes `Button variant="primary" type="submit"`, disabled while signing in. Announce errors and use the shared loading treatment.

### 02. Loading, errors, unavailable and empty states — browser + source

Sources: [loading.tsx](/Users/rabreu/Projects/personal/forest_fire/frontend/src/loading.tsx:16), [viewer startup states](/Users/rabreu/Projects/personal/forest_fire/frontend/src/App.tsx:358), [management states](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ManagementApp.tsx:307), [decision states](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionWorkspace.tsx:196).

- **Visual:** `.loading-screen`, `.startup-error`, `.empty-scenarios`, `.management-empty` and `.decision-setup` independently define spacing and headings.
- **UX/accessibility:** recovery actions and status announcements vary. The existing LoadingProvider already handles inert background and focus restoration; however, using the full overlay for lightweight map/time changes unnecessarily interrupts focus.
- **Replacement:** full-page state content becomes SectionContainer + Card + Typography; Retry uses secondary, Create uses primary, Back stays a link or ghost action as appropriate. Panel loading uses a local status and `aria-busy`. Preserve the existing provider for genuinely blocking transitions.

### 03. Scenario list and cards — browser + source

Source: [ScenarioList](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ManagementApp.tsx:149).

- **Visual:** management page spacing is 36px vertically on desktop rather than the section token; `.card-main` has 20px/22px padding, square framing and large custom title spacing. Page h1 reaches 62px rather than 48px.
- **UX/accessibility:** search has only a placeholder. `.card-main` is a button containing a heading, description and metrics; this gives the whole information card button semantics. Create/delete paths lack a pending lock.
- **Replacement:** contents of `main.management-shell` become one SectionContainer. `article.scenario-card` contains Card, a real heading link and separate metadata; remove `.card-main` as a whole-card button. New scenario → primary; delete entry → destructive ghost/outline after foundation support; confirm → destructive primary; Keep → outline. Label search and expose result count/status. Metrics become structured term/value groups with Typography.

### 04. Manual new-scenario modal — browser + source

Source: [ScenarioList modal](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ManagementApp.tsx:183).

- **Visual:** `.metadata-modal` uses its own 28px/18px padding instead of card padding, plus custom form actions.
- **UX/accessibility:** `.modal-backdrop > form` lacks dialog semantics and focus containment; Escape did not close it. Submission can be repeated while creation is pending.
- **Replacement:** use the shared Dialog shell with Card `shadow="raised"` around the existing form. Create → primary `type="submit"`; Cancel → outline. Add pending state, field-linked validation and focus return. No SectionContainer inside the modal.

### 05. Fogos import: availability, search, preview and pagination — source

Source: [FogosImportDialog](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/FogosImportDialog.tsx:77).

- **Visual:** `.fogos-import-modal`, `.incident-list article`, `.source-summary`, `.integration-unavailable` and `.import-tabs` use another collection of surfaces and button treatments.
- **UX/accessibility:** `role="dialog"`/`aria-modal` are present, but focus containment, initial/return focus and Escape handling are absent. Active/historical choice has only a CSS active state. Required fields sit outside a form, so native form validation is not being used. Coordinate inputs already provide a keyboard alternative to the map; retain them.
- **Replacement:** shared Dialog + raised Card; incident/preview groups → semantic articles with Card. Preview → secondary; Create → primary submit inside a form; Previous/Next → outline `sm`; Back/Close → ghost. Preserve existing source links and alert errors. Implement selection semantics, announce loading/results, validate coordinate ranges and retain list position when returning from preview.

### 06. Scenario overview, saved simulations and metric strips — browser + source

Source: [ScenarioOverview](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ManagementApp.tsx:188).

- **Visual:** `.management-panel` uses 24px/18px padding and square corners; details, experiments and metric strips follow separate spacing/type rules.
- **UX/accessibility:** saved status is visual text only. Simulation rows use navigation buttons. Small uppercase headings and oversized page titles weaken hierarchy.
- **Replacement:** one SectionContainer inside main; details and experiment semantic sections each receive Card and Typography. Compare decisions → primary; New simulation/Update prepared area → secondary. `.experiment-row` becomes a real result link within a list/card. Archive remains an anchor. Keep mobility `details/summary`; standardize its inner spacing. Announce autosave failure/completion without repeated chatter.

### 07. Preparation wizard and landscape controls — browser + source

Sources: [ScenarioWizard](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ScenarioWizard.tsx:123), [LandscapeSettings](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/LandscapeSettings.tsx:50).

- **Visual:** wizard, ignition rows, landscape fields and step actions define independent surfaces, gaps and `.run` buttons.
- **UX/accessibility:** Escape did not dismiss the wizard; its section is not a modal dialog. `.wizard-fire` is a clickable div containing an unlabeled ignition-name input. Position editing relies on the map. Progress lacks an accessible label.
- **Replacement:** Dialog + raised Card; steps and landscape groups keep their native form structure. `.wizard-fire` becomes a Card row with a labeled selection control, labeled name and coordinate inputs. Next/Prepare/Apply → primary; Add ignition → secondary; Back → outline; Close → ghost. Use an ordered step indicator, named progress, readable estimates and linked acknowledgement help. Retain native select labels and disabled data-source choices.

### 08. External incident context, weather and resource groups — source

Sources: [FogosContextPanel](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ManagementApp.tsx:227), [ResourceGroupEditor](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/OperationsPage.tsx:423).

- **Visual:** `.source-summary`, `.source-changes`, weather/resource groups and nested editor cards have independent padding and status styling.
- **UX/accessibility:** weather creation reports through `window.alert`; sync/save completion is not consistently announced. Long source metadata competes with operational fields.
- **Replacement:** keep the overview's outer SectionContainer; context groups → Card with Typography metadata. Synchronize/Create weather series/Apply editable values → primary for the active task; Refresh/secondary operations → secondary; source references stay links. Replace browser alert with inline status. Keep provenance, timestamps and the distinction between reported totals and confirmed resources. Only `ResourceGroupEditor` is active here, not the surrounding Operations page.

### 09. New simulation setup and technical controls — browser + source

Sources: [ExperimentSetup](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ManagementApp.tsx:270), [Controls](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/Controls.tsx:30).

- **Visual:** full-map setup has an independent 360px sidebar, 12px shell spacing, tiny control headings and repeated custom `.place`/`.run` actions. It renders two h1 headings.
- **UX/accessibility:** the run control changes to Cancel while launching, but this setup passes a no-op cancellation callback. Ignition placement needs a keyboard alternative. Engine/weather controls already use labels and native disclosures.
- **Replacement:** preserve `.experiment-setup-page` map grid. Use token gaps for the grid, Card for metadata, Typography for a single page title and nested control headings. Run → primary; Add/Move ignition → secondary; Remove draft ignition → ghost; Back → ghost/link. While launch is not cancellable, show disabled “Starting…” rather than an ineffective Cancel action. Add coordinate editing. Retain `details`, legends, uploads and engine availability explanations.

### 10. Simulation detail, progress, metadata and results — browser + source

Source: [ExperimentDetail](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ManagementApp.tsx:287).

- **Visual:** progress, editable metadata, frozen inputs and result summaries use `.management-panel` with unrelated action spacing.
- **UX/accessibility:** progress needs an accessible name; Save/Cancel actions lack pending locks, and local errors lack alert semantics.
- **Replacement:** main contents → SectionContainer; each existing semantic panel → Card. Save metadata → primary; Cancel running simulation → destructive outline with pending feedback; View result stays a primary-styled link. Typography separates metadata from immutable inputs. Label progress and announce failures/completion.

### 11. Decision workspace shell, navigation and responsive layout — browser + source

Source: [DecisionWorkspace header](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionWorkspace.tsx:202).

- **Visual:** custom 8px rounded navigation, mixed amber/slate selection and inherited uppercase heading rules differ from the tokens. The brand is the only h1. Header metadata and intrinsic sizing contribute to the observed 434px mobile page width.
- **UX/accessibility:** main tabs, perspective choices and proposal choices only expose CSS active states. Repeated navigation has no skip-to-content link.
- **Replacement:** retain the full-width workspace/map shell; replace nav buttons with shared Button styles plus a proper tab pattern, and proposal choices with a labeled selection group. Add an actual workspace title with Typography, skip link and visible keyboard focus. Give flex/grid children `min-width:0`, allow metadata wrapping and measure actual header height rather than relying on stale viewport subtraction. Preserve routing links in “Other tools”.

### 12. Decision Data and Simulation tabs — browser + source

Source: [DecisionWorkspace setup panels](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionWorkspace.tsx:216).

- **Visual:** separate `.decision-setup` wrappers use 820px maximum width, 48px margins, 28px padding and 12px corners.
- **UX/accessibility:** prerequisites, imports, saved status and next actions are presented as a long sequence with weak grouping. Existing error alerts should be retained.
- **Replacement:** each tab panel gets one SectionContainer with Cards for operational imports, population data and simulation selection/setup. Replace `.decision-setup` presentation with these wrappers. Import/save/run actions → primary; refresh/supporting actions → secondary. CSV/template downloads stay anchors. Use headings, linked help and concise success/status feedback.

### 13. Population location and vehicle editor — browser + source

Source: [PopulationDataEditor](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/PopulationDataEditor.tsx:27).

- **Visual:** `.population-edit-row` has 12px padding, 9px corners and custom 7px action corners; h4 headings are visually detached from the surrounding hierarchy.
- **UX/accessibility:** repeated Remove actions need names identifying the row; save/dirty status and field help should be associated with the relevant group. Native input labels and error alerts are already present.
- **Replacement:** origin/reception groups → named sections with Card rows, token grid gaps and Typography headings. Add location → secondary; remove unsaved row → ghost with a specific accessible name; Save data → primary, disabled during save. Keep vehicle dimension fields and coordinate inputs in native labeled groups.

### 14. Water comparison inputs and saved comparisons — browser + source

Source: [DecisionWorkspace comparison panel](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionWorkspace.tsx:224).

- **Visual:** `.decision-input` uses 22px padding; `.decision-source` uses 10px corners and 7/13/12px padding; `.decision-primary` uses a separate amber palette and 9px corners.
- **UX/accessibility:** prerequisites and stale-result messages need explicit associations; saved comparison choices do not consistently expose selection state. Fieldsets and legends are useful and must remain.
- **Replacement:** apply token spacing to the structural sidebar; preserve source fieldsets and style them with shared field-group tokens. Compare alternatives → Button primary; saved comparison selection → secondary/ghost with selected semantics inside list/Card items. Vehicle facts → Card or a structured definition list. Use Typography for titles/help and an announced stale-result notice.

### 15. Access proposal and impact summary — browser + source

Sources: [access input](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionWorkspace.tsx:239), [ImpactSummary / AccessResults](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/AccessViews.tsx:20).

- **Visual:** `.selected-road`, `.access-impact-count` use 12px padding and 10px corners; `.access-impact` uses 11px padding/9px corners. Summary actions are roughly 31px high.
- **UX/accessibility:** choosing a road depends on vector-map clicking. Large summary bodies are buttons, obscuring the distinction between information and action.
- **Replacement:** selected-road/impact information → Card with semantic headings and explicit controls. Test closure → primary; Show road/Open water/Open population → secondary or ghost `md`. Add a searchable keyboard-operable road selector linked to the map. Keep counts, before/after states and proposal caveats in readable text, not only color.

### 16. Population perspective and reception choices — browser + source

Sources: [population input](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionWorkspace.tsx:254), [PopulationResults](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/AccessViews.tsx:63).

- **Visual:** `.population-row`, `.population-option` and `.population-detail` use another small-card spacing/radius system.
- **UX/accessibility:** chosen origin/reception is indicated by border color and `.chosen`, without a programmatic selected state.
- **Replacement:** result rows/detail → Cards with Typography; origin/reception controls → labeled radio-style selection or explicit pressed Buttons. Evaluate access → primary; Edit data → secondary; map focus → ghost/outline. Keep the meaning of supplied population counts and route feasibility text intact. Do not wrap an entire Card containing other controls in a Button.

### 17. Decision results, metrics and advisories — browser + source

Sources: [DecisionResults](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionResults.tsx:26), [DecisionAdvisories](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionAdvisories.tsx:30).

- **Visual:** `.decision-card` has 15px padding and 11px corners. Metrics/category text reaches 10.4px. Advisory actions have 5px/8px padding and are about 28px high. Custom action rules omit a shared hover/active/focus treatment.
- **UX/accessibility:** A/B/Show both selection lacks exposed pressed state; dense assumptions compete with results. Feasibility already has text labels, which should remain.
- **Replacement:** preserve `article`; replace its visual frame with Card. Result title → Typography plus a ghost selection Button, or a heading with a Button inside. Show both → secondary; advisory focus/time actions → outline/ghost at least `sm`, `md` for touch layouts. Add selected semantics; use structured metric pairs and `small`/body tokens. Advisories become a shared status surface using centralized severity colors, not full page sections. Static advisory lists should not all be assertive live alerts.

### 18. Decision timeline, events, provenance and map caption — browser + source

Sources: [decision timeline](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionWorkspace.tsx:266), [TimelineEvents](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/DecisionResults.tsx:80).

- **Visual:** timeline playback has 8px corners and custom 8px/12px padding; event/caption text is around 11–12px, below the agreed small-text scale.
- **UX/accessibility:** the range already has an accessible name. Crowded clock/slider labels need responsive wrapping and a readable current value. Map-only information needs equivalent event/result text.
- **Replacement:** playback → secondary `sm`/`md`; preserve native range and provenance `details/summary`. Use token padding, wrapping and Typography for events/assumptions. Keep the map container sized for Leaflet. Avoid announcing every animation tick; expose user-initiated value changes and selection feedback appropriately.

### 19. Shared map interactions and popups — browser + source

Sources: [MapView](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MapView.tsx:37), [AccessMapLayers](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/AccessViews.tsx:89), [map styles](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/mapStyles.ts:1).

- **Visual:** React popup actions and generated popup content do not share the new control typography or states.
- **UX/accessibility:** map click handlers for placing/selecting domain features need matching form/list actions. Keep Leaflet's existing keyboard controls and attribution.
- **Replacement:** React popup Move/Delete actions → secondary/destructive Button; generated HTML popups use the same scoped token classes or move into a React popup before adopting components. Add location inputs/road lists outside the map, selected-item announcements and clear map-region names. Do not replace GeoJSON `style` or marker `pathOptions` with SectionContainer; geometry colors/line widths are domain rendering, not layout styles.

### 20. Advanced simulation viewer shell, controls and overlays — browser + source

Source: [ViewerApp / AppHeader / ViewerControls](/Users/rabreu/Projects/personal/forest_fire/frontend/src/App.tsx:435).

- **Visual:** `.panel.controls`, `.control-section`, map notices and legends have independent spacing; some section headings render as 9px uppercase text. Result selection appears in both header and sidebar. Mobile header consumes considerable vertical space.
- **UX/accessibility:** active navigation links need `aria-current`; warnings and completion/status hierarchy vary. Tiny headings impair scanning even where contrast is adequate.
- **Replacement:** retain full-width viewer/map grid and use token panel spacing. Apply Typography to section headings, Card to separate notices and result summaries, and shared Buttons to comparison/retry actions. Keep navigation as links. Consolidate duplicate result selection, add a skip link and keep warnings accessible without covering controls.

### 21. Advanced simulation timeline and forecast — browser + source

Source: [Timeline](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/Timeline.tsx:18).

- **Visual:** forecast buttons are approximately 20px high with 9px text; the selected forecast has the measured 3.16:1 contrast failure.
- **UX/accessibility:** the slider is labeled and forecast buttons already have `aria-pressed` inside a fieldset/legend. Preserve these strengths while increasing usable control size and contrast.
- **Replacement:** play/pause → secondary; forecast choices → outline/secondary `sm` with centralized pressed styling and at least 4.5:1 text contrast. Use token label/current-time typography. Preserve native range behavior and named forecast group. Wrap controls on narrow screens instead of shrinking text.

### 22. External map layers and observation comparison — source, viewer shell checked

Sources: [FogosLayersPanel](/Users/rabreu/Projects/personal/forest_fire/frontend/src/App.tsx:484), [ObservationComparisonPanel](/Users/rabreu/Projects/personal/forest_fire/frontend/src/App.tsx:509).

- **Visual:** disclosures, risk summaries, comparison metrics and errors have individual surface and spacing rules.
- **UX/accessibility:** loading/error feedback is inconsistent and local error paragraphs lack announcements. Native checkboxes and disclosure summaries are already useful.
- **Replacement:** preserve `details/summary` and labeled fields; metric/source summaries → Card or definition lists with Typography. Compare snapshot → primary; Compare series/Load risk/Refresh → secondary as appropriate to the task. Keep busy locks, add error/status semantics and show timestamps and source availability without relying on color.

### 23. Mobility navigation, map, fire entry panel and demo status — browser + source

Source: [MobilityApp](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:126), [FireStart](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:310).

- **Visual:** `.mobility-panel` uses 25px padding and square corners; fire overlay, summary stats and demo banner have independent treatments. Header tabs use CSS-only active states.
- **UX/accessibility:** the connection indicator is hidden by the small-screen rule, concealing offline information. There is no consistent map-view page heading. Map selection needs the alternatives described in entry 19.
- **Replacement:** preserve map grid; FireStart and MapSummary visual panels → Card with Typography; overlay/status use token surfaces. New movement/Plan journey → primary; Units/Show latest/Updates/Sources → secondary or ghost; external page navigation stays links. Implement accessible tab semantics and keep connection/last-refresh status visible on mobile. Announce meaningful state changes, not every demo timer tick.

### 24. New movement planner — browser + source

Source: [MovementPlanner](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:175).

- **Visual:** `.mobility-panel`, `.primary-action.full`, fieldsets and route assessment cards use independent spacing and action rules.
- **UX/accessibility:** close is an unnamed ×; destination is map-only. Changing departure or picking another destination does not invalidate the existing route preview. Error text lacks alert semantics.
- **Replacement:** panel surface → Card; Preview/Assign → primary `md`; Close → ghost with an accessible name. Preserve numbered fieldsets. Add coordinate/location selection; clear route and acknowledgements whenever route inputs change, then require a new preview. Link route warnings to acknowledgement controls. On mobile, if the panel becomes a modal sheet, apply the shared Dialog lifecycle and return focus.

### 25. Road report and restriction panel — source

Source: [RoadReportPanel](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:205).

- **Visual:** side panel, restriction chips and report action spacing differ from other forms.
- **UX/accessibility:** close is an unnamed ×; save/restriction changes need a pending lock and announced outcome. Selecting the road requires a keyboard alternative.
- **Replacement:** `.mobility-panel` → Card; Record report → primary; End restriction → an explicitly labeled outline action with appropriate confirmation, not a generic danger color by accident; Close → ghost. Preserve read-only permissions and native labels. Add submission status, linked errors and a searchable road selector.

### 26. Movement detail, briefing actions and replanning — source

Source: [MovementDetail](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:216).

- **Visual:** details, warnings and action groups use the broad mobility-panel styling and inconsistent buttons.
- **UX/accessibility:** close is an unnamed ×. Status transitions and clipboard actions need clear busy/completion feedback; replanning already has some busy handling but other actions can be repeated.
- **Replacement:** panel → Card with Typography and definition-list facts. Next operational step → primary; Replan → secondary; Copy crew/brief link → outline; Close → ghost. Preserve version/review warnings, disable pending transitions and announce copy success/failure. Keep any direct briefing navigation as an anchor.

### 27. Movement board — browser + source; populated cards source-only

Source: [MovementBoard](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:226).

- **Visual:** board spacing uses 30px/18px/12px values; status columns and whole movement buttons have their own framing.
- **UX/accessibility:** organisation select has no label. Horizontal columns need a named, keyboard-operable scroll region; selected/detail state is not explicit on cards.
- **Replacement:** content page → SectionContainer; retain the board's internal column layout and intentional local horizontal scroll. Each movement article → Card with heading, metadata and an explicit secondary/ghost Open action. Use Typography for column headings and counts. Label filters and add meaningful filtered/empty states. Do not give every column a padded SectionContainer.

### 28. Mobility updates, road review and communications — browser + source; pending-review form source-only

Source: [Updates](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:233).

- **Visual:** `.updates-page`, `.updates-grid`, report articles and communication groups duplicate card styling.
- **UX/accessibility:** the road-match label wraps both a search input and a select; give each its own label. Review actions lack pending locks; errors are plain text.
- **Replacement:** page → SectionContainer; review and feed groups → semantic sections/articles containing Card. Confirm → primary; Dismiss → outline with an explicit action name; Open record → ghost/link according to destination. Add separate field labels, pending states and announced results. Preserve the visible distinction between simulated communications and recorded reports.

### 29. Sources, water report history, units and incident points — browser + source

Source: [SourcesUnits](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:245).

- **Visual:** repeated article wrappers have inconsistent padding. Manage units renders close to a browser-default button (roughly 24px high), unlike primary actions elsewhere.
- **UX/accessibility:** review actions lack pending feedback; local errors are not alerts. Verification age and reported status need a consistent hierarchy.
- **Replacement:** page → SectionContainer; water-source/unit/incident articles → Card; history keeps `details/summary`. Manage units → secondary `md`; Confirm report → primary; Dismiss → outline. Typography differentiates name, current status, source and timestamp. Announce outcomes and retain explicit unknown/unverified wording.

### 30. Inventory drawer: vehicles, units and radio check-in — browser + source

Source: [Inventory](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:273).

- **Visual:** drawer and its repeated sections use custom padding, borders and unstandardized actions.
- **UX/accessibility:** backdrop + aside lacks modal dialog behavior and the close × lacks a name. Mutations need pending states; availability action text can be mistaken for the current state.
- **Replacement:** shared Dialog/drawer shell + raised Card; vehicle/unit/check-in groups get Typography and consistent form spacing. Add/save/check-in → primary within each group; availability toggle → secondary with an action-oriented label; Close → ghost. Preserve labeled fields; add error/status handling and focus return. No SectionContainer inside the drawer.

### 31. Crew: no assignment, active briefing and reports — empty view browser + source; populated views source

Source: [CrewView / CrewWaterSources](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:285).

- **Visual:** `.crew-brief`, `.crew-report` and `.crew-empty` form a separate card system. The primary crew action already has a useful 60px minimum height.
- **UX/accessibility:** the empty branch does not display errors from Share location. Secondary movement actions and road/water report submissions do not consistently lock during submission. Retry feedback is not announced.
- **Replacement:** use token gutters for the compact crew shell, Card for briefing/report surfaces, Typography for title and facts. Main movement action → primary, preserving the larger touch height through a central rule; location/report → secondary; Cancel/Close → ghost/outline; send report → primary. Render errors in both branches, announce unsent/retry states, preserve request-id reuse and offline/version/review messages. Do not add desktop-sized section padding above the urgent mobile action.

### 32. Shared and printable briefing — source

Source: [SharedBrief](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/MobilityApp.tsx:306).

- **Visual:** `.print-brief` uses a separate 760px width, 40px/22px screen padding and 40px h1, plus dedicated print margins.
- **UX/accessibility:** fetch failure silently falls back to cached data without indicating that the brief is cached. Loading/error states have no consistent recovery treatment.
- **Replacement:** screen page → SectionContainer with semantic article/Card and Typography; Print → secondary. Add cached/offline status and last-successful-fetch information. Keep print-specific typography, page margins and hidden controls in print media rules; reset screen section/card padding and shadow when printing. Preserve route warnings and brief version.

### 33. Public demo: introduction, scenarios, all perspectives, map and footer — browser + source

Source: [public-demo.tsx](/Users/rabreu/Projects/personal/forest_fire/frontend/src/public-demo.tsx:76).

- **Visual:** `.public-intro` uses 1250px width and repeated 18/30/15px padding overrides; `.public-layout` uses 1500px width. A browser-default 8px white body margin remains. Public headings are sans while the main app's shared result headings inherit serif/uppercase styling. Public page slightly overflows at 390px.
- **UX/accessibility:** scenario/departure/proposal/perspective choices only expose CSS active state. Fixed map heights, sticky layout and result scrolling need narrow-screen/zoom checks. Loading errors offer no retry.
- **Replacement:** introduction/footer → SectionContainer + Typography; `.public-scenario-story` → Card; scenario/departure choices → accessible shared selection controls; playback/map-focus actions → secondary/ghost Button. Shared results/access/population migrate once through entries 15–18. Keep the map workspace full width where needed. Add a common entry-point page baseline for body margin/background and token font inheritance, fix intrinsic overflow, and provide retry/status feedback. Preserve public/fictitious-data notices, provenance disclosures and basemap checkbox.

### 34. Read-only archive, every category — browser + source

Source: [PlanningArchive](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/PlanningArchive.tsx:8).

- **Visual:** `.management-shell.archive-page`, `.management-panel` and `.archive-record pre` use old spacing and tiny headings; raw JSON dominates each opened record.
- **UX/accessibility:** failed category requests are converted into empty lists and displayed as “No saved records”. Users cannot distinguish unavailable from empty. Long raw records are hard to scan.
- **Replacement:** outer content → SectionContainer; each category → named section with Card, Typography and independent loading/error/empty state. Add secondary Retry where needed. Keep record `details/summary` and saved-result links; show readable key facts first and raw data in a secondary disclosure. Preserve read-only behavior.
- **All categories included:** saved situation, situation snapshots, missions, response plans, response experiments, rehearsals, fire results, saved planning closures, saved containment tasks, saved allocation plans, saved response teams and saved points. No category should silently disappear after a failed fetch.

## Retained interfaces and shared helpers

These are included to complete the inventory. They are not active planning routes. Apply the replacements below only if the component is reused/restored, or when migrating an active shared helper. Do not reactivate old workflows as part of visual cleanup.

### 35. Older scenario manager and area settings — source

Sources: [ScenarioManager](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ScenarioManager.tsx:13), [AreaSettings](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/AreaSettings.tsx:52), [retained opener/state](/Users/rabreu/Projects/personal/forest_fire/frontend/src/App.tsx:318).

- **Visual:** `.scenario-manager`, `.scenario-row`, `.delete-confirmation` and area wizard surfaces have custom padding/actions.
- **UX/accessibility:** ScenarioManager already uses native `dialog.showModal()`, a label, error/status announcements and guarded cancellation; retain these strengths. AreaSettings uses the weaker wizard backdrop pattern. The current viewer has no wired call site for `openManager` or an action setting `editingArea` true.
- **Replacement:** retain native dialog; use raised Card and Typography inside; Save name → primary `type="submit"`; Delete/confirm → destructive intent; Keep → outline; Close → ghost. AreaSettings → shared Dialog, Card and Prepare/Apply primary, Cancel outline. Do not add new navigation to expose them in this pass.

### 36. Exercise situation map and location selection — source, unmounted

Source: [ExerciseWorkspace map](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ExerciseWorkspace.tsx:102).

- **Visual:** `.exercise-sidebar`, `.exercise-panel`, preset controls and selected-location cards use another dense spacing/type system.
- **UX/accessibility:** map-driven placement and CSS-only preset state need keyboard alternatives and exposed selection. English copy differs from the surrounding Portuguese interface.
- **Replacement if reused:** keep the map grid; panel cards → Card, presets → secondary/ghost Buttons with selected state, Save location changes → primary. Use Typography and label all coordinate alternatives. Resolve interface copy consistently through the locale system.

### 37. Exercise missions — source, unmounted

Source: [MissionsPage](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ExerciseWorkspace.tsx:128).

- **Visual:** `.exercise-content`, `.exercise-panel` and mission rows use independent page spacing and repeated card/action treatments.
- **UX/accessibility:** long mission forms need explicit grouping and helper associations; preserve the existing labeled coordinate fields and pending guards.
- **Replacement if reused:** main content → SectionContainer; mission form and list articles → Card; Create/save → primary; edit/supporting actions → secondary; archive → explicit outline action. Use Typography and native fieldsets for mission-specific fields, with consistent validation and empty states.

### 38. Exercise plans, response experiments and rehearsals — source, unmounted

Source: [PlansPage](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ExerciseWorkspace.tsx:140).

- **Visual:** plan builder, candidate/assignment cards, comparison rows and playback controls share broad selectors despite different purposes.
- **UX/accessibility:** assignment remove × lacks a name; selection relies on custom visual treatment. Rehearsal state/time and destructive restart need clear hierarchy and feedback.
- **Replacement if reused:** one SectionContainer for the page; builder, saved plan, experiment comparison and rehearsal → separate semantic sections with Card. Add assignment → secondary; Save/Suggest/Run comparison → primary within each task; Rehearse/Play/Step → secondary; Restart → outline with explicit meaning; Remove → labeled ghost. Preserve native checkboxes, expose selection and announce major playback state changes without narrating every tick.

### 39. Exercise resources and updates — source, unmounted

Sources: [ResourcesPage](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ExerciseWorkspace.tsx:163), [UpdatesPage](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/ExerciseWorkspace.tsx:173).

- **Visual:** vehicle/unit/location forms and reported/simulated feeds use `.exercise-grid-three`, `.exercise-panel`, `.resource-row` and `.update-row` framing with custom page spacing.
- **UX/accessibility:** dense side-by-side forms need mobile stacking, clear validation and status hierarchy. Preserve their existing labels, busy conditions and explicit reported-versus-simulated distinction.
- **Replacement if reused:** SectionContainer outer content; each inventory/feed section → Card and Typography. Add vehicle/Add unit/Save locations → primary; supporting actions → secondary. Preserve layout grids with token gaps. Reuse the point editor migration below rather than adding another card style.

### 40. Operations: water, teams, routing, containment, rankings, closures — source, unmounted page

Sources: [OperationsPage](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/OperationsPage.tsx:304), [RouteResults](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/OperationsPage.tsx:442).

- **Visual:** water presets/source inventory, stations, routing, team allocation, containment drawing, rankings, advanced comparisons, closure editor and layer controls use numerous `.run`/`.place` actions and custom nested panels.
- **UX/accessibility:** dense operational tasks lack a consistent action hierarchy; map drawing/closure selection needs keyboard-operable alternatives. Tiny metric/label treatments impede scanning. Preserve source uncertainty and feasibility wording.
- **Replacement if reused:** retain operational map layout; each named tool section → Card/token panel spacing with Typography. Calculate route/allocate/run comparison/save restriction → primary for the current task; Add station/team/line, preview and draw controls → secondary; clear/cancel → outline; deletion → destructive intent. RouteResults/Stat → structured metrics inside Card. Keep fieldsets, native disclosures and domain map styling. Migrate active `ResourceGroupEditor` now via entry 08 without rewriting the dormant parent page.

### 41. Point editor and water presets — source, retained helpers

Sources: [PointsEditor](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/PointsEditor.tsx:19), [WaterPresets](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/WaterPresets.tsx:12).

- **Visual:** `.point-card`, `.water-presets`, `.point-actions` and `.place` buttons use their own compact border/padding/text treatments.
- **UX/accessibility:** Place/Move relies on a map click. Existing labels, point-type accessible name and native details summaries should remain; provenance and unknown availability must stay visible.
- **Replacement if reused:** retain point `details/summary`, apply shared surface tokens or Card to its content; water presets → Card with Typography. Add preset/Add all → secondary; Place/Move/Show all → secondary; Delete → destructive intent. Provide labeled coordinate editing and consistent imported/status feedback. Keep source links as anchors.

## CSS cleanup map

| File | Remove or replace during the corresponding migration | Keep or centralize deliberately |
| --- | --- | --- |
| [styles.css](/Users/rabreu/Projects/personal/forest_fire/frontend/src/styles.css:1) | Repeated palette roots and visual overrides; migrated `.management-*`, `.scenario-card`, `.primary-action`, `.secondary-action`, `.run`, `.place`, `.mobility-panel`, `.updates-*`, `.crew-*`, modal/card padding and broad heading/button styling. | Grids, map sizes, print rules, meaningful status distinctions, responsive behavior; express shared values through design tokens. Remove dormant rules only after checking remaining consumers. |
| [interface.css](/Users/rabreu/Projects/personal/forest_fire/frontend/src/interface.css:1) | Duplicate fonts, surfaces, borders and button/card overrides on migrated sections. | Any remaining layout rules until their owners migrate. |
| [decision.css](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/decision.css:1) | `.decision-primary`, bespoke action skins, `.decision-card`, `.selected-road`, `.population-*`, `.decision-setup` visual definitions and heading overrides replaced above. | Workspace grids, map/Leaflet sizing and responsive arrangement. Centralize severity/selection colors; preserve domain A/B distinctions. Reformat the minified source before selective cleanup so changes are reviewable. |
| [public-demo.css](/Users/rabreu/Projects/personal/forest_fire/frontend/src/components/public-demo.css:1) | Repeated intro width/padding/type declarations, `.public-choice button` skins and story-card framing. | Public layout, map placement, responsive ordering and footer structure, after overflow fixes. |
| [design-tokens.css](/Users/rabreu/Projects/personal/forest_fire/frontend/src/design-tokens.css:1) | No competing page-specific values. | Single source for shared spacing, type, borders, surfaces, control states, focus and any approved compact/danger/status additions. |

## Proposed order and completion checks

1. **Foundation:** add semantic danger/selection/field/status treatments, accessible Dialog lifecycle, anchor styling and any needed compact Card option. Keep existing spacing/type defaults. Establish a common page baseline for both entry points.
2. **Current decision workflow:** fix mobile overflow and labels; migrate DecisionWorkspace, PopulationDataEditor, AccessViews, DecisionResults, advisories and timeline. This also improves shared public-demo results.
3. **Scenario and simulation flow:** list, overview, both creation paths, preparation wizard, simulation setup/detail, viewer/timeline and external-source panels. Resolve the forecast contrast and ineffective setup Cancel action here.
4. **Mobility and field use:** map panels, planner, road reports, details, board, updates, sources, inventory, crew, shared/print brief. Resolve stale previews, mobile connection visibility and missing error feedback.
5. **Public demo and archive:** finish entry-point/layout unification; distinguish loading, errors and empty archive categories. Keep all twelve archive categories accessible.
6. **Retained code:** record dormant status, consolidate only shared helpers still used, and remove obsolete styles only after consumer checks. Restoration/removal of old workflows is a separate product decision.

Each migrated group must pass:

- Main and public production builds and TypeScript checks.
- 390px and desktop visual checks, plus narrow-screen and 200% zoom checks: no page-level horizontal overflow; intentionally scrollable boards remain contained and labeled.
- Keyboard-only navigation: visible focus; usable tabs/choices; dialog open, Tab/Shift+Tab, Escape and focus return; equivalent form/list access to map actions.
- Accessible names for every input/select/textarea and icon-only action; meaningful headings and landmarks; normal text contrast at least 4.5:1, including selected/hover states.
- Pending, success, error, empty and read-only states; prevented duplicate mutations; movement preview invalidation whenever inputs change; appropriate disabled explanations.
- Existing source provenance, status distinctions, review/version acknowledgements, crew request-id retry behavior and print output remain intact.
- Existing primary/secondary/outline/ghost hover, active, focus-visible and disabled states remain consistent; reduced-motion preference is respected.
- No retired visual class is left overriding a migrated primitive. Full-page content uses SectionContainer once; maps and compact controls use the designated token layout rules.

This is an implementation plan with source and browser evidence, not a claim of complete WCAG conformance. The conditional populated/integration states identified above must be exercised with fixtures during implementation.
