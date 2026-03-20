# PDHC Frontend Design System

Style guide for all subprojects under the PDHC (Patient-Driven Healthcare) platform. Follow these conventions to maintain visual consistency across services. Reference implementation: `sso.pdhc.se`.

---

## Design Philosophy

**Clinical clarity meets modern design.** The interface should feel trustworthy and professional — like a well-designed medical instrument. Every element earns its place. White space is not wasted space; it is breathing room for decision-makers who carry cognitive load.

We draw from Scandinavian healthcare design principles: restrained colour, generous spacing, clear typography, and no visual noise.

---

## Colour Palette

| Token              | Hex       | Usage                                       |
|--------------------|-----------|----------------------------------------------|
| `--primary`        | `#2563eb` | Navbar background, primary buttons, links    |
| `--primary-dark`   | `#1d4ed8` | Button hover, focus ring                     |
| `--danger`         | `#dc2626` | Rejected, error, destructive actions         |
| `--success`        | `#16a34a` | Approved, active, connected                  |
| `--warning`        | `#d97706` | Pending, caution                             |
| `--bg`             | `#f8fafc` | Page background                              |
| `--card-bg`        | `#ffffff` | Cards, panels, modals, table rows            |
| `--text`           | `#1e293b` | Primary text, headings                       |
| `--text-muted`     | `#64748b` | Secondary text, labels, muted content        |
| `--border`         | `#e2e8f0` | Card borders, dividers, table lines          |
| `--code-bg`        | `#f1f5f9` | Code/monospace backgrounds, table headers    |

### Rules
- Never use pure black (`#000`) for text. Use `--text` or `--text-muted`.
- Background must always be `--bg` or `--card-bg`. No dark mode (clinical environments require high contrast on light backgrounds).
- Status colours (`success/warning/danger`) are used **only** for status indicators and action buttons — never for decoration.

---

## Typography

| Element         | Font                                                      | Size    | Weight | Line-height |
|-----------------|-----------------------------------------------------------|---------|--------|-------------|
| Page title      | -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif | 1.4rem  | 700    | 1.3         |
| Section heading | (same stack)                                              | 1.1rem  | 700    | 1.3         |
| Subsection      | (same stack)                                              | 1rem    | 600    | 1.3         |
| Body text       | (same stack)                                              | 12px    | 400    | 1.6         |
| Small/label     | (same stack)                                              | 0.92em  | 600    | 1.4         |
| Monospace       | SF Mono, Fira Code, Consolas, monospace                   | 0.9em   | 400    | 1.5         |

### Rules
- Use system font stack — no external font loading required.
- Body font-size base: `12px`. Compact density suited for clinical data-heavy interfaces.
- Never use more than 3 font weights on a single page.
- Headings use `--text`. Body uses `--text` or `--text-muted`.

---

## Spacing Scale

Based on `0.25rem` (3px at 12px base) increments.

| Token  | Value  | Usage                          |
|--------|--------|--------------------------------|
| `xs`   | 0.2rem | Tight gaps, icon padding       |
| `sm`   | 0.4rem | Inline spacing, badge padding  |
| `md`   | 0.5rem | Input padding, small gaps      |
| `base` | 0.75rem| Default element spacing        |
| `lg`   | 1rem   | Card padding, section gaps     |
| `xl`   | 1.25rem| Section separators             |
| `2xl`  | 2.5rem | Page-level vertical rhythm     |

---

## Component Patterns

### Cards
```css
.card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
```
- No heavy drop shadows. Borders define edges; shadows are subtle depth cues only.

### Buttons
```
Primary:    bg primary (#2563eb), white text, rounded 5px
Secondary:  bg #e2e8f0, dark text, hover #cbd5e1
Danger:     bg danger, white text — only for destructive actions
Success:    bg success, white text
Regular:    padding 0.35rem 0.9rem, font-size 0.92em
Small:      padding 0.2rem 0.6rem, font-size 0.85em
```
- All buttons have `font-weight: 600`.
- Transitions: `background 0.2s`.

