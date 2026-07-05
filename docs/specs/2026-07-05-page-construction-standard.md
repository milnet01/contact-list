# Page Construction Standard (CL-0047)

**Status:** Signed off (2026-07-05) — passed `/cold-eyes` to convergence (6 loops,
2 independent cold reviewers per loop). Loops 1–5 caught and fixed real defects
that would have shipped broken UI: a tab `<button>` submitting the settings form,
the `page_header` macro escaping its action markup, the `.detail-header` JS
coupling, the floated-legend clear failing on an inline `<small>`, the control
selector stretching the photo checkbox/file input, and the print/specificity
issues. Loop 6 returned **zero CRITICAL/HIGH/MEDIUM** from both reviewers — only
LOW/INFO polish (all applied) — i.e. polish-convergence.

## 1. Goal

Every page in the app should be built the same way and read as one coherent
product. Today there are three divergent "looks" (survey 2026-07-05):

- **Card stack** — `sync`, `import`, `merge`, `duplicates`, `birthdays`,
  `contact_detail` wrap content in `.card` (white surface, soft shadow, rounded).
- **Settings fieldset-cards** — `settings.html` uses `<fieldset class="settings-form">`
  which, via `box-shadow`, looks identical to a `.card`, plus a full-width
  underlined section header.
- **Flat form** — `contact_form.html` uses plain `<fieldset>` with **no** shadow
  and a legend sitting on the border line, so it reads flat/unfinished.

