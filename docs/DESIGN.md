---
name: WUDup
description: A compact operator dashboard for reviewing and safely applying Docker updates.
colors:
  ink: "#172026"
  body-bg: "#f5f7f8"
  surface: "#ffffff"
  sidebar: "#132126"
  sidebar-hover: "#21383f"
  sidebar-text: "#f7fbfc"
  sidebar-muted: "#c9d6d9"
  muted-text: "#65747a"
  border: "#dbe3e6"
  border-subtle: "#e6ecef"
  border-hover: "#86b7dd"
  panel-tint: "#f9fbfc"
  table-head: "#f0f5f6"
  action-blue: "#0f6fbd"
  operational-teal: "#137a63"
  login-bg: "#eef3f5"
  log-bg: "#0f171a"
  log-text: "#d8e8df"
typography:
  title:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1.35rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "0.78rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0"
  data:
    fontFamily: "SFMono-Regular, Consolas, Liberation Mono, monospace"
    fontSize: "0.84rem"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  sm: "7px"
  md: "8px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  sidebar-gap: "28px"
components:
  button-primary:
    backgroundColor: "{colors.operational-teal}"
    textColor: "{colors.surface}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "32px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "32px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.lg}"
  metric-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.lg}"
  sidebar-nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.sidebar-muted}"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "42px"
  sidebar-nav-item-active:
    backgroundColor: "{colors.sidebar-hover}"
    textColor: "{colors.surface}"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "42px"
  list-row:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
  table-head:
    backgroundColor: "{colors.table-head}"
    textColor: "{colors.muted-text}"
    typography: "{typography.label}"
    padding: "10px 12px"
  text-link:
    backgroundColor: "transparent"
    textColor: "{colors.action-blue}"
    typography: "{typography.body}"
  input-text:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "4px 10px"
    height: "32px"
  status-tag:
    backgroundColor: "{colors.panel-tint}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 8px"
    height: "24px"
  log-viewer:
    backgroundColor: "{colors.log-bg}"
    textColor: "{colors.log-text}"
    typography: "{typography.data}"
    rounded: "{rounded.md}"
    padding: "{spacing.lg}"
---

# Design System: WUDup

## 1. Overview

**Creative North Star: "The Operator Console"**

WUDup should feel like a small self-hosted admin appliance that has one job: help an operator understand update state and act safely. The visual system is calm, reliable, and compact. It uses cool neutral surfaces, a dark teal sidebar, modest borders, and restrained accent color so the content stays ahead of the chrome.

The interface rejects marketing-page performance. It should not use hero sections, decorative gradients, glowing cards, fake metrics, or card-within-card clutter. Density is part of the brand when it helps operators compare images, stacks, plans, and history without losing orientation.

**Key Characteristics:**
- Compact grids and tables that prioritize scanning.
- Cool neutral surfaces with a dark operational sidebar.
- One sans family for labels, controls, headings, and data-adjacent UI.
- Flat-by-default panels with 1px borders and small radius.
- State expressed with text, icons, and labels, never color alone.
- Explicit operator safety tools, such as the Apply Preflight Readiness Summary and Diagnostics Support Bundle.

## 2. Colors

The palette is a restrained product palette: cool neutrals carry the surface, dark teal anchors navigation, and accent color appears only for state, links, current selection, and action clarity.

### Primary
- **Operational Teal**: Icon and state accent for update-related affordances. Use it sparingly for positive operational cues and never as page decoration.
- **Action Blue**: Link and command color. Use for navigational text links, hover borders, and explicit user actions that need to stand apart from passive data.

### Neutral
- **Console Ink**: Primary text for headings, labels with emphasis, and dense data.
- **Cool Workbench**: App background behind the main task surface.
- **Panel White**: Primary panel, card, table, and login surface.
- **Deep Sidebar**: Persistent navigation background and login mark background.
- **Sidebar Current**: Active and hovered sidebar item fill.
- **Sidebar Text**: High-contrast sidebar brand and active text.
- **Sidebar Muted**: Inactive sidebar item text.
- **Muted Slate**: Secondary text, table headings, metadata, empty-state text, and definition labels.
- **Panel Border**: Primary 1px panel and table border.
- **Subtle Divider**: Inner row borders and low-emphasis card borders.
- **Hover Border**: Interactive row and shortcut hover border.
- **Soft Panel Tint**: Shortcut and plan-action background.
- **Table Header Tint**: Management table header background.
- **Log Charcoal**: Log viewer background.
- **Log Mint Text**: Log viewer text.

### Named Rules

**The Ten Percent Accent Rule.** Operational Teal and Action Blue together should stay under 10% of any task screen. Their rarity is what makes them useful.

**The Status Needs Words Rule.** Color can reinforce status, but status must always include a label, icon, or text description.

## 3. Typography

**Display Font:** Inter with system sans fallbacks.
**Body Font:** Inter with system sans fallbacks.
**Label/Mono Font:** SFMono-Regular, Consolas, Liberation Mono for digests, commands, and logs.

**Character:** This is a single-family product UI, not a brand typography system. It should read as familiar, compact, and sturdy, with weight and spacing doing the hierarchy work.

### Hierarchy
- **Title** (700, 1.35rem, 1.2): Page headings, section headings, and login heading. Keep fixed rem sizing for product stability.
- **Body** (400, 1rem, 1.5): Main content and control-adjacent copy. Keep long prose rare and cap explanatory copy around 65-75ch.
- **Metadata** (400, 0.82-0.85rem): Secondary row values, metric captions, plan summary labels, and compact helper text.
- **Label** (700, 0.78rem, uppercase only for short system labels): Eyebrows and management table heads. Use sparingly because repeated uppercase labels add noise.
- **Data Mono** (400, 0.82-0.84rem, 1.55 for logs): Digests, command arguments, and log output.

