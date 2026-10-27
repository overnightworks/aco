# `aco rulings`

`aco rulings` lists every open board item that carries at least one
`[[expectation]]` line, fully ruled ones too, read-only. This file owns its
row and per-line text, its ordering, its `--json` shape, and its empty-board
sentence. It cites the forge-resolution precondition `specs/board.spec.md`
owns (BOARD-01/BOARD-02/BOARD-42) rather than restating it, and the
`RULE-01`/`ASK-01` write paths that fill the lines this command only reads;
`specs/output.spec.md` owns the `--json` envelope itself (OUT-nn: key
order, `ok`, `message`) that wraps RUL-05's own `rulings` array. `<n>` is an
item number, `<label>` an item as `specs/landing-grammar.spec.md` prints
it, `<k>` an expectation line's 1-based index.

## Behavior table

| state \ trigger | text | `--json` |
|---|---|---|
| unsupported forge host / untracked pin | BOARD-01/02 (cited) | BOARD-01/02 (cited) |
| `--repo` under `storage = "state-ref"` | BOARD-42 (cited) | BOARD-42 (cited), RUL-09 |
| an item with an open expectation line | RUL-01, RUL-02 | RUL-05, RUL-10, RUL-12 |
| several such items | RUL-03 | RUL-05, RUL-10 |
| an item whose every line is already ruled | RUL-01, RUL-04 | RUL-05, RUL-10 |
| a ruled line | RUL-02 | RUL-05, RUL-10, RUL-12 |
| a line's `question`/`example`/`picture` | — | RUL-06 |
| an option line, open or ruled | RUL-02 | RUL-10, RUL-12, RUL-13, RUL-14, RUL-15 |
| an option line ruled `other` | RUL-02, RUL-16 | RUL-16 |
| an option line with its head | RUL-18 | RUL-17 |
| no item on the whole board carries an expectation line | RUL-07 | RUL-08 |
| a title or line holds a display control | RUL-11 | RUL-10, RUL-11 |

## Rows and lines

