# Shared UI components

Import from `./components/ui` (relative to the calling file), or import a component
directly. Each component loads `design-tokens.css`; Vite deduplicates the import.
There are no new runtime dependencies. The application, public replay and retained
planning interfaces now use these primitives. Existing handlers, data expressions,
map geometry and native form behavior are preserved.

```tsx
import { Button, Card, SectionContainer, Typography } from "./components/ui";

<SectionContainer aria-labelledby="section-title" containerClassName="ds-stack">
  <div className="ds-stack">
    <Typography id="section-title" variant="h2">
      Preparar exercício
    </Typography>
    <Typography variant="subtitle">Escolha um cenário para começar.</Typography>
  </div>
  <Card className="ds-stack">
    <Typography variant="h3">Novo cenário</Typography>
    <Typography>Defina os recursos e as condições do exercício.</Typography>
    <div className="ds-cluster">
      <Button onClick={createScenario}>Criar cenário</Button>
      <Button variant="outline" onClick={showDetails}>
        Ver detalhes
      </Button>
    </div>
  </Card>
</SectionContainer>;
```

## Button

- `variant`: `primary` (default), `secondary`, `outline`, `ghost`.
- `intent`: `default` or `danger`. Use destructive intent with the existing
  confirmation flow; do not use a separate red button class.
- `size`: `sm`, `md` (default), `lg`; minimum heights are 36, 44, and 52px.
  Prefer `md` or `lg` for touch interfaces. Labels wrap when space is limited.
- All variants share hover, pressed, keyboard focus, disabled, and reduced-motion
  rules. Colors follow the selected token theme.
- Native button props, event handlers, ARIA attributes, `className`, `style`, and
  a ref to the button are supported. `type` defaults to `button`; use
  `type="submit"` explicitly in forms.
- Both `disabled` and `aria-disabled={true}`/`"true"` produce a native disabled
  button: it cannot activate or receive tab focus. A disabled fieldset also works.
- Use visible text or an `aria-label` for every button. Keep decorative icons
  `aria-hidden`. Use an anchor for navigation; this component renders a button.
- `aria-pressed` and `aria-current="page"` receive the shared selected treatment.
  Preserve native radios/checkboxes when they already represent a choice.
- `ButtonLink` provides the same variants and sizes while rendering an anchor.
  It forwards `href`, `target`, `download`, events and the anchor ref.
- Plain links use the shared link token: primary text in dark mode and green in
  light mode, including map attribution and popup links. Preserve underlines and focus rings.

## Card and SectionContainer

`Card` defaults to a div with the card background, border, 3px corners, responsive
24/32px padding, and subtle shadow. `as` accepts `div`, `section`, `article`,
`aside`, `details`, `dialog` or `form`, preserving that element's native props and ref type.
Keep `summary` inside a details card and use `type="submit"` for form submission.
`shadow` accepts `none`, `card` (default), or `raised`; reserve `raised` for floating
panels. `density="compact"` uses the shared 16px padding for operational panels
and nested summaries. It does not change typography or the control sizes.

`SectionContainer` renders a section and a centered inner container. `as` may be
`section`, `main`, `div` or `footer` to retain the page's semantics. The section
owns the page surface and 64/96px vertical padding; the inner container owns the
1280px maximum width and 16/32px horizontal gutters. Sizes change at 768px.
`className`, native props, and the ref target the section. `containerClassName`
adds layout classes to the inner div. Give named sections `aria-labelledby`
pointing to a visible heading. `spacing="compact"` uses 16/32px vertical spacing
for compact workspaces such as the crew screen. Horizontal gutters remain 16/32px.
Use `Card` alone inside map panels; do not nest full content sections inside them.

## Layout and dialogs

`Box` is a ref-forwarding div for structural grids, stacks, map hosts and loading
regions. It adds no surface or spacing. Domain-specific class names on Box carry
layout only; use tokens for their gaps and padding.

`Dialog` renders a native modal dialog in a portal. It contains keyboard focus,
blocks background interaction, calls the existing `onDismiss` action on Escape,
and restores focus to the opener. Give it `aria-label` or `aria-labelledby` and
place a raised Card inside. Omit `onDismiss` only when the workflow cannot close.
The existing native ScenarioManager dialog retains its own busy-state lifecycle.
It uses `Card as="dialog"` for the shared surface while keeping its existing ref,
`showModal()` effect and cancellation handler.

## Typography

| Variant          | Default element | Size, mobile / desktop | Weight / line-height |
| ---------------- | --------------- | ---------------------- | -------------------- |
| `h1`             | h1              | 36 / 48px              | 600 / 1.15           |
| `h2`             | h2              | 28 / 36px              | 600 / 1.2            |
| `h3`             | h3              | 20 / 24px              | 600 / 1.3            |
| `body` (default) | p               | 16px                   | 400 / 1.6            |
| `subtitle`       | p               | 20px, muted by default | 400 / 1.6            |
| `small`          | small           | 14px                   | 400 / 1.5            |
| `label`          | span            | 12px, uppercase mono   | 700 / 1.5            |

Use `as` to choose a semantic element independently of size, e.g.
`<Typography as="h2" variant="h3">` for a smaller section heading. Supported
elements are h1–h6, p, span, div, and small. Keep the heading hierarchy meaningful.
The `label` variant is visual text; use a real HTML label for a form control.
`tone="muted"` selects secondary text; `tone="default"` keeps the variant's
standard color. Native HTML attributes and a ref to the rendered element work.

## Styling and migration

Shared visual tokens and control states live in `frontend/src/design-tokens.css`. Use
`data-ds-theme="light"` or `"dark"` on a wrapper to select a palette; dark is the
default. Both nested themes and a theme on the component itself are supported.

Use `PrumoBrand` for logos; it loads its own tokens and brand styles. Its
`--ds-brand-accent` is independent of hyperlink colors. Logo assets, palette
roles, naming and print rules are documented in `docs/BRANDING.md`.

Generated `data-ui`, `data-variant`, `data-size`, `data-intent`, `data-tone`,
`data-shadow`, `data-density` and `data-spacing` attributes belong to the components.
The four retained layout stylesheets use `@layer legacy`, below the shared styles.
Their overlapping presentation declarations have been removed; compatibility
variables are defined centrally in `design-tokens.css`.

Use `className` for layout: `ds-full`, `ds-list-action`, `ds-row-action` and
`ds-heading-action` cover the supported button layouts. `ds-crew-action` preserves
the crew action's 60px minimum touch height. Do not combine primitives with old
presentation classes such as `run`, `primary-action`, `danger` or `decision-primary`.
Keep Leaflet geometry/marker styling separate: it represents domain data, not UI
spacing or button variants. Native fieldsets, labels, disclosures and map hosts
remain semantic elements rather than being replaced with decorative cards.

## Popup forms

`PopupLayout` provides a compact heading, optional navigation, a scrollable field
region, optional map, and a persistent actions/feedback footer. Render it inside
`Dialog`; the dialog owns focus, Escape and background blocking. Pass `map` for
the wide split layout, `size="wide"` for long lists, or `size="drawer"` for inventory.
Put native forms in the field region and connect footer submit buttons with the
HTML `form` attribute. Keep operation errors in `feedback` and required warnings
expanded. Use existing design tokens for presentation and popup-layout.css for
geometry. `LocationMap` handles point and coverage previews; `CoordinateFields`
commits complete coordinate pairs on blur or Enter, preserving longitude/latitude
storage order. Browser fixtures and checks are documented in frontend/tests/README.md.
