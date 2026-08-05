---
name: VisionQC Industrial Quality Workbench
description: A restrained, evidence-first visual system for a Chinese industrial quality control room.
colors:
  signal-blue: "#155EEF"
  signal-blue-deep: "#1246B6"
  graphite: "#1E2A27"
  graphite-soft: "#485853"
  canvas: "#EDF1EF"
  surface: "#FFFFFF"
  surface-subtle: "#F7F9F8"
  line: "#D6DFDA"
  normal-green: "#18794E"
  warning-amber: "#A65F00"
  danger-red: "#B42318"
typography:
  display: "Inter, PingFang SC, Noto Sans SC, sans-serif"
  headline: "Inter, PingFang SC, Noto Sans SC, sans-serif"
  title: "Inter, PingFang SC, Noto Sans SC, sans-serif"
  body: "Inter, PingFang SC, Noto Sans SC, sans-serif"
  label: "IBM Plex Mono, SFMono-Regular, ui-monospace, monospace"
rounded:
  sm: "4px"
  md: "6px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "22px"
  xl: "28px"
components:
  button-primary:
    backgroundColor: "{colors.signal-blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.sm}"
    padding: "0 13px"
    height: "36px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.sm}"
    padding: "0 13px"
    height: "36px"
  status-badge:
    backgroundColor: "{colors.surface-subtle}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.sm}"
    padding: "4px 8px"
  evidence-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.md}"
    padding: "14px"
  metric-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.md}"
    padding: "14px"
---

## Overview

**Creative North Star: "The Line-Side Evidence Ledger"**

VisionQC is a mature industrial quality control room: quiet, dense, and accountable. The interface should feel like a well-designed production instrument rather than a marketing surface. Every high-value decision starts with evidence, then exposes the policy, model, operator, and external-system trail that supports it.

The system uses an industrial white and graphite canvas with one signal-blue interaction accent. Semantic colors are deliberately narrow: green means normal, amber means attention or warning, and red means danger or an unresolved stop condition. A flat tonal hierarchy, compact navigation, and 1px rules keep the workbench readable at 1440px, 1280px, and the 1024px minimum desktop width.

**Key Characteristics:**

- Evidence-first layouts with the original image and heatmap as the visual anchor.
- Chinese as the primary interface language; identifiers and version strings remain machine-readable.
- Dense operational tables and short status labels instead of decorative hero copy.
- Explicit empty, loading, error, and mock-data boundaries; no invented production metrics.
- Keyboard-ready actions, visible focus, and state labels that never rely on color alone.

## Colors

**The One Signal Rule.** Use `#155EEF` and its deep state `#1246B6` for interaction, selection, links, and primary actions only. Do not use blue as a health or quality status.

The canvas is `#EDF1EF`, primary surfaces are `#FFFFFF`, and graphite `#1E2A27` carries text and structure. `#18794E` is reserved for normal or complete states, `#A65F00` for warnings and queued attention, and `#B42318` for danger, failure, or a quality stop. Every semantic color is paired with a Chinese label and, where useful, an icon or count.

## Typography

**The Instrument Hierarchy Rule.** Use a compact system sans stack (`Inter`, `PingFang SC`, `Noto Sans SC`, system sans) for Chinese-readable headings and body copy. Use `IBM Plex Mono` with a system-mono fallback for scores, timestamps, IDs, hashes, gateway versions, and policy/model identifiers. Headings are concise and sentence case; labels are not decorative all-caps English.

The visual hierarchy is operational: page title, one-line purpose, dense section title, then evidence or action. Scores and IDs may use mono numerals, but no display treatment should overpower the evidence itself.

## Elevation

**The Flat Ledger Rule.** Establish hierarchy with white surfaces, the `#D6DFDA` rule, and the subtle `#F7F9F8` tonal layer. Cards have 1px borders and 4–6px radii. Decorative shadows, glassmorphism, blur, and large gradients are not part of the system; a small focus ring or transient overlay may use a restrained shadow when it improves keyboard or modal clarity.

## Components

**The Evidence Before Decoration Rule.** The global shell is a compact header plus a context bar for customer, site, Deployment Pack, Gateway health, and operator state. It never consumes a full permanent sidebar. The overview uses metric rows, an attention queue, event state, and Gateway telemetry. Inspection detail uses an original/heatmap evidence viewer with a compact metadata rail. Review uses a desktop queue → evidence → decision structure, while incidents use a timeline and external MES/QMS actions.

Buttons are 36px high, rectangular with a 4px radius, and have clear primary, secondary, danger, and quiet variants. Status badges combine a small mark with text. Tables use compact rows with visible headers and not just color-coded cells. Forms have real labels and inline recovery messages. Loading and empty states retain the page structure and explain what data is missing.

The layout is designed for 1440px and 1280px workstations and remains usable at a 1024px minimum width. At the minimum width, secondary columns stack below the evidence area; mobile-specific simplification is out of scope for this pilot. Motion is limited to state feedback and respects `prefers-reduced-motion`.

## Do's and Don'ts

### Do:

- **Do** keep industrial white and graphite as the dominant surfaces and use signal blue only for interaction.
- **Do** use green only for normal, amber for warning/attention, and red for danger or failure; pair each with text.
- **Do** make the original image and heatmap the primary visual area on inspection and review screens.
- **Do** show API-backed values, honest empty states, and a visible Mock mode boundary when fixtures or Mock MES/QMS are active.
- **Do** preserve tenant switching, manual upload, Gateway operations, review, incidents, and keyboard recovery at the 1024px desktop minimum.
- **Do** state that an anomaly is not a confirmed defect until a named operator records the decision.

### Don't:

- **Don't** use large gradients, glassmorphism, excessive shadows, or a sea of rounded cards.
- **Don't** use decorative all-caps English labels or static demo copy that consumes operational space.
- **Don't** hardcode fake metrics such as “128 件” or “3 个待处理”; show an honest empty state when the API has no data.
- **Don't** present synthetic smoke metrics as production effectiveness or invent formal MVTec results.
- **Don't** hide actions behind color alone, remove high-risk confirmation, or delete existing pilot functions for visual simplicity.
