# Popup browser checks

Start the frontend with `npm run dev`, then open
`http://127.0.0.1:5173/tests/popups.html?scene=regressions`.
Click **Iniciar verificações**. Eleven checks exercise the real Leaflet viewport:
initial focus, point selection, coordinate commits, preserving manual panning,
coverage bounds, resizing, explicit recentering, and invalid coordinates.

The same page mounts the production forms against in-memory API responses.
No import, preparation, inventory, or scenario request reaches the backend.
Fixtures are excluded from production entrypoints and builds.

Scenes: `wizard`, `area`, `fogos`, `manager`, `inventory`, `manual`, `coordinates`.
Use `?scene=wizard&state=failed` for retry, `state=running` for cancellation,
`cost=1` for a required processing acknowledgement, `fail=1` for save failure,
`missing=1` for an incident without coordinates, and `unavailable=1` for an
unconfigured integration. Successful preparation returns a partial catalog.

Check each form at 1440×900, 1024×768, 375×667, and a 720×450 CSS viewport (200% reflow equivalent of 1440×900):

- Long names and expanded optional fields wrap without horizontal overflow.
- Header and actions remain accessible; desktop map stays visible while fields scroll.
- Only the selected ignition has an editor; valid commits recenter, partial typing does not.
- Empty or out-of-range coordinate drafts show an inline error and prevent continuing.
- Map remains mounted during preparation and review; clicks cannot move points then.
- Keyboard focus stays in the dialog; Escape closes and restores the opener when permitted.
- Inventory tabs support arrows, Home, and End; switching tabs preserves drafts.
- Failed operations show feedback inside the dialog; retry and cancellation retain their behavior.

Type-check the fixtures with `npx tsc --project tests/tsconfig.json --noEmit`.

## Navigation checks

Start the isolated navigation server with `npm exec vite -- --config tests/navigation.vite.config.ts`.
Open `http://127.0.0.1:5174/tests/navigation.html` and select **Iniciar verificações de navegação**.
The 32 checks exercise production components with in-memory responses. Unexpected fetch requests
fail immediately; the test server has no backend proxy and its image policy blocks external map tiles.

The fixture server also serves production paths directly, so reload and bookmark checks work:
`/scenarios/navigation-fixture/experiments`, `/mobility/units`, `/decisions?view=data`, and legacy archives.
Use the full occurrence prefix for mobility/decision paths. Add `?crew=1` for the focused crew view,
`?empty=1` for no completed simulations, and `?offline=1` to exercise a previously cached mobility snapshot.
`/scenarios/missing` exercises an unavailable occurrence; `/brief/fixture` exercises a standalone public brief.

Run the suite at CSS viewport widths of 1440, 1024, 720 (200% reflow equivalent), and 390 pixels.
Also inspect the mobility map at 1200px, where the desktop sidebar reduces the map's available width.
Each destination checks its content width as well as the document width. Also verify the drawer with
Tab/Shift+Tab, Escape, focus restoration, active navigation, and sidebar/map resizing.

Each visited destination also rejects blue link text and checks that adjacent form controls
share a baseline when their labels occupy the same row, including wrapped labels.
Stacked fields must retain spacing, and map actions must clear zoom controls and information panels.

Static route/brand checks: `node --experimental-strip-types --test tests/navigation.test.ts` (Node 22.13+).
Type-check fixtures with the command above. Production build and `npm run check:language` must also pass.

## PRUMO branding checks

The navigation checks also verify the accessible logo, approved theme-specific accent and page titles, including
a standalone brief. Use `/scenarios?login=1` for the login view,
`/brief/fixture?brief=1` for a populated fictional brief, and `?light=1`
for the existing light theme. These variants use only in-memory responses.
Static tests compare inline/exported logo geometry, approved export colors, title/icon declarations, and icon dimensions.
Check the populated brief with print preview and background graphics disabled.

If native print preview is unavailable, append `&print-preview=1` to the populated
brief URL. The fixture applies the actual print rules from the loaded stylesheets
to the screen, allowing inspection of the monochrome SVG on white.