The **Settings look is the canonical target** (the user's reference: "the edit
contact page doesn't have the same look as the settings page"). This standard
codifies that one look and a single page skeleton, then migrates every page to it.

## 2. The page skeleton

Every content page is:

```
{% extends "base.html" %}
{% from "_macros.html" import page_header %}
{% block title %}…{% endblock %}              {# each page keeps its existing title — unchanged #}
{% block breadcrumb %}…{% endblock %}          {# optional, sub-pages only #}
{% block content %}
  {{ page_header('<Page title>') }}             {# §3 — required #}
  {# per-page `errors` block, if the page validates a form (see §3) #}
  … one or more .card / <fieldset> sections (§4) …
{% endblock %}
```

- **Shell** — always `extends base.html`. No page supplies its own `<head>` or
  nav. (The sole exception is `server_action.html`, CL-0046, a standalone page
  shown while the server is down — out of scope here.)
- **One `<h1>` per page**, emitted **only** through the `page_header` macro (§3),
  never a bare `<h1>` — with the single documented exception of `contact_detail`,
  whose richer `.detail-header` variant is retained (§3, §8).

## 3. Page header — `page_header` macro

A single macro in `templates/_macros.html` (**new file**) renders the title row.
It uses Jinja's `{% call %}`/`caller()` mechanism so action markup is **not**
HTML-escaped (a plain `{{ actions }}` string param would render as escaped text
under the app's autoescaping):

```jinja
{% macro page_header(title) %}
<div class="page-header">
  <h1>{{ title }}</h1>
  {% if caller %}<div class="page-actions">{{ caller() }}</div>{% endif %}
</div>
{% endmacro %}
```

- **No title-row actions:** `{{ page_header('Settings') }}`. `caller` is undefined,
  so the `.page-actions` div is omitted.
- **With actions:** wrap the call —
  ```jinja
  {% call page_header('Import') %}
    <a class="btn" href="{{ url_for('contacts.contact_list') }}">Back</a>
  {% endcall %}
  ```
  The `caller()` output is real Markup (not escaped), right-aligned next to the
  title.
- **Breadcrumb** stays in base.html's `{% block breadcrumb %}` (rendered above the
  header) — unchanged mechanism, now used consistently by every sub-page.
- **Per-page validation errors are unaffected.** `base.html` only renders
  `get_flashed_messages` (the flash strip). Pages that show a form's `errors` list
  (`settings.html`, `contact_form.html`) keep their own `{% if errors %}…{% endif %}`
  block **after** `page_header` — this standard does not touch it.
- `.page-header` CSS: `display:flex; justify-content:space-between; align-items:
  baseline; gap:1rem; flex-wrap:wrap; margin-bottom:1rem;`. To avoid a doubled gap,
  the nested `<h1>` **loses** its own bottom margin: add `.page-header h1
  { margin-bottom:0; }` (mirroring the existing `.detail-header h1{margin-bottom:0}`
  at `style.css:548`). Net vertical rhythm below the title is unchanged (1rem).

### 3.1 `contact_detail` — the media-header variant

`contact_detail.html` uses `.detail-header` (avatar + `<h1>` + type/Google badges +
favourite toggle). It is **retained as-is**, not converted to `page_header`,
because:

- the macro has only a title slot — folding it in would drop the avatar and
  badges; and
- `static/app.js:230` (`document.querySelector('.detail-header h1')`, the
  recently-viewed feature) and `static/style.css:542,548,549,941` couple to
  `.detail-header` / `.detail-header h1`. Renaming it silently breaks that JS
  (which no server-side test would catch).

`.detail-header` is therefore the documented **rich page-header variant** for the
detail page: same role as `.page-header`, extra media/badges. INV-1 exempts it.

## 4. Content sections — the card

One canonical container, the **card**: white `--surface`, `--radius-lg`, 1px
`--border-light`, `var(--shadow)`, `1.5rem` padding, `1rem` bottom margin (the
existing `.card` rule). Two spellings must render **identically**:

- **`<div class="card">`** — non-form sections (info, tables, lists). Already used
  by most pages.
- **`<fieldset>`** inside a `<form>` — form sections.

### 4.1 CSS changes to unify them

The flat-vs-card difference is caused solely by a missing shadow + an on-border
legend (survey). Promote the Settings treatment to the **base** rules so *every*
form fieldset becomes a card with **no per-form class**:

- **`fieldset`** (base rule, `style.css:620`): add `box-shadow: var(--shadow);`,
  set `padding: 1.5rem;` + `margin-bottom: 1rem;` to match `.card` **exactly**
  (drop the Settings-specific `1.4rem 1.5rem 1.6rem` / `1.5rem` values), and add
  **`min-inline-size: 0;`** — a `<fieldset>` carries a UA `min-inline-size:
  min-content` that a `.card` `<div>` does not, so without this reset the two
  differ at narrow widths (INV-3). Blast radius is safe — `<fieldset>`
  appears **only** in `settings.html` and `contact_form.html` (verified); the
  Settings-tab fieldsets sit inside the Save form, and the Server fieldset *wraps*
  its own two POST forms (`settings.html:93`) — either way, no other template uses
  a `<fieldset>`.
- **Print parity:** the `@media print` block (`style.css:1014`) resets `.card` to
  `box-shadow:none; border:1px solid #ddd` (line 1018). Give `fieldset` the **same
  two** overrides — `@media print { fieldset { box-shadow:none; border:1px solid
  #ddd; } }` — so the two stay identical in print, not just on screen.
- **`legend`** (base rule, `style.css:627`): adopt the full `.settings-form legend`
  declaration set (`style.css:1105-1114`) verbatim — `float:left; width:100%;
  margin:0 0 1.25rem; padding:0 0 .65rem; border-bottom:1px solid var(--border-light);
  font-size:1rem; font-weight:700; letter-spacing:-0.01em; color:var(--text)` — a
  full-width underlined section header instead of sitting on the border line.
- **Clearing the float:** the legend uses `float:left; width:100%` (the standard
  trick to make a `<legend>` behave as a full-width block). Whatever element
  follows the legend must clear it, or it rides up beside the float — and that
  first element is **not always** a `.form-group` (Custom Fields opens with
  `<div id="custom-fields">`, `contact_form.html:103`; the Server fieldset opens
  with `<small class="form-hint">`, `settings.html:95`). So clear the **immediate
  next element** generically, not just `.form-group`:
  **`fieldset > legend + * { clear: both; }`** (the `+` combinator targets the
  first element sibling after the legend; once it clears, the rest stack below it
  normally). This replaces the old `.settings-form label { clear:both }`.
  **Include `display:block`** in that rule —
  `fieldset > legend + * { clear:both; display:block; }` — because `clear` has no
  effect on an **inline** box, and the Server fieldset's first child is an inline
  `<small class="form-hint">` (which has no CSS rule of its own). Without
  `display:block` that `<small>` would ride up into the legend row. The other
  first-children (`.form-group` / `#custom-fields` divs) are already block, so
  `display:block` is a harmless no-op for them.
- **`.card-title`** (new rule): for `.card` sections that want the same header, a
  `<h2 class="card-title">` styled to match the `legend`'s **visual** treatment —
  `border-bottom:1px solid var(--border-light); margin:0 0 1.25rem; padding:0 0
  .65rem; font-size:1rem; font-weight:700; letter-spacing:-0.01em` — but **without**
  the legend's `float:left; width:100%` (an `<h2>` is already a full-width block, so
  it needs no float, and the `fieldset > legend + *` clear does not apply inside a
  `.card`; floating it would leave the card body riding up beside it). Optional;
  most `.card`s have no title today and stay as-is.
