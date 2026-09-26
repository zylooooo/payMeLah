# PayMeLah Mini App — UX Research

Compiled 2026-09-26. Informs [miniapp-brief.md](miniapp-brief.md). Sources are cited inline; where a claim comes
from general product familiarity rather than a fetched source it is marked *(obs.)* and should be spot-checked
against live screenshots before it drives a design decision.

---

## 1. App-by-app

### Splitwise (market leader, the reference everyone copies)

**Strengths**
- Group list shows one line per group with *your* net in that group: green "you are owed S$X", orange "you owe S$X",
  grey "settled up" *(obs.)*. The dashboard adds a total across groups ([TapSmart guide](https://www.tapsmart.com/tips-and-tricks/splitwise-guide/)).
- Add-expense is a sentence: **"Paid by [you] and split [equally]"** — each bracket is a tappable chip that opens a
  picker. Tapping a name in the equal split removes them and re-divides ([Splitwise KB](https://kb.splitwise.com/balances-and-expenses/what-are-different-ways-i-can-split-an-expense), [TapSmart](https://www.tapsmart.com/tips-and-tricks/splitwise-guide/)).
- Five split modes (equal / exact / percent / shares / +/- adjustment) as tabs on one screen, with a live
  "S$X of S$Y — S$Z left" footer while entering unequal splits ([Splitwise KB](https://kb.splitwise.com/balances-and-expenses/what-are-different-ways-i-can-split-an-expense)).
- Expense rows: date, category icon, title, "You paid S$X", and on the right a coloured "you lent / you borrowed S$Y" —
  i.e. the row is about *my* effect, not the raw total *(obs.)*.
- "Simplify debts" is explained in plain language with a 3-person example and "never changes anyone's total"
  ([KB: Simplify Debts](https://kb.splitwise.com/balances-and-expenses/what-is-simplify-debts)).
- Leaving/removing is blocked while the balance is non-zero; the help page offers two escapes — record a cash
  payment, or edit them out of expenses ([KB: remove a person](https://kb.splitwise.com/groups/how-do-i-remove-a-person-from-a-group), [feedback KB](https://feedback.splitwise.com/knowledgebase/articles/386282-why-can-t-i-remove-a-group-member-with-a-non-zero)).

**Weaknesses**
- Free tier capped at ~3–5 expenses/day with a ~10 s countdown ad before adding — the #1 complaint in 2025–26 reviews
  ([Medium: bypassing limits](https://medium.com/@prathamarora25.6/how-i-bypass-splitwise-ads-and-limits-and-you-should-too-68b7b84fbae5), [Trustpilot](https://www.trustpilot.com/review/splitwise.com), [Kimola report](https://kimola.com/reports/splitwise-app-feedback-report-uncover-user-insights-google-play-en-144452)).
- Currency conversion, receipt scan, itemised split and charts moved behind Pro (~US$40/yr)
  ([splitty comparison](https://splittyapp.com/learn/splitwise-vs-splid-vs-settleup/)).
- Unequal split modes buried under "More options"; case studies recommend description → payer/amount → split order
  and surfacing quick-add ([Bootcamp case study](https://bootcamp.uxdesign.cc/splitwises-ux-e0afb602582e), [UX Collective](https://uxdesign.cc/splitwise-a-ux-case-study-dc2581971226)).
- Pro upsell buttons feel random and don't preview what you get ([Thinking Crayfish product study](https://thinkingcrayfish.substack.com/p/product-study-splitwise)).
- Simplified balances confuse people: pairwise debts get "reshuffled" and KB tells users to watch only their total;
  toggling simplify off after payments "unravels" paths ([KB](https://kb.splitwise.com/balances-and-expenses/what-is-simplify-debts)).
- Reminders go by **email** and live in different places for groups (Balances) vs friends (overflow menu)
  ([UX Collective](https://uxdesign.cc/splitwise-a-ux-case-study-dc2581971226)).

### Tricount (bunq-owned, EU travel favourite)

**Strengths**
- Two-tab group: **Expenses** | **Balances**. Balances shows each member's net as a horizontal bar (positive one
  colour, negative the other) plus a suggested reimbursements list ([FlightDeck review](https://www.pilotplans.com/blog/tricount-review)) *(bar colours obs.)*.
- One-tap **"Mark as paid"** on a suggested reimbursement records the payment — no separate settle form
  ([Tricount help: payments](https://help.tricount.com/topics/payments)).
- Add-expense "For whom" is a checklist of all members with each person's computed share shown inline, updating as
  you tick/untick *(obs.)*.
- Reviewers repeatedly call it simple, ad-light and unlimited on free ([App Store reviews](https://apps.apple.com/au/app/tricount-split-settle-bills/id349866256?see-all=reviews&platform=iphone), [Lemon8 SG review](https://www.lemon8-app.com/@_jeslynsy_/7398592806777782800?region=sg)).

**Weaknesses**
- Balance screen mixes "balances" and "reimbursements" without clear separation ([Montcoudiol redesign](https://medium.com/@constancemontcoudiol/redesigning-tricount-ios-app-5bb2ec07b974)).
- Users report suggested reimbursements that look "scrambled" (people paying someone who paid nothing) — a
  simplification result with no explanation ([FlightDeck](https://www.pilotplans.com/blog/tricount-review)).
- No search, no recurring, no partial payments, no CSV; regressions after updates (lost default participants,
  stats) ([App Store reviews](https://apps.apple.com/us/app/tricount-split-settle-bills/id349866256?see-all=reviews)).

### Settle Up

**Strengths**
- Add-expense **starts with who paid** — reviewers call it the fastest entry flow ([App Store reviews](https://apps.apple.com/us/app/settle-up-group-expenses/id737534985?see-all=reviews)).
- **Weights** (couple = 2, single = 1) as a first-class split, free ([splitty](https://splittyapp.com/learn/splitwise-vs-splid-vs-settleup/)).
- Min-transfers settlement, multi-currency free, offline with sync, automatic settle reminders
  ([App Store](https://apps.apple.com/us/app/settle-up-group-expenses/id737534985), [Settle Up tips](https://settleup.io/tips)).

**Weaknesses**
- "Not intuitive how to settle up"; too many taps to navigate ([App Store reviews](https://apps.apple.com/us/app/settle-up-group-expenses/id737534985?see-all=reviews)).
- Intrusive ads on free; dated look; feels over-engineered for simple splits (same source).

### Splid

**Strengths**
- Zero-account: create group, type names, share a code; tracking in under two minutes
  ([WhistleOut](https://www.whistleout.com/CellPhones/Apps/splid-app-for-splitting-group-expenses)).
- Single orange **+** for add; form is just amount → who paid → how to split (same source).
- Late joiners aren't charged for earlier expenses (same source).
- Settle screen lists minimal transfers; members **tick them off** as they pay (same source).
- Offline-first, 150+ currencies free, no ads; 4.9★ ([App Store](https://apps.apple.com/us/app/splid-split-group-bills/id991473495)).

**Weaknesses**
- Monetises via one-time unlocks (extra groups, Excel export) — fine, but a group cap is a surprise wall
  ([App Store](https://apps.apple.com/us/app/splid-split-group-bills/id991473495)).
- No web/tablet version (same source).

### Spliit (open source — closest technical sibling)

**Strengths**
- Next.js + shadcn/ui + Postgres/Prisma; MIT — a readable reference implementation ([GitHub](https://github.com/spliit-app/spliit)).
- Split modes labelled **"Evenly" / "Unevenly – By shares" / "– By percentage" / "– By amount"**, with inline validation
  stating what the amounts/percentages currently add up to vs the target ([en-US messages](https://raw.githubusercontent.com/spliit-app/spliit/main/messages/en-US.json)).
- "Save as default splitting options" per group (same source).
- **"Who are you?"** prompt so a shared link can personalise the view (same source) — PayMeLah gets this free from Telegram `initData`.
- Balances page = totals per person + reimbursement list ("A owes B", **Mark as paid**); settled empty state is a
  positive sentence, not a blank ([spliit.app](https://spliit.app), messages).
- Tagline "No ads. No account. No limitation." — positioning directly against Splitwise ([spliit.app](https://spliit.app)).

**Weaknesses**
- Anyone with the URL can view *and edit* — no roles, no audit of who changed what (warned in its own share copy).
- Web-generic look; no native mobile affordances (bottom action button, haptics).

### Revolut / Monzo (bank-side pattern references)

- Revolut: split is **attached to a transaction** — swipe/tap a card payment → "Split bill" → pick contacts; even split
  by default, amounts editable; the request appears in the payee's feed with Accept/Decline
  ([TechCrunch](https://techcrunch.com/2017/01/17/revolut-lets-you-split-bills-in-a-few-taps/), [Revolut help](https://help.revolut.com/en-US/help/adding-money/with-money-from-friends-or-relatives/splitting-bill/)).
- Revolut split is even-or-exact only, no by-item ([splitty](https://splittyapp.com/learn/revolut-bill-splitting/)).
- Monzo Split: **Single Split** vs **Running Split** (trip/household), guests join by link without an account,
  partial payments, **automatic reminders** ([Monzo Split](https://monzo.com/features/monzo-split), [Monzo help](https://monzo.com/help/monzo-with-friends/SplitandPaytheMonzowaywithSharedTabs)).
- Takeaway: a request lives **in the other person's feed** as an actionable item, not only as a number on a
  balances page. Telegram's chat is PayMeLah's equivalent feed.

### Telegram Wallet (native-feel reference)

- Big centred balance, a row of round action buttons, then a plain list — uses Telegram's own list-row/section
  styling so it reads as part of Telegram *(obs.)*.
- Third-party guidance: mirror Wallet's terminology and confirmation layouts for trust; ignoring the Telegram theme
  "feels foreign" ([turumburum](https://turumburum.com/blog/telegram-mini-app-beyond-the-standard-ui-designing-a-truly-native-experience), [Merge guide](https://merge.rocks/blog/how-to-build-a-telegram-mini-app-your-telegram-mini-apps-guide)).
- Community component library that copies Telegram's look: [TelegramUI](https://github.com/telegram-mini-apps-dev/TelegramUI) and its [Figma kit](https://www.figma.com/community/file/1348989725141777736/telegram-mini-apps-ui-kit).

---

## 2. Telegram Mini App guidelines (from [core.telegram.org/bots/webapps](https://core.telegram.org/bots/webapps))

**Official design rules (summarised)**
- Mobile-first and responsive; interactive elements should mimic existing Telegram components in style, behaviour
  and intent; animations smooth (~60 fps); all inputs and images labelled for accessibility.
- Follow the user's colour theme live; respect **safe area** and **content safe area** (esp. fullscreen).
- On Android, read the performance class from the User-Agent and cut animation on low-end devices.

**Theming — `themeParams` → CSS vars `--tg-theme-*`**
`bg_color`, `secondary_bg_color`, `section_bg_color`, `section_header_text_color`, `section_separator_color`,
`text_color`, `hint_color`, `subtitle_text_color`, `link_color`, `accent_text_color`, `destructive_text_color`,
`button_color`, `button_text_color`, `header_bg_color`, `bottom_bar_bg_color`. Listen to `themeChanged`.
`setHeaderColor` / `setBackgroundColor` / `setBottomBarColor` accept hex or a theme key.

**Native controls**
- **MainButton** / **SecondaryButton** (BottomButton): `setText`, `show/hide`, `enable/disable`,
  `showProgress/hideProgress`, `color`, `textColor`, `hasShineEffect` (7.10+); secondary has `position`
  (left/right/top/bottom). Events `mainButtonClicked`, `secondaryButtonClicked`.
- **BackButton**: `show/hide`, `onClick` — replaces any in-page back arrow.
- **SettingsButton**: entry in the ⋮ menu — natural home for Profile/settings.
- **Popups**: `showPopup` (up to 3 buttons, `destructive` type), `showConfirm`, `showAlert`.
- **HapticFeedback**: `impactOccurred(light|medium|heavy|rigid|soft)`, `notificationOccurred(success|warning|error)`,
  `selectionChanged()`.
- `enableClosingConfirmation()` for dirty forms; `disableVerticalSwipes()` so scroll/drag doesn't close the app.

**Viewport & safe areas**
- `expand()`; `viewportHeight` vs `viewportStableHeight` (use the *stable* one for bottom-pinned layout, since the
  live value changes mid-drag) — CSS `--tg-viewport-height`, `--tg-viewport-stable-height`.
- Bot API 8.0+: `requestFullscreen()`, `safeAreaInset` / `contentSafeAreaInset` →
  `--tg-safe-area-inset-{top,bottom,left,right}`, `--tg-content-safe-area-inset-*`; events `safeAreaChanged`,
  `contentSafeAreaChanged`, `fullscreenChanged`. Gate with `isVersionAtLeast()`.

**Data, deep links, sharing**
- `initData` must be HMAC-validated server-side (key `"WebAppData"` + bot token) — never trust `initDataUnsafe`.
- `t.me/<bot>/<app>?startapp=<value>` → `start_param` / `tgWebAppStartParam` (our `startapp=<group_id>` entry).
- `openTelegramLink` (stay in Telegram), `switchInlineQuery`, `shareMessage` (share a prepared message to a chat).
- `CloudStorage` (1024 keys/user) for tiny prefs such as last-used split mode; `DeviceStorage` / `SecureStorage` exist
  but aren't needed.

**What feels native vs web-like** ([turumburum](https://turumburum.com/blog/telegram-mini-app-beyond-the-standard-ui-designing-a-truly-native-experience), [BAZU](https://bazucompany.com/blog/best-practices-for-ui-ux-in-telegram-mini-apps/))
- Native: one MainButton per screen for the primary action (with progress spinner while saving); BackButton;
  `showConfirm` for destructive actions; haptic on success/error; theme-matched background from the first frame;
  inset-grouped list sections like Telegram Settings; skeletons, and `ready()` called early.
- Web-like (avoid): hamburger menus, custom top app bars, floating "+" FABs that duplicate the MainButton, pure white
  flash in dark mode, px-fixed fonts, horizontal carousels near the iOS back-swipe edge, custom modal dialogs for confirmations.

---

## 3. Patterns we adopt

| Screen | Pattern | Source app | Why |
|---|---|---|---|
| Home | One card per group showing **my** net in that group: "you're owed S$X" (green) / "you owe S$X" (raspberry) / "all settled" (hint colour) | Splitwise | Instantly answers "do I need to do anything?"; matches our per-group-only rule (no cross-group total) |
| Home | Colour is never the only signal — prefix/wording ("owe" vs "owed") + icon | Accessibility (TG guideline: labelled inputs) | Red/green and orange/green are colour-blind-hostile |
| Home | Archived groups collapsed in a section at the bottom | Splitwise (hidden groups) | Keeps list short without deleting history |
| Group home | Feed where each expense row shows *my effect* ("you lent S$12" / "you borrowed S$8" / "not involved") with total as secondary text | Splitwise | Users care about their delta, not the bill total |
| Group home | Payments visually distinct from expenses: different icon (💸/arrow), "A paid B S$X" sentence, no category, muted row | Splitwise, Spliit | Prevents payments being mistaken for spending; supports our payments filter |
| Group home | Two top-level views: **Activity** and **Balances** (segmented control, not a tab bar) | Tricount, Spliit | Simplest mental model; Tricount's reviews show users don't need more |
| Add expense | Field order: amount (big, auto-focused, numeric keypad) → description → paid by → split | Splid, Splitwise case studies | Amount is the thing you're holding (the receipt); description can be auto-categorised |
| Add expense | Summary sentence **"Paid by [you] · split [equally] between [5 people]"** with tappable chips | Splitwise | Default path is one screen and one MainButton tap |
| Add expense | Payer defaults to me; participants default to everyone (or last-used set) | Splitwise, Spliit (save default split) | Most expenses are "I paid, everyone shares" |
| Add expense | Currency chip beside amount, defaulting to group currency; converted SGD equivalent shown under the amount | Splid / Settle Up (free multi-currency) | Our currency support is a free differentiator vs Splitwise Pro |
| Split editor | Segmented control Equal / Exact / % / Shares; member checklist with each person's computed share inline | Tricount (checklist), Splitwise (modes) | See the result of every tap; no hidden "More options" |
| Split editor | Sticky footer "S$X of S$Y assigned · S$Z left" (turns destructive colour when over), MainButton disabled until it balances | Splitwise, Spliit validation copy | Validation is visible *before* submit, not an error after |
| Split editor | Shares mode with steppers (−/+) — covers "couple = 2" | Settle Up weights | Common real-world case without percent maths |
| Balances | Simplified list of "A → B S$X" transfers first, with a one-line explainer and a toggle to raw pairwise | Splitwise KB explainer, Tricount | Simplified is the actionable view; the explainer defuses "why do I owe someone I never paid?" |
| Balances | Per-member net bars (green positive / raspberry negative) above the transfer list, clearly separated headers | Tricount (+ its critique) | Visual overview, but keep "balances" and "suggested payments" as separate sections |
| Balances | Rows where **I** am involved pinned to top and highlighted | Splitwise dashboard focus | Most viewers only care about their own lines |
| Settle up | "Mark as paid" on a suggested transfer pre-fills the settle form (amount editable for partial) → MainButton "Record S$X payment" | Tricount, Spliit, Monzo (partial) | One tap from seeing a debt to clearing it |
| Settle up | Success: `notificationOccurred('success')` + 🎉 full-screen state if the group is now all settled | Telegram HapticFeedback | Closure moment; native feel |
| Nudge | Nudge sends via the bot to Telegram DM (group fallback), showing cooldown ("nudged 3h ago") on the button | Monzo reminders, Splitwise remind | Reminder lands where the friend already is — not email |
| Members | Leave/remove blocked with non-zero balance; the block sheet shows the amount and offers **Settle up** directly | Splitwise KB | Guard + escape hatch in one place (our `assert_settled`) |
| Members | Roles shown as small badges (Owner/Admin) on member rows; actions via `showPopup` | Telegram popups | Native, destructive-styled confirmation |
| Join | Invite deep link `startapp=<group_id>`; identity from Telegram — no "Who are you?" step | Spliit (inverse), Splid codes | Telegram gives us identity for free — zero-account like Splid, but with real users |
| Empty states | Positive sentence + single action: "No expenses yet — add the first one" / "All settled lah 🎉" | Spliit copy, brief tone | Empty is an invitation; Singlish only here, per brief |
| Global | MainButton = the one primary action per screen, `showProgress()` while saving; BackButton for navigation; `showConfirm` for delete | TG guidelines, Wallet | Feels native; prevents double submits |
| Global | Theme from `themeParams`, brand only via accent (Mango); `setHeaderColor('bg_color')` | TG guidelines, Wallet | No white flash in dark mode; trust |
| Global | `enableClosingConfirmation()` only while a form is dirty; `disableVerticalSwipes()` on screens with long scroll/drag | TG API | Avoids losing a half-typed expense |
| Global | No limits, no ads, no paywall messaging anywhere | Spliit, Splid positioning vs Splitwise | Biggest competitor pain point = our free win |

---

## 4. Pitfalls to avoid

1. **Rate-limiting or delaying expense entry.** Splitwise's 3–5/day cap and 10 s countdown are the most-cited reason people
   leave ([Medium](https://medium.com/@prathamarora25.6/how-i-bypass-splitwise-ads-and-limits-and-you-should-too-68b7b84fbae5), [Trustpilot](https://www.trustpilot.com/review/splitwise.com)). Trips are logged in bursts at the end — batch entry must be fast.
2. **Hiding split modes behind "More options".** Case studies flag it as the main add-expense friction
   ([Bootcamp](https://bootcamp.uxdesign.cc/splitwises-ux-e0afb602582e)). Keep all four modes one tap away.
3. **Validation only on submit.** Show the running "left to assign" at all times; disable the MainButton, don't throw an error after.
4. **Unexplained simplification.** Tricount users read simplified transfers as a bug ([FlightDeck](https://www.pilotplans.com/blog/tricount-review)).
   Always label "Simplified — fewest payments, same totals" and let the user flip to raw.
5. **Toggling simplify silently re-routing debts after payments** ([Splitwise KB](https://kb.splitwise.com/balances-and-expenses/what-is-simplify-debts)). Make the toggle a *view*
   choice where possible, and warn if it's a group setting change.
6. **Mixing balances and reimbursements in one undifferentiated list** ([Montcoudiol](https://medium.com/@constancemontcoudiol/redesigning-tricount-ios-app-5bb2ec07b974)). Separate sections and headers.
7. **Payments that look like expenses** in the feed — inflates perceived spend. Distinct row style + filter.
8. **Dead-end blocks.** "You can't leave" with no next step. Every guard shows the amount and a Settle up button.
9. **Reminders through a channel people ignore** (Splitwise email). Use Telegram DM; show cooldown state so nudging
   doesn't feel spammy.
10. **Web chrome inside Telegram:** custom header bars, hamburger menus, in-page back arrows, floating FABs duplicating the
    MainButton, custom modal confirms ([turumburum](https://turumburum.com/blog/telegram-mini-app-beyond-the-standard-ui-designing-a-truly-native-experience)).
11. **Ignoring theme / white flash** on open in dark mode; set header/background colours before first paint and call `ready()` early.
12. **Using `viewportHeight` for bottom-pinned UI** — it jitters during drag; use `viewportStableHeight` and safe-area vars.
13. **Trusting `initDataUnsafe`** for identity or permissions — validate `initData` server-side every request.
14. **Colour-only owe/owed signalling** — red/green is unreadable for many users; always pair with words ("owe"/"owed") and sign.
15. **Over-engineering** (Settle Up's "too many clicks", Splitwise's itemisation split into a separate app). Ship the four split
    modes well before adding adjustments, itemisation or receipt scan.
16. **Regressions of learned defaults** (Tricount lost default participants → angry reviews). Persist last-used payer/split per group.
17. **Link-equals-edit-access** (Spliit). We have roles — keep permission-aware edit/delete visible (disabled with reason, not hidden).
