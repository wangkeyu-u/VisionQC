# Product

## Register

product

## Users

VisionQC is used by quality inspectors, quality managers, line operators, ML engineers, system administrators, auditors, and FDE/deployment engineers in a manufacturing quality workflow. Inspectors work at a desktop workstation under time pressure: they need to move from a prioritized review task to image evidence, an accountable decision, and an auditable receipt without losing production context. Managers and deployment engineers need a trustworthy view of tenant-scoped packs, gateways, models, policies, connectors, and open quality events.

## Product Purpose

VisionQC turns industrial visual anomaly evidence into a controlled quality workflow. It receives images with tenant, product, batch, station, and capture context; preserves model/package/policy evidence; routes samples through deterministic thresholds; and supports named human review, MES/QMS actions, audit timelines, and closure. Success means a credible, repeatable pilot that makes the evidence and the limits of the system obvious: an anomaly score or heatmap is not a confirmed defect, root cause, or disposition.

The current product spans two tenant-scoped Deployment Packs, a directory-based Edge Gateway, manual upload, review, incident closure, Mock MES/QMS, and offline ModelOps evidence. Synthetic smoke results are implementation evidence only. Real MVTec/customer evaluation, production identity, PostgreSQL RLS, real cameras, Kafka, and Kubernetes remain outside this iteration.

## Brand Personality

Mature, restrained, operational. The interface should feel like an industrial quality control center: calm under pressure, precise about evidence, explicit about risk, and honest about what is live, simulated, or not yet production-ready. Chinese is the primary interface language; model, package, gateway, and connector identifiers may remain in English for traceability.

## Anti-references

Do not make this a dark-mode SaaS showcase, a decorative analytics landing page, or a generic AI dashboard. Avoid large gradients, glassmorphism, excessive shadows, rounded-card seas, decorative all-caps English, fake demo metrics, and visual polish that hides missing evidence. Do not present synthetic smoke metrics as production performance, do not use color alone for state, and do not frame model anomaly output as a confirmed defect.

## Design Principles

- **Evidence before conclusion:** put original image, heatmap, score, thresholds, model/package/feature-bank/policy versions, context, status, and audit evidence in the same decision path.
- **Operational density with hierarchy:** prioritize the next safe action, queue pressure, gateway health, and closure blockers; reduce navigation and decorative copy that compete with work.
- **Human accountable, fail safe:** make responsibility, high-risk confirmation, recovery, and submission receipts explicit; missing or failed evidence never becomes automatic release.
- **Configuration is the product boundary:** expose tenant, factory, product, Deployment Pack, Gateway, ModelOps, and Connector contracts without customer-specific code branches.
- **Honest status semantics:** distinguish real API data, Mock data, synthetic smoke evidence, and unavailable production evidence in the interface itself.

## Accessibility & Inclusion

Target reasonable WCAG AA for the pilot: keyboard navigation and visible focus, labelled form controls, semantic headings and status text, sufficient contrast, non-color state cues, reduced-motion support, readable desktop density at 1440/1280px, and a minimum supported workbench width of 1024px. High-risk actions require explicit confirmation and clear impact wording; errors must include an actionable next step and correlation ID when available.