- Delete **only** the now-redundant `.settings-form`-scoped rules by name —
  `.settings-form fieldset`, `.settings-form legend`, `.settings-form label`,
  `.settings-form fieldset label:last-child`, `.settings-form select /
  input[number]` — once their declarations move to the base rules. Do **not**
  delete by line range: the `.settings-form` block is interleaved with unrelated
  rules (e.g. `.merge-option` around `style.css:1127`) that must survive.
- `.settings-form` and `.contact-form` classes become unnecessary and are removed
  from the templates. Note `.settings-form` appears **twice** in `settings.html`
  (the Save `<form>` at line 13 **and** the Server `<fieldset>` at line 93) — remove
  both. `.contact-form` (on `contact_form.html`'s `<form>`) already has **no** CSS
  rule (inert) — remove it too.

## 5. Forms

One convention across `contact_form`, `settings`, and any future form.

### 5.1 Fields

- **`.form-group`** wraps each field: a `<label for=…>` above its control, optional
  `<small class="form-hint">` below.
- **Label style is unified to the Settings look** (mixed-case, medium weight,
  muted, block). **Note the change:** the current global `.form-group label`
  (`style.css:637`) is **UPPERCASE / 600 / 0.8rem / `letter-spacing:0.03em`**; this
  standard changes it to `text-transform:none; font-weight:500; font-size:0.9rem;
  letter-spacing:normal` — so `contact_form`'s labels shift from uppercase to
  mixed-case to match Settings. `.form-group` is used **only** in `contact_form.html`
  today (verified), so no other page is affected. This is intended (Settings is the
  reference look).
- Controls: block, `width:100%`, `max-width:26rem`, small top margin. Scope to the
  **text-like** controls only —
  `.form-group select, .form-group textarea, .form-group input:not([type=checkbox]):not([type=radio]):not([type=file])` —
  NOT a bare `.form-group input`. Two reasons: (1) the base `select`/`input` are
  already `width:100%` globally at `style.css:647`, and the new `max-width:26rem` +
  top margin must not leak onto the list-chrome filter toolbar select on
  `contacts.html` (`<select name="type">`, §5.3(d), unchanged); (2) `contact_form`'s
  Photo `.form-group` contains a `remove_photo` **checkbox** (`contact_form.html:78`)
  and a `photo` **file** input (`:82`) — the base rule deliberately excludes those
  types, and a bare `.form-group input` would stretch them to a full-width 26rem
  block (a detached, oversized checkbox). Move the declarations from the
  `.settings-form select/input[number]` rule (`style.css:1134`) to this scoped rule.
  **Note:** the `max-width:26rem` narrows `contact_form`'s currently full-width text
  inputs to a 26rem column — intended, matching Settings.

### 5.2 Settings field restructure

`settings.html` currently uses **nested** `<label>Theme <select…></label>` with no
`id`/`for` (`settings.html:18`). Convert each of the **10** settings controls
(3 Appearance + 2 Dates & Time + 5 Contacts & Phone) to the `.form-group` shape:
`<div class="form-group"><label for="theme">Theme</label>
<select id="theme" name="theme">…</select></div>`. Keep every `name` attribute
exactly as-is (the route reads by `name` — INV-6). This is a real markup change on
`settings.html`, listed in §8. Expect a slightly **tighter** inter-field spacing on
Settings afterward (the old `.settings-form label{margin-bottom:1.1rem}` gives way
to `.form-group`'s smaller gaps) — intended by the unification, not a regression.

### 5.3 Actions & exemptions

- **`.form-actions`** holds the submit/cancel row at the end of the form (`display:
  flex; gap:.5rem; margin-top:1.25rem`). Settings' current **loose** Save button
  moves into a `.form-actions`.
- Primary action first (`.btn`), secondary/cancel after (`.btn-secondary`),
  destructive as `.btn-danger`.
- **Exemptions from "every field is a `.form-group`" (INV-2):** (a) the contact
  form's paired-input `.custom-field-row` (name+value+remove on one line); (b) any
  **action-only** fieldset (the Server controls — buttons, not fields); (c)
  sub-controls that belong to a parent group (the Photo group's `remove_photo`
  checkbox lives inside the Photo `.form-group`, not its own); and (d) **list-chrome
  forms** — the search / type-filter / sort toolbar on `contacts.html` is a
  filter bar, not a data-entry form, and keeps its inline layout (§8 leaves it
  unchanged). These are all explicitly exempt.

## 6. Buttons

- Variants kept as-is: `.btn` (primary), `.btn-secondary`, `.btn-danger`,
  `.btn-small`.
- **Placement:** action rows use `.form-actions` **inside a `<form>`** and
  `.actions` **outside** a form (e.g. `contact_detail`'s bottom Edit/Delete/Back).
  `.bulk-bar` (multi-select toolbars on list/duplicates) is a **selection**
  toolbar, not a page/form action row — explicitly exempt, unchanged.
- **Confirm-before-destructive** uses `data-confirm="…"` (the `static/app.js`
  modal), never inline `onclick` (CSP blocks inline handlers — CL-0046).

## 7. Tabs (multi-section pages)

For a page with several independent peer sections (Settings: Appearance, Dates &
Time, Contacts & Phone, Server), group them into tabs instead of a long scroll.

### 7.1 Markup

Authored with **all panels visible and none `hidden`** (the no-JS state, §7.3).
Tab buttons are `type="button"` so they never submit an enclosing form:

```html
<div class="tabs">
  <div class="tab-bar" role="tablist" aria-label="Settings sections">
    <button type="button" class="tab" role="tab" id="tabbtn-appearance"
            aria-controls="tab-appearance" aria-selected="true"  tabindex="0">Appearance</button>
    <button type="button" class="tab" role="tab" id="tabbtn-dates"
            aria-controls="tab-dates"      aria-selected="false" tabindex="-1">Dates &amp; Time</button>
    <button type="button" class="tab" role="tab" id="tabbtn-contacts"
            aria-controls="tab-contacts"   aria-selected="false" tabindex="-1">Contacts &amp; Phone</button>
    <button type="button" class="tab" role="tab" id="tabbtn-server"
            aria-controls="tab-server"     aria-selected="false" tabindex="-1">Server</button>
  </div>
  <section class="tab-panel" id="tab-appearance" role="tabpanel" aria-labelledby="tabbtn-appearance"> … </section>
  <section class="tab-panel" id="tab-dates"     role="tabpanel" aria-labelledby="tabbtn-dates"> … </section>
  …
</div>
```

No `hidden` attribute is authored on any panel; no `aria-selected` panel is
pre-hidden. (See §7.3 — JS establishes the initial single-panel state.) **Note:**
this generic example shows panels as direct children of `.tabs`; for Settings,
three panels are nested **inside the Save `<form>`** — see §7.2 for the real DOM.

### 7.2 Settings form structure (resolves the two-form layout)

Settings has **two** independent form contexts: the Save form (Appearance / Dates /
Contacts → one Save button) and the Server controls (their own two POST forms to
`/settings/server`). Nesting forms is invalid HTML, so the tab container is laid
out as (ARIA `role`/`aria-*` on the tabs and panels abbreviated here — see the
full attribute set in §7.1):

```
{{ page_header('Settings') }}
{% if errors %}…errors block…{% endif %}
<div class="tabs">
  <div class="tab-bar" role="tablist"> …4 type="button" tabs… </div>

  <form method="post" action="{{ url_for('settings.save_settings') }}">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
    <section class="tab-panel" id="tab-appearance"> <fieldset>…form-groups…</fieldset> </section>
    <section class="tab-panel" id="tab-dates">      <fieldset>…</fieldset> </section>
    <section class="tab-panel" id="tab-contacts">   <fieldset>…</fieldset> </section>
    <div class="form-actions" data-tab-scope="settings-save"><button class="btn">Save settings</button></div>
  </form>

  <section class="tab-panel" id="tab-server"> <fieldset>…Server data-confirm buttons…</fieldset> </section>
</div>
```

- The **tab-bar sits outside** the Save form; its buttons are `type="button"`, so a
  tab click never submits.
- Panels 1-3 and the Save `.form-actions` are **inside** the Save form; the Server
  panel is **outside** it (its own POST forms).
- The Save `.form-actions` carries `data-tab-scope="settings-save"`: the tab JS
  hides it whenever the active tab is **Server** (Save is meaningless there) and
  shows it on the three settings tabs.

### 7.3 Behavior — handler in `static/app.js`

A **dedicated IIFE** (its own `(function(){…})()`). This is **required**, not
stylistic: `app.js` is currently a single IIFE (lines 2–534) whose custom-fields
guard `return;`s at `app.js:347` when `#custom-fields` is absent — which exits the
**entire** IIFE, so on Settings a tab handler appended to it would never run. (That
early return also strands the existing back-to-top / `--header-h` code on every
page without the contact form — a pre-existing bug tracked separately as CL-0048;
this standard only requires the new tab handler to stand alone.)

- **On load:** find each `.tabs`; add the `js-tabs` class (reveals the tab bar,
  §7.4); add `hidden` to every `.tab-panel` except the one whose tab has
  `aria-selected="true"` (the first). Hide any `[data-tab-scope="settings-save"]`
  if the initially-selected tab is Server (it isn't, but the rule is general).
- **On `.tab` click:** set clicked tab `aria-selected="true"` + `tabindex="0"`, the
  rest `false`/`-1`; unhide its panel, `hidden` the others; toggle the
  `data-tab-scope` Save row per §7.2; move focus to the clicked tab.
- **Keyboard (roving tabindex, WAI-ARIA tabs):** Left/Right (and Home/End) move
  selection between tabs and activate on move; only the selected tab is in the tab
  order (`tabindex="0"`), the rest `-1`.
- **No-JS fallback (INV-4), progressive enhancement:** the `.tab-bar` is hidden by
  default in CSS (`.tab-bar{display:none}`); the tab JS adds a class to `.tabs`
  (e.g. `.tabs.js-tabs .tab-bar{display:flex}`) to reveal it. So with JS **off**:
  no tab bar is shown and every panel is visible — a plain long settings page
  (today's behavior), with no dead/non-functional tab buttons. With JS **on**: the
  bar appears and panels switch. No content is reachable only via a tab click.

### 7.4 CSS (new rules)

- `.tabs` — block wrapper, `margin-bottom:1rem`.
- `.tab-bar` — **`display:none`** by default (no-JS shows no bar). `.tabs.js-tabs
  .tab-bar` — `display:flex; gap:.25rem; border-bottom:1px solid var(--border);
  margin-bottom:1rem; flex-wrap:wrap;`. The JS adds `js-tabs` to each `.tabs` on
  init.
- `.tab` — button reset: transparent bg, no border, padding `.5rem .9rem`,
  `cursor:pointer`, muted color, `border-bottom:2px solid transparent`,
  `margin-bottom:-1px`.
- `.tab[aria-selected="true"]` — accent text + `border-bottom-color:var(--accent)`.
- `.tab:hover`, `.tab:focus-visible` — reuse existing focus styling.
- `.tab-panel[hidden]` — hidden (native). No other panel styling needed; the
  fieldset/card inside carries the look.
- **Print:** in the `@media print` block, reveal all panels and drop the bar —
  `.tab-panel[hidden]{display:block !important}` + `.tabs.js-tabs .tab-bar
  {display:none !important}`. The **`!important`** is what does the work: it beats
  the non-important reveal rule `.tabs.js-tabs .tab-bar{display:flex}` regardless of
  that rule's (0,3,0) specificity (a bare `.tab-bar{display:none}` **without**
  `!important` would lose, since media queries add no specificity). Matching the
  `.tabs.js-tabs` selector is belt-and-suspenders, not strictly required.
- `.form-hint` currently has **no** dedicated rule (renders as a default `<small>`,
  intentionally). This standard does not add one; leave as-is.

**Scope of tabs:** Settings only. Import (stage-driven) and Sync (auth-state-driven)
are **not** peer sections — not tabbed.

## 8. Per-page migration checklist

Each page: `extends base.html`, import + use `page_header(...)`, wrap content in
cards, forms use `.form-group` + `.form-actions`, buttons per §6.

**Title text is normalized deliberately** where it drifts from the nav label —
e.g. "Google Contacts Sync" → **Google Sync**, "Import Contacts" → **Import**,
"Duplicate Contacts" → **Duplicates** — so the `<h1>` matches the nav item. No
test asserts the old strings (verified), so the suite stays green.

| Page | Changes |
|------|---------|
| **`_macros.html`** | **New file** — the `page_header` macro (§3). |
| `settings.html` | `page_header('Settings')`; keep the `errors` block; convert the 4 sections into **tabs** (§7) with the two-form layout (§7.2); convert each field to `.form-group` + `id`/`for` (§5.2); move the loose Save button into `.form-actions`; drop the `settings-form` class. |
| `contact_form.html` | import + `page_header(...)` (replaces the bare `<h1>`); keep the `errors` block; fieldsets now render as cards automatically (§4); labels shift to mixed-case (§5.1); `.form-actions` already used — keep; drop the `contact-form` class; `.custom-field-row` exempt (§5.3). Breadcrumb unchanged. |
| `contact_detail.html` | **Keep `.detail-header`** (the media-header variant, §3.1) — do **not** macro-ize (preserves avatar/badges and the `app.js:230` coupling). `.card` body + bottom `.actions` unchanged. |
| `contacts.html` | Add `{% call page_header('Contacts') %}<a class="btn" href="{{ url_for('contacts.new_contact') }}">+ New</a>{% endcall %}` (today it has **no** `<h1>`); `.list-controls` / `.toolbar` / `.bulk-bar` unchanged (list chrome). |
| `sync.html` | `page_header('Google Sync')`; already `.card` — no structural change. |
| `import.html` | `page_header('Import')`; already `.card` stages — no structural change. |
| `merge.html` | `page_header('Merge Contacts')`; already `.card` — no structural change. |
| `duplicates.html` | `page_header('Duplicates')`; already `.card` — no structural change. |
| `birthdays.html` | `page_header('Upcoming Birthdays')`; already `.card` — no structural change. |
| `error.html` | Out of scope — `.empty-state`, no title row. |

## 9. Testing

- **Existing suite stays green.** Route/template tests assert on content
  substrings and buttons (e.g. `value="restart"`, contact names, flash/error text,
  `>Clear</a>`) — restructuring markup around them must keep those substrings. Run
  the full suite after each template change.
- **Client-JS couplings to preserve (not caught by server-side tests):**
  `.detail-header h1` (`app.js:230`, recently-viewed) — keep the class (§3.1);
  the `#custom-fields`/`#add-field` block — the tab handler must be a separate IIFE
  (§7.3).
- **Settings tabs test:** GET `/settings` still contains every section's controls
  (theme select, timezone, `per_page`, and the restart/shutdown hidden-input
  values — asserted by `tests/test_server_control.py:123` as `value="restart"` /
  `value="shutdown"`, which survive the Server-panel move). All panels are present
  in the served HTML (tabs only hide via JS; the test sees the no-JS DOM). **Add a
  new assertion** that the tab scaffold is server-rendered: the four
  `.tab-panel` ids are present and every `.tab` button carries `type="button"`
  (locks INV-4/INV-5 cheaply, without a browser).
- **Hidden panels still submit.** The three settings tab-panels sit inside the one
  Save `<form>`; JS `hidden` on a panel does **not** stop its fields from
  submitting, so saving from any settings tab posts *all* settings fields
  unchanged — this is what keeps `save_settings` (and its tests) working
  untouched (INV-6). State it so the regression story is explicit.
- **No server-side behavior changes** — markup/CSS only; no route, model, or
  form-handling change. `save_settings`, `create`/`update`, etc. are untouched, so
  their tests are the regression guard that forms still submit the same fields.
  Watch: converting settings labels to `.form-group` adds `id`/`for` but keeps the
  `name` attributes the handler reads — verify field `name`s are unchanged.
- Manual: the user eyeballs each page (no browser automation here).

## 10. Out of scope

- No new pages, no route changes, no data-model changes.
- No restyle of the global nav header, footer, flash, or modal (already shared).
- `server_action.html` (standalone) and `error.html` (`.empty-state`) keep their
  minimal shapes.
- No color/theme changes — reuses existing tokens (`--surface`, `--border`,
  `--shadow`, `--radius*`, `--accent`).

## 11. Invariants

- **INV-1** Exactly one `<h1>` per **in-scope content page**, emitted via
  `page_header` — the sole exception among them is `contact_detail`'s retained
  `.detail-header` (§3.1). The out-of-scope `error.html` and `server_action.html`
  (§10) keep their own bare `<h1>`s.
- **INV-2** In the **standardized content/settings forms** (contact create/edit,
  settings), every data-entry **field** is a `.form-group` (label + control
  [+ hint]) and every form's actions are in a `.form-actions` — **except** the
  exemptions in §5.3 (`.custom-field-row`, action-only fieldsets, parent-group
  sub-controls, and list-chrome filter/search toolbars).
- **INV-3** Form `<fieldset>` sections and `<div class="card">` sections render
  visually identically — same surface, border, radius, **padding (1.5rem)**,
  **bottom margin (1rem)**, and shadow — on screen **and in print**. Header
  treatment matches **when a header is present**: a `<legend>` and a
  `<h2 class="card-title">` share one declaration set; a plain `.card` with no
  title simply has no header.
- **INV-4** Tabs degrade to all-panels-visible with JS disabled (panels authored
  without `hidden`); no content is reachable **only** through a tab click.
- **INV-5** No inline JavaScript is introduced (tabs handler lives in
  `static/app.js`); the strict CSP is untouched. Tab buttons are `type="button"`
  (never submit an enclosing form).
- **INV-6** No server-side route/model/form-handling behavior changes; field
  `name` attributes are unchanged, so the existing test suite passes (additive
  assertions only).