### Named Rules

**The Fixed Scale Rule.** Do not use fluid headline clamps in the app shell. This is an operator tool, so type should stay predictable across screen sizes.

**The No Display Voice Rule.** Do not introduce display fonts for labels, buttons, tables, or navigation.

## 4. Elevation

WUDup is flat by default. Depth is carried by borders, tonal layers, and layout position. The only ambient shadow currently used is a tiny panel lift, subtle enough to read as separation rather than decoration.

### Shadow Vocabulary
- **Panel Lift** (`box-shadow: 0 1px 2px rgb(23 32 38 / 0.04)`): Use only on major panels, metric cards, login panels, and mobile cards. Do not combine it with large blur values.

### Named Rules

**The Border First Rule.** Use a 1px border and tonal layering before adding a shadow.

**The No Glow Rule.** Glowing cards, neon accents, and decorative blur are prohibited.

## 5. Components

### Buttons
- **Shape:** Gently squared controls, matching the product radius system (7-8px).
- **Primary:** Use library primary buttons for explicit commands such as previewing plans or applying updates. Keep labels as verb plus object: "Preview plan", "Update selected", "Sign in".
- **Hover / Focus:** Hover should make the control feel interactive without shifting layout. Focus must remain visible and keyboard-accessible.
- **Secondary / Ghost:** Use quaternary or secondary buttons for refresh, sign out, select all, clear selection, and similar support actions.

### Chips
- **Style:** Small tags carry read-only state, selected count, plan status, line numbers, and policy state.
- **State:** Tags should include readable text. Warning, success, and error states must not rely on hue alone.

### Cards / Containers
- **Corner Style:** Compact product radius (7-8px).
- **Background:** Panel White for primary panels, Soft Panel Tint for shortcut and plan-action rows, Table Header Tint for dense table headings.
- **Shadow Strategy:** Panel Lift only for large panels and cards, never for inner rows.
- **Border:** 1px Panel Border on outer panels, 1px Subtle Divider on rows and inner utility cards.
- **Internal Padding:** 16px for panels and metric cards, 12px for shortcut and summary cards, 8px 10px for dense list rows.

### Inputs / Fields
- **Style:** Use Naive UI field controls with the same 7-8px radius vocabulary and compact sizing.
- **Focus:** Visible focus is required. Do not remove library focus outlines unless replacing them with an equal or stronger focus ring.
- **Error / Disabled:** Error and disabled states must include text feedback, not only color or disabled opacity.

### Navigation
- **Style:** Fixed dark sidebar on desktop, sticky horizontal compact bar below 920px. Navigation items use 42px minimum height, 10px horizontal padding, 7px radius, and lucide icons.
- **States:** Inactive items use Sidebar Muted. Active and hovered items use Sidebar Current with white text. Preserve both icon and label wherever space allows.
- **Mobile:** Keep the brand mark visible and let nav items scroll horizontally. Do not collapse navigation into an invented custom control.

### Responsive Breakpoints
- **Compact (`--wud-compact`, 560px):** Stack dense control groups, tighten dialog and panel spacing, and switch small action rows to single-column treatment.
- **Narrow actions (`--wud-narrow-actions`, 760px):** Reflow settings action controls before the full compact layout is needed.
- **Data cards (`--wud-data-cards`, 768px):** Switch dense management tables and history tables to card/list views.
- **App shell (`--wud-app-shell`, 920px):** Move the fixed sidebar into the sticky horizontal shell and adjust app-level navigation/action chrome.
- **Management cards (`--wud-management-cards`, 1120px):** Switch broad settings management tables, such as snoozes and tag exclusions, to card views.
- **Policy management cards (`--wud-policy-management-cards`, 1200px):** Keep policy management on its wider existing card threshold.
- **Reduced motion (`--wud-reduced-motion`):** Remove nonessential transition duration and use instant or browser-default scroll behavior.

### Data Surfaces
- **Tables:** Use Naive UI tables for wide data on desktop, then switch to mobile cards under the existing breakpoint behavior.
- **Rows:** Use 1px borders, compact 8-12px spacing, and `overflow-wrap: anywhere` for image names, digests, and paths.
- **Logs:** Logs use Log Charcoal and Log Mint Text with mono typography. They are a distinct utility surface, not a decorative dark-mode theme.

## 6. Do's and Don'ts

### Do:
- **Do** keep screens calm, reliable, and compact.
- **Do** lead with pending count, status, blockers, and recent activity before secondary management controls.
- **Do** use Deep Sidebar, Cool Workbench, and Panel White as the dominant color structure.
- **Do** use Operational Teal and Action Blue only for state, icons, current selection, links, and explicit actions.
- **Do** use labels, icons, and text for every status. Color is reinforcement, not the message.
- **Do** keep panel corners at 7-8px and panel shadows at `0 1px 2px rgb(23 32 38 / 0.04)` when a shadow is needed.
- **Do** favor direct labels such as "Preview plan", "Update selected", and "Sign out".

### Don't:
- **Don't** make this feel like a startup SaaS landing page.
- **Don't** make this feel like a crypto or AI dashboard.
- **Don't** use neon glassmorphism UI.
- **Don't** make it a shadcn clone.
- **Don't** use generic gradient-heavy AI-generated dashboard styling.
- **Don't** add hero sections, decorative blobs, glowing cards, unnecessary animations, fake metrics, or card-within-card clutter.
- **Don't** use gradient text, decorative side-stripe borders, oversized radii, or repeated identical card grids.
- **Don't** hide mutation risk behind vague labels. Plan, preview, and apply actions must stay explicit.
