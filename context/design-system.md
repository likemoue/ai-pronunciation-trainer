# Design system: AI Pronunciation Trainer

> **Approved by the user on 2026-11-16**, together with the wireframes in `design/wireframes/` (start at
> `index.html`). Nothing in `static/` follows it yet: phase 4 applies it.
>
> Decisions taken with it (2026-11-16): **Q1** the page follows the server's thresholds (§3), no scoring change;
> **Q2** marks only on Almost and Needs-work words (§2.10); **Q3** the typical-mistake hint is part of phase 4
> (§2.13); **Q4** Correct is teal-green `#0f766e`, with red `#b91c1c` for Needs work (§1.3).

- **Source of truth:** `static/css/style.css` (the `:root` tokens and the `prefers-color-scheme: dark` block). When
  this file and the CSS disagree, trust the CSS and fix this file. Phase 4 adds the new tokens to the CSS before any
  component uses them.
- **Look:** today's page, codified: Inter, an indigo primary, rounded cards, soft shadows, light and dark themes. No
  design generator was used. What changes: AA contrast everywhere, a status palette that survives colour blindness,
  and no signal carried by colour alone.
- **Stack:** Flask + one Jinja template (`templates/main.html`), vanilla JS (`static/javascript/app.js`), one
  stylesheet. No Tailwind, no component library, no icon font: icons are the inline SVG sprite in `main.html`
  (`fill: currentColor`).

## 1. Tokens

