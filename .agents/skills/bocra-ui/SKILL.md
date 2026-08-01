---
name: bocra-ui
description: Premium front-end design system and component library extracted from the BOCRA Connect government portal. Covers floating pill navbar, hero sections, cards, modals, badges, buttons, inputs, toasts, glassmorphism, responsive tables, and full color/typography system. Use this skill to turn crowded layouts into premium, responsive government and enterprise web systems.
---

# BOCRA Connect — Front-End Design System Skill

## 1. Design Tokens & Color System

### Primary & Brand Colors
- **Primary Navy**: `#1A3A6B` — Main brand, nav links, header elements
- **Accent Blue**: `#2E5FA3` — Secondary accents & focus highlights
- **Light Blue**: `#D6E4F7` — Pill backgrounds, hover states, icon container bg
- **Teal / Emerald**: `#0F6E56` — Success indicators, active status, badges
- **Deep Black**: `#050505` — Primary CTA buttons & high-contrast elements
- **Near Black**: `#0b1f3a` — Headings, key text metrics

### Neutral Palette
- `#111827` — Primary text, main titles
- `#334155` — Subtitles, form labels
- `#64748b` — Muted body text, metadata
- `#e2e8f0` — Subtle card borders, section dividers
- `#f8fafc` — Primary light page canvas background
- `#ffffff` — Crisp white card backgrounds

### Semantic Badges
- **Draft / In Progress**: `bg: #eff6ff`, `text: #1e40af`, `border: #bfdbfe`
- **Submitted / Active**: `bg: #f0fdf4`, `text: #166534`, `border: #bbf7d0`
- **Evaluation / Pending**: `bg: #fefce8`, `text: #854d0e`, `border: #fef08a`
- **Closed / Rejected**: `bg: #fef2f2`, `text: #991b1b`, `border: #fecaca`

---

## 2. Responsive & Non-Overflow Layout Architecture

1. **Containers**: `max-width: 1280px; margin: 0 auto; padding: 0 1.5rem; width: 100%; box-sizing: border-box;`
2. **Prevent Overflow**:
   - `html, body { max-width: 100vw; overflow-x: hidden; }`
   - `* { box-sizing: border-box; }`
   - Data tables MUST use responsive card wrappers or clean `.table-responsive` horizontal scrolling within card boundaries, never overflowing the page body.
3. **Card Grid Layout**:
   - Use `grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))` for bento box and dashboard widgets.
   - Flexible gap spacing (`gap: 1.25rem to 1.75rem`).

---

## 3. Typography System
- **Font Stack**: `'Plus Jakarta Sans', 'Inter', system-ui, -apple-system, sans-serif`
- **Headings**: Tight tracking (`letter-spacing: -0.025em; font-weight: 700;`)
- **Eyebrows / Badges**: Uppercase wide tracking (`letter-spacing: 0.08em; font-size: 11px; font-weight: 600;`)
