# Product

## Register

product

## Users

WUDup is used by self-hosted operators who maintain Docker Compose stacks, review update signals from What's Up Docker, and decide when to snooze, preview, or apply container updates. They are usually working in an admin context where speed matters, but where a mistaken update can affect running services.

## Product Purpose

The product helps operators see update status, understand risk, review affected stacks and images, manage snoozes or exclusions, and confirm what changed before applying updates. Success means the operator can move from "what needs attention" to a safe decision with minimal hunting, clear evidence, and explicit confirmation before mutation. Recent additions include a Diagnostics Support Bundle to quickly capture system state and a WebUI Apply Preflight Readiness Summary to ensure operator safety during update mutations.

## Brand Personality

Calm, reliable, compact.

The WebUI should feel like a polished self-hosted admin appliance: quiet, precise, and operationally trustworthy. It should favor dense but readable information, direct labels, and stable controls over expressive branding or decorative visual effects.

## Anti-references

Do not make the WebUI feel like a startup SaaS landing page, crypto or AI dashboard, neon glassmorphism interface, shadcn clone, or generic gradient-heavy dashboard. Avoid hero sections, decorative blobs, glowing cards, unnecessary animations, fake metrics, and card-within-card clutter.

## Design Principles

- Lead with operational clarity: show current status, pending work, and blockers before secondary detail.
- Make mutation risk explicit: preview plans, label read-only state, and require confirmation for actions that change services.
- Keep density useful: compact layouts are welcome when labels, spacing, and hierarchy still support scanning.
- Prefer evidence over decoration: icons, color, and motion should clarify state or action, not fill space.
- Preserve operator confidence: use consistent controls, predictable navigation, visible focus states, and plain language.

## Accessibility & Inclusion

Target WCAG AA. Support reduced motion, keyboard navigation, visible focus states, sufficient contrast, and color-blind-safe status cues. Status must never rely on color alone; pair color with labels, icons, or text. Full WCAG AAA is not required unless a specific component can reach it without compromising the product workflow.
