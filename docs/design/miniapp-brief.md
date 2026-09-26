# PayMeLah Mini App — Design Brief

Locked 2026-09-26. Figma: https://www.figma.com/design/F0dWGREVWNNZRuR3V5mwma (team payMeLah, Student tier).

## Product
- Telegram Mini App is the primary UI. Bot text commands keep working. Bot remains the notifier (nudges, "X added expense").
- Group-chat entry: `t.me/payMeLahzBot/app?startapp=<group_id>` → opens that group.
- Private-chat entry: Home — greeting, group cards with *my* net per group (no cross-group total), recent activity, add-expense shortcut, Archived section.
- Navigation: Home is the hub, no tab bar. Telegram BackButton for back, Telegram MainButton for primary action. Profile via avatar on Home.

## Screens (everything the backend supports)
Home · Group home (feed, category chips, payments filter) · Add expense + split editors (equal/exact/percentage/shares) · Expense detail/edit/delete (permission-aware) · Balances (simplified/raw, Nudge, Settle up) · Settle up · Payment detail + undo · Group settings & members (roles, remove, transfer ownership, archive/unarchive, leave/delete, settle-before-leave block) · Create group · Join via invite · Profile · Archived · Empty / all-settled / error states · Currency conversion display.
Out of scope: recurring expenses, quick-add (no backend).

## Visual system
- Theming: hybrid — bg/text/dark mode from Telegram `themeParams`; brand via accent, type, illustration, copy.
- Colour: Mango `#FFB059` (brand fill), `#4A2600` text-on-brand, `#A85A00` orange text on light, tint `#FFF4E6` / dark `#3B2C1A`, dark-mode orange text `#FFB059`. Never `#FFB059` text on white.
  Owed (green) `#16875A` / dark `#62D6A2`. Owe (raspberry) `#C8385A` / dark `#FF8BA0`.
  Telegram reference: light bg `#FFFFFF` / secondary `#F1F1F4`; dark bg `#212121` / secondary `#181818`.
- Type: Bricolage Grotesque (headings, amounts, buttons; tabular numerals). System font (SF Pro / Roboto) for body.
- Icons: Solar — Linear for UI, Bold Duotone for personality moments. CC BY credit on Profile.
- Illustration: Fluent Emoji 3D (MIT) for full-screen states only (🎉 🧾 💸 🙈 — no mango). Crayon/hand-drawn doodle accents (scribbled underlines, doodle stars, wobbly outlines). 3–4 labelled placeholders for a future original crayon-style mascot. No Crayon Shin-chan character or look-alike.
- Tone: playful Gen Z, light Singlish only in empty/success copy. Money figures and button labels stay plain.

## Build notes (2026-09-26)
- Body font in Figma is **Inter** as a stand-in: SF Pro renders zero-width in the Figma plugin runtime. Code uses `-apple-system, "SF Pro Text", Roboto, sans-serif`.
- Colour variables carry WEB code syntax mapped to Telegram CSS vars (`var(--tg-theme-bg-color)` etc.); brand tokens use `--pml-*`.
- Added `tg/link` token (Telegram header "Close/Back" colour, not ours to change).
- Research write-up: `docs/design/research.md`.

## Figma deliverable
Pages: Cover · Research · Foundations · Components · Screens · Flows.
Variables (light/dark modes), text styles, components (group card, expense row, balance chip, member row, amount input, split editor row, buttons).
Screens at 390×844 inside a Telegram header + MainButton mock.
Flows: add expense (with split editor) · settle up · join group · leave blocked → settle → leave.