- [ ] [RUL-01] Each listed item prints one header, `<label> <open>/<total>: <title>`, then one line per expectation entry -- ruled ones too -- in block order (see E-RUL-01, E-RUL-05).
- [ ] [RUL-02] An open line prints `  <k> open: <summary>`, ruled `  <k> ruled <outcome> <date>: <summary>`, `<outcome>` an option line's letter or `other`; `<summary>` caps at 100, `…` last if cut (see E-RUL-01).
- [ ] [RUL-11] Text shows `<title>` and `<summary>` with each display control escaped (NEXT-37), `<summary>` after its cap; `--json` carries both as stored.
- [ ] [RUL-03] Rows rank by priority category, score, fewer open lines, ascending `<n>` (never `board --json`'s raw order); open-line items precede fully ruled ones, each group in that order (see E-RUL-02).
- [ ] [RUL-04] An item whose every expectation line is already ruled is listed, in both text and `--json`, in the fully-ruled group RUL-03 orders last (see E-RUL-02, E-RUL-05).

## `--json`

- [ ] [RUL-05] `rulings --json` wraps OUT-nn (`reason: "listed"`) around a `rulings` array (see E-RUL-03, E-RUL-05).
- [ ] [RUL-10] A row is `{"number", "title", "open", "total", "lines"}`; a yes/no line is `{"index", "text", "ruling", "ruled_on", "default"}` (see E-RUL-03).
- [ ] [RUL-12] An open line has `ruling`/`ruled_on` `null`; a yes/no line's `default` is its proposed outcome (ASK-02) until ruled, an option line's always `null` (see E-RUL-03, E-RUL-05, E-RUL-07).
- [ ] [RUL-06] A yes/no line's `question`/`example`/`picture` (`aco ask`, ASK-03) each add their own key, present only when that field was given.
- [ ] [RUL-13] An option line adds `question` to `reason` and `options`, each option keyed as listed below, its `letter` derived from its position (see E-RUL-07).
- [ ] [RUL-14] An option line also starts with `"form": "options"`, `"card_hash"` (the card now, BODY-89) and `"stored_card_hash"` (its ruling's, `null` while open); a ruled line's two are equal (BODY-87).
- [ ] [RUL-15] An option line carries `"via"` (`board`, `chat` or `default`, BODY-90) right after `"stored_card_hash"`, `null` while open; a yes/no line never carries it (see E-RUL-07).
- [ ] [RUL-16] An option line carries `"other"` after `"via"`: the answer verbatim once ruled `other`, else `null`; text prints `other` as `<outcome>` and the answer as `<summary>` (see E-RUL-07).
- [ ] [RUL-17] An option line carries `"returned_on"` and `"returned_note"` after `"other"`: its date and note while with its head, else `null`; a yes/no line never carries them (see E-RUL-07).
- [ ] [RUL-18] Text prints a line with its head `  <k> with head <date>: <summary>`, `<summary>` its note, else its text, capped and escaped as RUL-02 and RUL-11; it still counts as open (see E-RUL-07).

An option line's keys after `returned_note` are `question`, `problem`, `picture`,
`caption`, `decision_kind`, `area`, `topic`, `recommended`, `reason`,
`options`; each option is `{"letter", "name", "effect", "picture"` or
`"same_as_today": true`, `"caption"` when stored, `"notice", "cost", "undo",
"undo_how", "contract"}`.
- [ ] [RUL-09] `--json` on a dispatched refusal (BOARD-02, BOARD-42) prints OUT-nn's envelope with the sentence as `message` and `reason` from the table below, exit `2` (see E-RUL-06).

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| PIN-04 (`--repo` under `storage = state-ref`) | `invalid_usage` |
| BOARD-02 (no forge adapter for host), PIN-05 (no resolvable default branch) | `unavailable` |

## Empty board

- [ ] [RUL-07] With no item on the whole board carrying an expectation line, text output is exactly `No expectation lines.`, exit `0` (see E-RUL-04).
- [ ] [RUL-08] The same board's `--json` prints `{"ok": true, "reason": "listed", "rulings": []}`, exit `0` (see E-RUL-04).

## Never

- `aco rulings` never writes: it reads the same open-board projection `board`/`next` already build, and nothing else.
- `aco rulings` never re-scans an item's stale prose for its progress counts: a `## Erwartungen` heading left beside the block plays no part -- only the block's own `[[expectation]]` entries are read.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local
bare repository with `main` at one commit, a git identity, `origin/HEAD`, a
tracked `.aco/board.toml`, and `ACO_AGENT` set to `Ada`. A session
reading GitHub issues also names a fixed, deterministic fake `gh` as a
setup precondition (the shape `specs/landing-grammar.spec.md` already
uses).

### E-RUL-01 — one item, an open line and a ruled line

Setup: bare-remote, fake `gh`, issue `#10` open, one open (`default = "later"`) and one ruled `[[expectation]]` line

```console
$ aco rulings
#10 1/2: Open expectation
  1 open: Open decision 0.
  2 ruled yes 2026-09-19: Settled decision 0.
exit 0
```

### E-RUL-02 — ranked rows, a fully-ruled item ordered last

Setup: bare-remote, fake `gh`, issue `#50` in-flight with two open lines, issue `#60` a lower-priority item with one open line, issue `#70` fully ruled

```console
$ aco rulings
#50 2/3: In-flight security work
  1 open: Name it.
  2 open: Name it too.
  3 ruled yes 2026-09-19: Settled.
#60 1/1: Lower-priority product work
  1 open: Ship it?
#70 0/1: Fully ruled security work
  1 ruled yes 2026-09-19: Settled.
exit 0
```

### E-RUL-03 — `--json`

Setup: bare-remote, fake `gh`, issue `#10` as in E-RUL-01

```console
$ aco rulings --json
{"ok": true, "reason": "listed", "rulings": [{"number": 10, "title": "Open expectation", "open": 1, "total": 2, "lines": [{"index": 1, "text": "Open decision 0.", "ruling": null, "ruled_on": null, "default": "later"}, {"index": 2, "text": "Settled decision 0.", "ruling": "yes", "ruled_on": "2026-09-19", "default": null}]}]}
exit 0
```

### E-RUL-04 — no board item carries an expectation line

Setup: bare-remote, fake `gh`, no open issue's body carries an `[[expectation]]` line

```console
$ aco rulings
No expectation lines.
exit 0
$ aco rulings --json
{"ok": true, "reason": "listed", "rulings": []}
exit 0
```

### E-RUL-05 — a fully-ruled item, text and `--json`

Setup: bare-remote, fake `gh`, issue `#11` open with two ruled `[[expectation]]` lines, no open line anywhere

```console
$ aco rulings
#11 0/2: Fully ruled
  1 ruled yes 2026-09-19: Settled decision 0.
  2 ruled yes 2026-09-19: Settled decision 1.
exit 0
$ aco rulings --json
{"ok": true, "reason": "listed", "rulings": [{"number": 11, "title": "Fully ruled", "open": 0, "total": 2, "lines": [{"index": 1, "text": "Settled decision 0.", "ruling": "yes", "ruled_on": "2026-09-19", "default": null}, {"index": 2, "text": "Settled decision 1.", "ruling": "yes", "ruled_on": "2026-09-19", "default": null}]}]}
exit 0
```

### E-RUL-06 — `--json` refusal envelope, `--repo` under `storage = state-ref`

Setup: bare-remote, `storage = "state-ref"` tracked

```console
$ aco --repo acme/items rulings --json
2> ERROR: --repo is meaningless under storage = state-ref
{"ok": false, "reason": "invalid_usage", "message": "--repo is meaningless under storage = state-ref"}
exit 2
```

### E-RUL-07 — an open option line

Setup: bare-remote, fake `gh`, issue `#12` "Song jump" open, its one
`[[expectation]]` line the option line below

```toml
[[expectation]]
text = "The song stays open on the jump."
question = "Keep the song open?"
problem = "The jump closes your song."
picture = '<svg xmlns="http://www.w3.org/2000/svg"/>'
caption = "Today"
decision_kind = "product"
area = "Song page"
topic = "Jump"
recommended = "A"
reason = "Ends the loss."

[[expectation.option]]
name = "Song stays open"
effect = "The app jumps itself."
picture = '<svg xmlns="http://www.w3.org/2000/svg"/>'
caption = "Still open"
notice = "You stay in your song."
cost = "More code."
undo = "reversible"
undo_how = "Any time."
contract = "The song stays open."

[[expectation.option]]
name = "As today"
effect = "The browser jumps."
same_as_today = true
notice = "You pick the song again."
cost = "None."
undo = "final"
undo_how = "Nothing is built."
contract = "The link stays a link."
```

```console
$ aco rulings
#12 1/1: Song jump
  1 open: The song stays open on the jump.
exit 0
$ aco rulings --json
{"ok": true, "reason": "listed", "rulings": [{"number": 12, "title": "Song jump", "open": 1, "total": 1, "lines": [{"index": 1, "form": "options", "text": "The song stays open on the jump.", "ruling": null, "ruled_on": null, "default": null, "card_hash": "sha256:b3f1720e7b5b083f5ae59eaf99559b438d1e729dc9034e3ea534cf5806f23b8a", "stored_card_hash": null, "via": null, "other": null, "returned_on": null, "returned_note": null, "question": "Keep the song open?", "problem": "The jump closes your song.", "picture": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>", "caption": "Today", "decision_kind": "product", "area": "Song page", "topic": "Jump", "recommended": "A", "reason": "Ends the loss.", "options": [{"letter": "A", "name": "Song stays open", "effect": "The app jumps itself.", "picture": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>", "caption": "Still open", "notice": "You stay in your song.", "cost": "More code.", "undo": "reversible", "undo_how": "Any time.", "contract": "The song stays open."}, {"letter": "B", "name": "As today", "effect": "The browser jumps.", "same_as_today": true, "notice": "You pick the song again.", "cost": "None.", "undo": "final", "undo_how": "Nothing is built.", "contract": "The link stays a link."}]}]}]}
exit 0
```

Ruled `A` on 2026-10-28 with `via = "board"`, the same line prints `  1 ruled A 2026-10-28: The song stays open on the jump.`
and carries `"ruling": "A", "ruled_on": "2026-10-28"` and `"via": "board"` with `stored_card_hash` equal to `card_hash`.
Ruled `other` on 2026-10-28 with `via = "chat"` and `other = "Only on desktop."`, it prints `  1 ruled other 2026-10-28: Only on desktop.`
and carries `"ruling": "other"`, `"via": "chat"` and `"other": "Only on desktop."`.
Sent back to its head on 2026-10-28 with the note `Was kostet B?`, it prints `  1 with head 2026-10-28: Was kostet B?`
and carries `"ruling": null`, `"returned_on": "2026-10-28"` and `"returned_note": "Was kostet B?"`; the header still counts it open.