### 1.1 Base colours

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--bg` | `#f4f5fb` | `#0e1020` | page background |
| `--surface` | `#ffffff` | `#171a2e` | cards, sheets, dialogs, the bottom bar |
| `--surface-2` | `#f7f8fc` | `#1d2138` | sentence block, cells of the word detail, waveform, ring track |
| `--border` | `#e3e6f0` | `#2a2f4a` | card edges and dividers (decoration only) |
| `--border-strong` **new** | `#868ca4` | `#666d8f` | edges that identify a control: text field, toggle, unselected chip (3:1) |
| `--text` | `#161a2e` | `#eef0fb` | main text |
| `--text-2` | `#4b5167` | `#b7bcd6` | secondary text, IPA, chip and bar labels |
| `--text-3` | `#646b85` (was `#7c829a`) | `#8a90ad` | hints, eyebrows, counters, disabled labels |
| `--primary` | `#4f46e5` | `#818cf8` | primary buttons, selected chip, links |
| `--primary-2` | `#6366f1` | `#a5b4fc` | second stop of the mic and brand-mark gradient only |
| `--primary-hover` **new** | `#4338ca` | `#a5b4fc` | hover of primary buttons (today's hover, `--primary-2`, gives white text 4.47:1) |
| `--primary-soft` | `#eef0ff` | `#252a4d` | selected word, toggle on, hover backgrounds, info notices |
| `--on-primary` | `#ffffff` | `#0e1020` | text and icons on `--primary` |
| `--rec` | `#e11d48` | `#fb7185` | live dot, "REC", the Stop button |
| `--on-rec` **new** | `#ffffff` | `#0e1020` | text on the Stop button (white on dark-mode `--rec` is 2.69:1) |
| `--focus` **new** | `#4f46e5` | `#a5b4fc` | focus outline, solid (today 55% primary over white: 2.54:1) |
| `--scrim` | `rgba(10, 12, 28, .55)` | same | backdrop behind sheets and dialogs |
| `--dim` **new** | `rgba(10, 12, 28, .62)` | same | the tour's dimmed page |

### 1.2 AA fixes, measured

WCAG 2.x contrast; text needs 4.5:1 at every size (one rule, no large-text exception), non-text 3:1.

| What | Today | Ratio | Proposed | Ratio |
|---|---|---|---|---|
| Hint text (`--text-3`) on surface / surface-2 / bg | `#7c829a` | 3.81 / 3.59 / 3.50 | `#646b85` | 5.27 / 4.97 / 4.84 |
| Warning text (`--ok`) on surface | `#d97706` | 3.19 | `#b45309` | 5.02 |
| Correct letters (`--good`) on surface-2 | `#12a150` | 3.17 | `#0f766e` | 5.16 |
| Wrong letters (`--bad`) on surface-2 | `#dc2626` | 4.55 | `#b91c1c` | 6.10 |
| Correct badge (good on good-soft `#e3f7ec`) | `#12a150` | 3.01 | `#0f766e` | 4.90 |
| Almost badge (on ok-soft `#fdf1dc`) | `#d97706` | 2.85 | `--ok-strong` `#92400e` | 6.34 |
| Needs-work badge (on bad-soft `#fde6e6`) | `#dc2626` | 4.06 | `#b91c1c` | 5.43 |
| Primary button hover (white on) | `#6366f1` | 4.47 | `#4338ca` | 7.90 |
| Dark-mode Stop button (text on `#fb7185`) | white | 2.69 | `#0e1020` | 7.01 |
| Focus outline against surface (non-text) | 55% primary | 2.54 | solid `#4f46e5` / dark `#a5b4fc` | 6.29 / 8.61 |
| Text-field edge against surface (non-text) | `#e3e6f0` | 1.25 | `#868ca4` / dark `#666d8f` | 3.33 / 3.39 |

Everything else already passes: in light mode `--text` 17.19, `--text-2` 7.86, white on `--primary` 6.29, white on
`--rec` 4.70; in dark mode `--text-3` 5.45 on surface, `--good` 8.50, `--bad` 5.72, `--ok` 9.48 on surface-2, the
three badges 7.19 / 7.96 / 5.57. One dark-mode pair fails and is banned instead: `--text-3` on `--primary-soft`
(4.40); use `--text-2` there (7.37).

### 1.3 Status palette: feedback on words and letters

Only these colours mean a status. A new status gets a row here before any component uses it.

| Status (API code) | Mark | EN | VI | Text, light | Soft bg, light | Text, dark | Soft bg, dark | Cue without colour |
|---|---|---|---|---|---|---|---|---|
| Correct (`0`) | ✓ | Correct | Đúng | `--good` `#0f766e` | `--good-soft` `#e3f7ec` | `#2dd4bf` | `#12352a` | no mark in the sentence (Q2); ✓ in badge, legend, accessible name |
| Almost (`1`) | ~ | Almost | Gần đúng | `--ok` `#b45309`; on soft bg `--ok-strong` `#92400e` | `--ok-soft` `#fdf1dc` | `#fbbf24` | `#3a2e12` | boxed ~ after the word |
| Needs work (`2`) | ✗ | Needs work | Cần luyện | `--bad` `#b91c1c` | `--bad-soft` `#fde6e6` | `#f87171` | `#3d1a1d` | boxed ✗ after the word |
| Wrong letter (`is_letter_correct` 0) | | | | `--bad` | | `--bad` | | weight 700 + 2 px dotted underline |
| Recording | ● | Recording | Đang ghi âm | `--rec` | | `--rec` | | "REC" next to the dot; the timer runs |

Why these hues: red-green colour blindness (4-8% of boys, so about one learner per class) turns today's green and
red letters into two olive tones. Moving Correct from green to teal-green keeps its meaning for everyone else and
adds blue, which protans and deutans still see. CIEDE2000 between Correct and wrong letters (normal / protanopia /
deuteranopia / tritanopia; Machado 2009 simulation at full severity; about 2 is just visible, 30 and more is clear):

| Pair | Today | Proposed |
|---|---|---|
| Correct / wrong letter, light | 71.8 / 23.0 / **9.0** / 65.0 | 54.4 / 22.1 / **29.7** / 56.9 |
| Correct / wrong letter, dark | 68.5 / 17.6 / **9.9** / 69.0 | 63.4 / 19.2 / **24.9** / 68.3 |
| Almost / Needs work, light | 24.8 / 18.4 / 9.5 / 11.7 | 16.2 / 10.9 / 5.8 / 8.2 |

Almost and Needs work stay close for deutans in every amber/red pair that keeps the usual meanings; they are told
apart by their mark (~ or ✗), never by colour. Q4 chose teal-green; the stronger alternative, blue `#1d4ed8` for
Correct (deuteranopia 60.9 against `#b91c1c`), was turned down because "blue = correct" is unusual for children.

Notices reuse the families: warning (in-app browser, offline, cannot record) = `--ok-soft` background, `--ok-strong`
icon, `--text` text (15.39:1); error = `--bad-soft` + `--bad` icon (14.44:1); info = `--primary-soft` + `--primary`
icon; success (link copied, progress deleted) = `--good-soft` + `--good` icon.

### 1.4 Alpha tokens: the end of `color-mix()`

`style.css` has 13 `color-mix()` declarations. Each is replaced by a precomputed token, one value per theme:

| Token | Light | Dark | Replaces |
|---|---|---|---|
| `--primary-glow` | `rgba(79, 70, 229, .35)` | `rgba(129, 140, 248, .35)` | shadows of the brand mark, the mic and primary buttons; the mic's pulse ring (5 uses) |
| `--primary-tint` | `rgba(79, 70, 229, .18)` | `rgba(129, 140, 248, .24)` | spinner track, text-field halo if one is kept (2 uses) |
| `--rec-glow` | `rgba(225, 29, 72, .35)` | `rgba(251, 113, 133, .35)` | Stop button shadow (1 use) |
| `--surface-veil` | `rgba(255, 255, 255, .86)` | `rgba(23, 26, 46, .86)` | waveform overlay while checking (1 use) |
| `--focus` (solid, §1.1) | | | the two focus outlines (2 uses) |
| none | | | the three word-underline colours: the marks of §2.10 replace them (3 uses) |

### 1.5 Type

- **Fonts:** Inter 400-700 for the interface, Noto Sans 400-500 for IPA, both served by the app (OFL).
  **Add Inter's Vietnamese subset** (U+0102-0103, U+0110-0111, U+0128-0129, U+0168-0169, U+01A0-01A1,
  U+01AF-01B0, U+0300-0301, U+0303-0304, U+0308-0309, U+0323, U+0329, U+1EA0-1EF9, U+20AB; about 10 KB): today's
  two Inter files skip U+1EA0-1EF1, so "ạ ố ữ" would come from another font. `tests/test_static.py` counts 5 font
  files; it becomes 6.
