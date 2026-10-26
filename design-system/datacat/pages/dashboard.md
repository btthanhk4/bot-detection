# Dashboard Page Overrides

> **PROJECT:** DATACAT
> **Generated:** 2026-10-26 (ui-ux-pro-max `--design-system --density 8`, then reviewed)
> **Page Type:** Admin dashboard / data view (`api_service/dashboard.html`, `api_service/login.html`)

> Rules in this file **override** `../MASTER.md`. Only deviations are listed.

---

## Why the overrides

The generated Master is a sound base (dark OLED style, slate palette, green accent, Fira
type, dense spacing) but four parts do not fit this page:

| Master says | Problem | Override |
|---|---|---|
| Page pattern "Real-Time / Operations Landing" (hero, how it works, CTA) | Landing-page structure; this is a signed-in console | Keep the existing app shell: sidebar, topbar, views |
| Dark only, light "not recommended" | Admins use it in daylight and project it in thesis reviews | Ship light **and** dark, follow the OS, manual toggle |
| `.btn-primary` `#16A34A` with white text | 3.3:1, fails its own 4.5:1 rule | Light `#15803D` + white (5.0:1); dark `#22C55E` + `#052E16` (6.5:1) |
| Cards `cursor:pointer` + hover lift; white modal | Cards are not clickable; white modal in dark mode | No pointer/lift on static cards; drawer uses card surface tokens |

---

## Color tokens (existing variable names, values per theme)

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg-primary` | `#F1F5F9` | `#020617` | Page background |
| `--bg-secondary` | `#F8FAFC` | `#1A1E2F` | Muted surface: table head, hover, code |
| `--bg-card` | `#FFFFFF` | `#0E1223` | Cards, panels, drawer |
| `--bg-card-hover` | `#F8FAFC` | `#151A2E` | Row/card hover |
| `--text-primary` | `#0F172A` | `#F8FAFC` | Body text (17.8:1) |
| `--text-secondary` | `#334155` | `#CBD5E1` | Secondary text (≥10:1) |
| `--text-muted` | `#475569` | `#94A3B8` | Labels, hints (≥6.4:1 on muted surfaces) |
| `--line` / `--border-subtle` | `#E2E8F0` | `#1E293B` / `#334155` | Dividers (decorative) |
| `--border-strong` | `#8592A6` | `#64748B` | Input and control boundaries (≥3:1) |
| `--brand` | `#15803D` | `#22C55E` | Accent / CTA / active nav |
| `--on-brand` | `#FFFFFF` | `#052E16` | Text on brand |
| `--ring` | `#15803D` | `#4ADE80` | Focus ring |
| `--accent-green` (human) | `#16A34A` | `#22C55E` | Fills; text uses `--success-text` `#15803D` / `#4ADE80` |
| `--accent-red` (bot) | `#DC2626` | `#EF4444` | Fills; text `#B91C1C` / `#F87171` |
| `--accent-orange` (suspect) | `#D97706` | `#F59E0B` | Fills; text `#B45309` / `#FBBF24` |
| `--accent-blue` (info) | `#0284C7` | `#38BDF8` | Fills; text `#0369A1` / `#38BDF8` |
| `--nav-bg` | `#0F172A` | `#070B19` | Sidebar stays dark in both themes |

Tints use `color-mix(in srgb, <token> N%, transparent)` instead of fixed `rgba()`.
Charts and the trajectory canvas read these tokens at draw time and redraw on theme change.

## Typography

Fira Sans (UI, supports Vietnamese) + Fira Code (numbers, IDs, IPs, clock). Base 14px for the
dense desktop view; form inputs 16px below 540px to avoid mobile zoom. Tabular numerals on KPIs.

## Shape, depth, motion

Radius 10px cards / 6px controls. Light: `--shadow-sm` on cards, `--shadow-lg` on menus.
Dark: borders instead of shadows. Transitions 150–200ms on color/background only; no
layout-shifting hover. `prefers-reduced-motion` disables animation.

## Accessibility rules applied

- Visible `:focus-visible` ring (2px `--ring`, 2px offset) on every interactive element.
- Status is never color-only: verdict badges keep text labels; charts keep legend and tooltips,
  and the session table is the data alternative.
- Theme toggle is a real `<button>` with `aria-pressed` and a Vietnamese label.