### Forms
- Labels above inputs, `font-weight: 600`, `0.92em` font-size.
- Inputs: `0.3rem 0.5rem` padding, `1px solid var(--border)`, `border-radius: 5px`.
- Focus: `border-color: var(--primary)` with `box-shadow: 0 0 0 2px rgba(37,99,235,0.1)`.
- Error state: border becomes `--danger`, message below in small red text.
- Group related fields in a card.

### Tables
- Header row: `--code-bg` (#f1f5f9) background, `font-weight: 600`, `0.92em` uppercase text.
- Cell padding: `0.4rem 0.6rem`.
- Horizontal borders only (no vertical cell dividers).
- Row hover: `--bg` background.

### Status Badges
```css
.badge { padding: 0.1rem 0.4rem; border-radius: 9999px; font-size: 0.85em; font-weight: 600; }
.badge-approved  { background: #dcfce7; color: #166534; }
.badge-pending   { background: #fef3c7; color: #92400e; }
.badge-rejected  { background: #fef2f2; color: #991b1b; }
.badge-endorsed  { background: #dbeafe; color: #1e40af; }
```

### Navbar
- Sticky top, `--primary` (#2563eb) background, white text.
- Padding: `0.5rem 1.25rem`.
- Logo/service name left-aligned (`font-weight: 700`, `1rem`), nav links right-aligned.
- Link hover: `background: rgba(255,255,255,0.15)`, border-radius 4px.
- Link font-size: `0.92em`.
- Mobile: stacks vertically.

---

## Layout

- Max content width: `960px` (standard), `1200px` (wide). Centred.
- Page padding: `1.25rem` horizontal, `1.25rem` top, `2.5rem` bottom.
- Grid utilities: `.grid-2` (2-col), `.grid-3` (3-col) with `1rem` gap.
- Dashboard grid: `repeat(auto-fill, minmax(12rem, 1fr))` with `1rem` gap.
- All layouts are responsive. Breakpoint: `768px`.
- Mobile: grids collapse to single column, nav stacks vertically.

---

## Icons

Use **Lucide** icons (MIT licensed, consistent stroke-based style). Load via CDN.

- Stroke width: `1.5px`.
- Size: `1rem` for inline, `0.85rem` for buttons, `1.5rem` for dashboard feature cards.
- Colour inherits from parent text colour.

---

## Accessibility

- Minimum contrast ratio: 4.5:1 for body text, 3:1 for large text.
- All interactive elements must be keyboard-navigable with visible focus indicators.
- Form inputs must have associated `<label>` elements (not just placeholder text).
- Status information must not rely solely on colour — include text labels or icons.
- Use `aria-live="polite"` for flash messages and dynamic status updates.

---

## Animation

- Transitions: `0.2s` for hover states and focus.
- No animation on page load. No parallax. No auto-playing carousels.
- Respect `prefers-reduced-motion`: disable all transitions when set.

---

## File Organisation

```
static/
  css/
    pdhc.css          <- Full design system (variables + components)
templates/
  base.html           <- Navbar, flash, footer, CSS/JS includes
  dashboard.html
  concepts/           <- Concept CRUD templates
  values/             <- Value CRUD templates
  valuesets/           <- ValueSet CRUD templates
  plandefinitions/    <- Builder + list + view templates
  lookup/             <- Lookup table CRUD templates (4 types x 4 templates)
  docs.html           <- Documentation browser
```

Subprojects should import `pdhc.css` (or its CSS variables block) and extend `base.html`. Page-specific styles go in `<style>` blocks within the template, never in separate per-page CSS files.

---

## Do / Don't

| Do | Don't |
|----|-------|
| Use the colour tokens | Invent new colours |
| Keep forms simple and vertical | Nest forms in tabs or accordions |
| Show status with badge + text | Rely on colour alone |
| Use one primary action per card | Clutter cards with multiple CTAs |
| Let tables scroll horizontally on mobile | Hide columns on small screens |
| Use real loading states | Block the UI without feedback |
| Use 12px base font for compact density | Override to larger font sizes |