- **Sizes (px), only these:** 12 caption (eyebrow, badge, legend, bar labels) · 13 small (counter, notes) · 14
  secondary (hint, chip, notice) · 16 body, buttons, inputs, IPA · 18 titles (sheet, result, detail word; the score
  in the phone ring; a sentence over 20 words on phones) · 22 the sentence on phones · 28 the sentence on desktop,
  the score in the desktop ring. Today's 11, 15, 19, 20 and 30 go.
- **Weights:** 400 body · 500 the sentence after a result · 600 the sentence, labels · 700 titles, buttons, wrong
  letters. The served Inter stops at 700.
- **Line height:** 1.5 body, 1.45 the sentence; text never sits in a fixed-height box.
- **Numbers:** `font-variant-numeric: tabular-nums` for scores, timers and counters.
- Inputs are at least 16 px (iOS zooms below that).

### 1.6 Spacing

A 4 px scale: 4, 8, 12, 16, 20, 24, 32, 40, 48. Today's off-scale values move to the nearest step (6 → 4 or 8,
10 → 8 or 12, 14 → 12 or 16, 18 → 16 or 20, 22 → 20 or 24, 26 → 24). Borders (1-2 px) and the 3 px focus outline
are not spacing.

### 1.7 Radii

| Token | Value | Used for |
|---|---|---|
| `--radius` | 18 | cards (sentence, result, How it works) |
| `--radius-sheet` **new** | 22 | top corners of bottom sheets; all corners of dialogs |
| `--radius-sm` | 12 | blocks inside cards, buttons, text fields, waveform (was 16), brand mark (was 14) |
| `--radius-xs` **new** | 8 | word-detail cells (were 10), `kbd` (was 6) |
| pill (`999px`) | | chips, badges, round buttons, the EN \| VI control, toggles |

### 1.8 Shadows and layers

- `--shadow` cards; `--shadow-lg` sheets and dialogs; `--shadow-bar` **new** for the bottom bar:
  `0 -4px 16px rgba(22, 26, 46, .08)` (dark: `rgba(0, 0, 0, .4)`); glows only through the alpha tokens. One shadow per
  element; none on disabled controls.
- z-index: 20 bottom bar · 21 notice docked above the bar · 49 backdrop · 50 sheet or dialog · 60 tour · 70 a
  confirmation over a sheet.

### 1.9 Motion

- State changes 200 ms or less (fades, the sheet sliding in).
- Longer motion is decoration and stops under `prefers-reduced-motion`: the ring filling (900 ms), the score counting
  up (800 ms, in JS: check `matchMedia`), the mic's idle pulse (2.4 s, also paused while a sheet is open), the live dot
  (1.2 s). No motion carries information on its own.

### 1.10 Layout

- **Below 768 px:** one column; the bottom bar is fixed; popups are bottom sheets.
- **From 768 px:** inline controls under the sentence; popups are centred dialogs (560 px).
- **From 1024 px:** two columns, sentence and controls (640 px) | result (the rest), content at most 1120 px wide.
- When the viewport is under 480 px tall (a phone held sideways), the bar stops being fixed.
- The meta viewport gets `viewport-fit=cover`; the bar's bottom padding is `max(8px, env(safe-area-inset-bottom))`.
- Check every screen at 320, 360, 390, 768 and 1280 px wide; 560 (inside Zalo) and 640 px tall.

## 2. Component rules

1. **Buttons.** At least 44 px tall, radius 12, 16 px / 700, icon + label. *Primary* (filled `--primary`): one per
   region (the mic is the page's; a sheet has one). *Secondary* (`--surface`, 1 px `--border-strong`). *Text*
   (underlined): low-emphasis actions such as Not now, Done in the tour, New learner. *Destructive*: secondary look +
   trash icon + 2 px border, only inside a confirmation, never focused by default. Labels never wrap inside a button:
   when two do not fit side by side, they stack, and the primary gets the larger share (1.6 : 1).
2. **Disabled.** When the learner should learn why (the mic in a browser that cannot record, Next while offline), use
   `aria-disabled="true"`: the control stays focusable and points to the notice that explains. Native `disabled` only
   for a form's submit while the field is empty. Look: dashed `--border-strong` edge, `--text-3` label, no shadow; text
   is never faded with `opacity`.
3. **Round buttons** (Listen, Next): 48 px on phones, 56 px on desktop, `--surface` with `--border-strong`, label
   underneath (12-13 px / 600). Pressed (playing) = filled `--primary`, Stop icon, label "Stop", `aria-pressed="true"`.
4. **Mic.** 64 px on phones, 88 px on desktop, the primary gradient with `--primary-glow`. Labels: "Tap to speak",
   "Try again" after a result, "Can't record" (mic-off icon, `aria-disabled`). Its accessible name is its label.
5. **Level chips.** A radio group (arrow keys move and choose, roving `tabindex`), pills 36 px with a 44 px hit area,
   14 px / 600. Selected = filled `--primary`. Never disabled while a sentence loads: the latest choice cancels the
   request in flight. Order: Easy, Medium, Hard, Random.
6. **EN | VI.** Two buttons with `aria-pressed`, 37 × 36 px each, 44 px hit area; the choice is remembered (§5).
7. **Bottom bar** (phones). Fixed; columns 1fr 1.3fr 1fr; exactly Listen · Mic · Next; labels follow the state.
   The page reserves its height (`padding-bottom`), and `html { scroll-padding-bottom }` keeps a focused element
   above it.
8. **Bottom sheet / dialog.** Parts: a fixed header (state icon or live dot, the title as a heading with
   `tabindex="-1"`, optional timer, close 44 px), a scrolling body, fixed actions above the safe area. Max height
   `100dvh` on phones and `100dvh - 64px` for dialogs, each after a `100vh` fallback. Escape closes (same as Cancel).
   The **recording sheet ignores backdrop taps in every state**; other sheets close on a backdrop tap only when
   nothing is lost (the My text draft is kept). The page behind is `inert`; no sheet opens another sheet: a
   confirmation is an `alertdialog` on top.
9. **Notices, not toasts.** Icon + title + text (+ actions), radius 12, the families of §1.3. They stay until the
   situation changes or the learner acts; the "Link copied" success reverts after 4 s but never disappears. A notice
   about the controls docks above the bar (phones) or above the inline controls (desktop); one about the sentence sits
   in the card. One docked notice at a time: cannot record > offline > no sample voice. `role="status"`, or
   `role="alert"` when it blocks.
10. **Words and letters after a result.** Each word is an inline button (2 px side padding, radius 6, at least 24 px
    tall). Letters heard as written: `--good`, weight 500. Wrong letters: `--bad`, weight 700, 2 px dotted underline
    4 px below (as longhands: `text-decoration-line`, `-style`, `-thickness`, `text-underline-offset`). Almost and
    Needs-work words end with a boxed mark, ~ or ✗ (11 px / 700, 1.5 px border in the status colour, radius 4),
    placed before trailing punctuation and raised so the line height never changes. No line break between a word and
    its mark: the word, its mark and any trailing punctuation sit in one `white-space: nowrap` group. Correct words
    carry no mark (Q2). Selected word: `--primary-soft` background. Accessible name: "books, Almost, show details".
11. **Badges.** Pill, 12 px / 700, mark + text on the soft background (`--ok-strong` text for Almost). Never a dot
    alone.
12. **Score ring.** 68 px (phones) / 96 px (desktop); `--surface-2` track, arc in the tier colour (§3); the number in
    `--text`. The title and the meaning line beside it say the same thing in words.
13. **Result card.** In this order: ring + title + meaning line; a "done" line (nothing to practise) or "Words to
    practise" (at most 4 chips, ✗ first, then by score, one chip per word, "+N more"); the selected word's detail
    (Correct IPA + Listen | Heard IPA + Replay; a word not heard says *not heard* and Replay is disabled); My
    recording; "Heard: “…”" (3 lines, then more); the legend; on desktop, Try again + Next sentence. The worst word's
    detail opens by itself. **Typical-mistake hint (Q3):** when the server names the mistake of an Almost word
    (`WordMatching.known_mistake`: `ending`, `th`, `sh`, in a new per-word field of the scoring response, added by the
    backend first), the word's detail shows one hint line in the interface language, with Listen buttons for the word
    as written and the word heard (wireframes page 3, C3/C4, and its copy table). One hint at a time; scores and labels
    do not change.
14. **In-app browser banner.** First thing on the page, in the flow, warning family, persistent and dismissible
    (✕, or "Not now" when the top right is kept for the pointer to the host app's menu). Actions: Open in Chrome
    (Android `intent://`), Copy link (with a selectable-field fallback when the clipboard is refused).
15. **Text field.** Label above (14 px / 700), 16 px text, 1 px `--border-strong`, radius 12, `--focus` outline.
    Under it: the counter (13 px, tabular), then any error (icon + bold text, linked with `aria-describedby`); an
    invalid field gets a 2 px edge and the icon, not just red.
16. **Skeleton and spinner.** Skeleton bars in `--surface-2`, no shimmer under reduced motion. Spinner 18-22 px,
    `--primary-tint` track, `--primary` head.
17. **Waveform and level meter.** Decorative (`aria-hidden`); the hint text carries the state.
18. **Tour.** A spotlight on the real control (`--dim` around it), a callout card: "Step 1 of 3", title, text, Skip
    (text) · pips · Next (primary). A modal dialog for assistive tech; Escape = Skip.
19. **Copy.** Say what happened and what to do next, without blame ("We couldn't hear any words", not "You didn't
    speak"). Never claim a cause the page cannot know (no "server restart"). Numbers with units. Do not overclaim the
    score ("native-like" is gone).

## 3. Score tiers: one table for ring, title, chime and words

Today three sets disagree: titles 80/60, chime 70/30, word labels 70/59.5 (the server's
`argmin |[80, 60, 59] - a|`). The page follows the server's word thresholds, so a sentence whose words are all
Correct can never get an amber ring: the sentence score is the letter-weighted mean of its words.

| Sentence score | Ring and chime | Title EN | Title VI | Words (from the server, per word) |
|---|---|---|---|---|
| 90-100 | Correct colour, rising chime | Excellent! | Xuất sắc! | ✓ Correct: at least 70% of its letters |
| 70-89 | Correct colour, rising chime | Well done! | Làm tốt lắm! | |
| 60-69 | Almost colour, one note | Almost there | Gần được rồi | ~ Almost: 60-69%, or a typical mistake (ending, th, sh) |
| 0-59 | Needs-work colour, falling chime | Keep practising | Cố gắng thêm nhé | ✗ Needs work: under 60%, or not heard |
| fewer than 35% of the words heard | Needs-work colour, falling chime | That sounds like a different sentence | Hình như bạn đọc câu khác | |

Meaning line: "The computer heard N% of the sentence as written." / "Máy nghe đúng N% câu so với câu mẫu." The chime
never plays during a recording, and is skipped when it would come more than 500 ms late. Q1 kept these thresholds, which
are the server's; moving server and page to 80/60 would be a scoring change, with its own evaluation run.

## 4. Accessibility

- **No colour-only signal:** statuses have marks and words; wrong letters are bold and underlined; errors have an icon
  and text; the selected chip is filled, not just tinted.
- **Contrast:** text 4.5:1, non-text 3:1 (control edges, focus outline, ring arc, meaningful icons), in both themes.
- **Targets:** every control has a hit area of at least 44 × 44 px (the visual may be smaller, as for 36 px chips,
  when an invisible extension does not overlap a neighbour). Words inside the sentence are an inline exception, padded
  to at least 24 px; the "Words to practise" chips are the full-size way to reach them.
- **Focus order** follows the DOM: banner, header, chips, sentence card, controls (the bar sits right after the card
  in the DOM), result card, How it works, footer. Sheets: focus moves to the title on open, to Stop while recording,
  to the title while checking, to the primary action on an error; on close it returns to the control that opened the
  sheet, or to the result title after a score.
- **Announcements:** one polite status region on the page (loading, sentence ready, playing), one in each sheet
  (phase changes); `role="alert"` for blocking errors. Countdowns are announced once, not every second; the animated
  score never; the result is one sentence: "Score 79%. 3 words to practise: written, three, books."
- **Keyboard:** Space starts recording only when focus is not on a control; inside the sheet Space and Enter belong to
  the focused button; key repeats are ignored; Escape closes sheets and dialogs and skips the tour.
- **Headings and names:** one `h1` (the product name); the sentence card and the result card are labelled regions;
  every icon-only control has a name; the waveform and meter are decorative.
- **Reduced motion** as in §1.9. **Zoom:** usable at 200% text size; no horizontal scroll at 320 px; bar labels may
  wrap to two lines.
- **Languages:** `<html lang>` follows the interface; the sentence, its IPA and English words keep `lang="en"`.

## 5. Language: EN | VI

- English by default; EN | VI in the header; the choice is remembered on the device (localStorage, and a `lang`
  cookie so the server can render the page in that language: no flash of English for Vietnamese learners).
- Every string comes from one dictionary per language. The server's English messages are never shown as they come:
  the page maps each `code` to its own text. Codes: `text_too_long`, `text_not_english`, `text_bad_characters`,
  `invalid_request`, `bad_category`, `bad_language`, `no_audio`, `bad_audio`, `audio_too_long`,
  `request_entity_too_large`, `no_speech`, `busy`, `tts_busy`, `tts_unavailable`, `tts_failed`, `scoring_failed`,
  `server_error`; `client_gone` is never shown.
- Numbers and dates through `Intl` in the interface language (1,240 / 1.240). "Today", the streak and dates use
  Vietnam time (`Asia/Ho_Chi_Minh`).
- Vietnamese labels are often longer: layouts wrap, they never cut a label. Every screen is checked in both languages.
- Tone: plain and friendly; Vietnamese addresses the learner as "bạn".

## 6. Browsers and fallbacks

Targets: Chrome and Edge 109+ (school labs on Windows 7), Safari and in-app browsers on iOS 15+, Android Chrome and
WebView (Zalo, Facebook, Messenger), Firefox ESR 115+.

- **`color-mix()`: not used.** iOS up to 16.1 and Chrome 109 lack it. A plain fallback written before it in the same
  rule does not help when the `color-mix()` contains `var()`: the browser accepts the declaration when parsing and
  drops it only at computed-value time, which resets the property to its initial value. That is how today's 13 uses
  fail (no focus outline, transparent overlay, underlines in the text colour). Use the tokens of §1.4; if a new case
  is unavoidable, put it inside `@supports (color: color-mix(in srgb, red 50%, blue))` with the fallback outside.
- `dvh`: write `100vh` first, then `100dvh`.
- `:focus-visible` (Safari 15.4+): a plain `:focus` outline, removed by a separate `:focus:not(:focus-visible)` rule.
- `inert` (Safari 15.5+, Firefox 112+): a JS focus trap where it is missing.
- No native `<dialog>` (Safari 15.4+), no `:has()`, no CSS nesting, no container queries for anything essential.
- `text-decoration` as longhands; `-webkit-backdrop-filter` next to `backdrop-filter`.
- `navigator.clipboard` can be refused (some WebViews): show the address in a selected read-only field.
- Device check before release: iPhone on iOS 15/17/18, Android Chrome, Zalo, Facebook and Messenger on both, Chrome
  109 on Windows.

## 7. Screens: the intent of each layout

| Screen | Intent |
|---|---|
| Main, phones | Sentence and mic in the first viewport; the result right under the sentence; Listen · Mic · Next always in thumb reach |
| Recording sheet / dialog | Header and actions never move; the sentence scrolls in its own area; nothing lost by a stray tap; every failure says what to do and keeps the recording when sending again can work |
| Result card | The score in words, then what to practise first, then the details; never "native-like" |
| In-app banner | Get the learner out of Zalo, Facebook or Messenger before the first recording fails |
| Tour + mic check | Three steps over the real controls; the microphone prompt comes with an explanation |
| Progress sheet | Today, the streak, words to review; kept on the device; a guarded "New learner" for shared devices |
| My text sheet | Type, see the length and the reading time, fix errors in place |
| Desktop | Same content; inline controls; result beside the sentence |

## 8. When the user sends a component (Stitch or elsewhere)

Treat it as a specification, not as code.

- Replace only that part; leave the rest of the screen alone.
- Keep the layout, the order of information and the relative spacing.
- Drop inline styles, hex codes and utility classes; map them to the tokens of §1 and the classes of `style.css`.
  Inline `style` attributes would break the CSP anyway.
- Reuse the components of §2 before writing new ones.

## 9. Do not

- Load anything from another site (fonts, scripts, styles, images, icons, analytics); no CDN.
- Use inline `<script>` or `style` (the CSP forbids both), or `color-mix()`.
- Signal a status by colour alone, or fade text with `opacity`.
- Show a toast; show the server's message text as is.
- Add a UI library, a framework or an icon font without the user's approval; icons come from the sprite in
  `main.html`.
- Animate a state change for more than 200 ms, or animate at all under reduced motion.
- Store a recording or typed text on the server, or a recording in the browser beyond the open sheet.
- Add a privacy notice or a policy page (the user's decision).

## Appendix: how the numbers were checked

Contrast is WCAG 2.x relative luminance; colour blindness uses the Machado, Oliveira and Fernandes (2009) matrices at
full severity in linear RGB, with CIEDE2000 distances. To re-check a pair:

```python
def lum(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


print(round(contrast('#646b85', '#ffffff'), 2))  # 5.27
```
