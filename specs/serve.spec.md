# `aco serve`

`aco serve --repo PATH...` shows one or
more repositories' open expectation lines in a browser SPA and writes each
decision through the installed `aco` command line, never through aco's own
modules; without `--repo`, the current directory is the one repository
served. This file owns the board's decision rules: which outcomes it writes,
when it refuses a decision, how writes are ordered and stopped, and the note
it may carry -- across every configured repository, since one write turn and
one drain span all of them. It cites the read shape `specs/rulings.spec.md`
owns (RUL-10) and the write `specs/rule.spec.md` owns (RULE-01, RULE-14, RULE-20)
rather than restating them. It also owns the JSON API under `/api/` -- its
shapes, token, and headers -- and the shell's own delivery contract (who may
fetch it, and how it is contained to its own files); the SPA's own behaviour
once loaded is `frontend/`'s. `<n>` is an item number, `<k>` an expectation
line's 1-based index, `<repo>` a configured repository's label -- the
resolved directory's name.

## Behavior table

| state \ trigger | load the page | decide a shown card |
|---|---|---|
| an open line | ABRD-06 | ABRD-01, ABRD-58, ABRD-59 |
| the line's shown fields changed since the page was built | ABRD-06 | ABRD-02 |
| a ruled line | ABRD-06, ABRD-37, ABRD-54, ABRD-57 | RULE-04 |
| an option line, open or ruled | ABRD-07, ABRD-34, ABRD-53, ABRD-56, ABRD-61, ABRD-62, ABRD-36, ABRD-37, ABRD-38, ABRD-43, ABRD-44, ABRD-45, ABRD-46, ABRD-47, ABRD-63, ABRD-65, ABRD-66, ABRD-67, ABRD-68, ABRD-69 | ABRD-39 (option) |
| a withdrawn line | ABRD-60 | — |
| an `option`, `other` or `unclear` posted for a line that is no option line | — | ABRD-40 |
| its card changed between the board's read and aco's write | — | ABRD-41 |
| a post naming not exactly one of `outcome`, `option`, `other`, `unclear`, another letter, or a note beside an `option` or `other` | — | ABRD-42 |
| an `other` posted with an open option line's fingerprint | — | ABRD-64 |
| an `unclear` posted with an open option line's fingerprint | — | ABRD-70 |
| a second decision while one is being written, in any configured repo | — | ABRD-03, ABRD-17 |
| the board is stopping | — | ABRD-04, ABRD-18 |
| a note or an answer on the decision | — | ABRD-05 |
| `aco rulings --json` names a field outside its shape | ABRD-07 | ABRD-07 |
| one configured repo's `aco rulings` fails or hangs | ABRD-15 | ABRD-15 |
| every configured repo's `aco rulings` fails or hangs | ABRD-20 | ABRD-20 |
| an `/api/` request without the right token | ABRD-10 | ABRD-10 |
| a decision naming a repo outside the configured ones | — | ABRD-16 |
| a card's fingerprint submitted against a different configured repo | — | ABRD-21 |
| `aco serve --json` | ABRD-26 | — |
| the global `aco --repo OWNER/REPO` before `serve` | ABRD-27 | — |

## Writing a decision

- [ ] [ABRD-01] Deciding a shown open yes/no card with outcome `yes`, `no`, or `later` runs `aco rule <n> --line <k>` with `--yes`, `--no`, or `--later` and `--json` (see E-ABRD-01).
- [ ] [ABRD-02] A card whose shown fields changed since it was shown -- an option line's `card_hash` (ABRD-35) -- is refused `Diese Zeile hat sich geändert, bitte neu laden`, no `aco rule` run (see E-ABRD-02).
- [ ] [ABRD-03] The board runs one `aco rule` at a time; a decision arriving meanwhile waits. Decisions on distinct lines are both stored; on the same line, the later one answers `already_ruled` (RULE-04).
- [ ] [ABRD-04] Stopping the board waits for an `aco rule` already running; a decision still waiting for its turn or arriving after stopping began is refused `board is shutting down`, no `aco rule` run.
- [ ] [ABRD-05] A note or answer is at most `280` characters after trimming, holds no NUL, and is valid UTF-8; any other refuses the decision before any `aco` call; a blank note is no note, a blank answer is refused.
- [ ] [ABRD-39] An `option` posted with an open option line's fingerprint runs `aco rule <n> --line <k> --option <X> --via board --card-hash=<H> --json`, `<H>` that line's `card_hash` just read (E-ABRD-12).
- [ ] [ABRD-40] An `option`, `other` or `unclear` posted for a line that is no option line, or for no line at all, is refused `Diese Zeile hat sich geändert, bitte neu laden`, no `aco rule` run: no card hash to name.
- [ ] [ABRD-41] An `aco rule` refusal `card_changed` (RULE-17) answers `failed` with `Diese Zeile hat sich geändert, bitte neu laden`; every other answer keeps its mapping, `already_ruled` (RULE-04) included.
- [ ] [ABRD-42] A post not naming exactly one answer (the key rules below) answers 400 `bad request: decision`; an `option` not `A`-`D` is refused the same way.

The key rules for ABRD-42: `outcome` (with an optional `note`), `option` (with no note or a blank one), `other` (its text, with no non-null `outcome`, `option` or `note`) and `unclear` (literally `true`, with an optional note and no non-null `outcome`, `option` or `other`) each name one answer; a blank note on `unclear` is no note. An absent key and a `null` value name nothing, so a valid `other` alongside `outcome: null` and `option: null` is accepted. A post carrying both `outcome` and `option` keys is refused whatever their values, unless its `other` is non-null, which then decides as above.

## Reading the lines

- [ ] [ABRD-06] Every page load reads `aco rulings --json` afresh, for every configured repo, and shows each line whose `ruling` is `null` as a card, in aco's own order within its repo; the board keeps no copy.
- [ ] [ABRD-07] A yes/no line with a non-outcome `default` or `ruling`, a malformed option line (below, ABRD-62), a `form` but ABRD-60's, or a non-ISO `ruled_on` shows `aco rulings --json is unreadable: <detail>`.

An option line is malformed when its `recommended` is no letter of its options, its `ruling` is neither such a letter nor `other`, its `other` is not non-blank text on a line ruled `other` or is neither absent nor `null` on any other, an option's `letter` is not A, B, C, D by position, a card field has the wrong type, or its `via` is missing or neither `null` nor `board`, `chat` or `default`.

## Browser decision flow

- [ ] [ABRD-28] The decision list groups open lines by repository under its name and open count; a row shows its state shape and an option line's topic, or a yes/no line's short question or sentence.
- [ ] [ABRD-29] Within a repository, open option lines come before yes/no lines, each in aco's order. First load selects the first row; desktop shows its card, phones the list until a row is tapped.
- [ ] [ABRD-30] Decided groups the ruled lines of open board items by repository under its name and count; a row shows the Decided shape and an option line's topic, or a yes/no line's short question or sentence.
- [ ] [ABRD-31] Within a repository, Decided lists the newest date first, then item number and line index descending, missing dates last; with no ruled line and no failed repository it reads `Nothing decided yet`.
- [ ] [ABRD-32] Opening Decided selects its first row: its card on desktop, the list on phones. Returning to Open keeps its selection, list position and phone view; a background decision displaces neither view.
- [ ] [ABRD-33] During undo a question stays open; only successful storage and reload move it to Decided. A stored “Später” stays there and is not automatically presented again.
- [ ] [ABRD-36] An open option line shows its card: repository, area, kind, `with head` (ABRD-61), `reversible` or `final`, question, Problem, Today, options A-D, Recommendation and Decide (ABRD-44).
- [ ] [ABRD-37] A selected ruled line shows the decided card: meta, question, Decided (`A — name`, `Ja`, `Nein`, `Später` or ABRD-57), How (ABRD-54) and Contract behind `Show` with its binding sentences and source.
- [ ] [ABRD-54] How reads `Board`, `From chat` or `Recommendation kept – no answer` for an option line's `via` (ABRD-53), else `not recorded`; then ` · ` and the ruling date as `DD.MM.YYYY` when known.
- [ ] [ABRD-57] A line ruled `other` shows Decided as `Other: „<answer>“` and binds that answer alone behind Contract's `Show`; How reads as ABRD-54; Open never lists it, Decided does (ABRD-30).
- [ ] [ABRD-38] Each option on an option card is a button that opens its Result (picture or `= TODAY`), You notice, Cost, Undo and Contract behind `Show`; opening one closes the other.
- [ ] [ABRD-43] Each Today and Result picture on an option card is an `Enlarge picture` button opening it with its caption in a modal dialog; `Close` or `Esc` closes it and focus returns to the button.
- [ ] [ABRD-44] An open option card's Decide row has one pick per option, the recommended one in the accent; a pick waits out the undo window, then posts `option` (ABRD-39); once stored, the card moves to Decided.
- [ ] [ABRD-45] A refused pick shows its sentence in the Decide row; "changed" (ABRD-02) or "already ruled" hide the picks behind `Neu laden`, and any other failure keeps them.
- [ ] [ABRD-46] A pick on a `final` option first opens a modal `Decide <X>?` with its Undo consequence and the warn mark, focus on `Cancel`; `Decide <X>` starts the undo window (ABRD-44).
- [ ] [ABRD-47] `Cancel` or `Esc` closes the confirm, posts nothing and returns focus to the pick; `Decide <X>` posts the card as shown when the confirm opened, so a card changed since is refused (ABRD-02).
- [ ] [ABRD-58] A pick shows a strip above the card until its 8 s undo window ends: the Decided shape, `Decided: <letter> — <name> · <topic>` and `Undo`, in view while the card scrolls and atop a phone's list.
- [ ] [ABRD-59] A pick moves focus to its strip's `Undo`, so Enter undoes it; `Undo` cancels the post and focuses the shown card, else the list. A window that ends removes its strip, and ABRD-50 applies.
- [ ] [ABRD-48] An option line's row carries the Open or With head (ABRD-61) shape; a yes/no line's the dashed Not ready shape in muted text. Each shape names its state; a row's title is its full question.
- [ ] [ABRD-61] An open option line with `returned_on` is with its head: Open lists it muted, with the With head shape (ring, back chevron), after other option lines; its card shows `with head`. Decide stays.
- [ ] [ABRD-49] Readable repositories with nothing open are named once under `Nothing open:`; with no open line and no failed repository the list reads `All decided`.
- [ ] [ABRD-50] Once the shown card's decision is stored, the stage moves to the list's first open option line, else to its first row; a card selected meanwhile stays (ABRD-32).
- [ ] [ABRD-51] A 56 px header (52 px on phones) holds the brand `Entscheidungs-Board` and the tabs `Open n` and `Decided n`: n counts the open list's rows and the ruled lines Decided lists.
- [ ] [ABRD-55] On phones a tapped row's card fills the pane without its card frame, under a header whose `‹ Open` or `‹ Decided` returns to that list with the row focused; the tabs hide meanwhile.
- [ ] [ABRD-63] An open option card's Decide row ends with `Other…`, beside the picks; it opens a panel with one textarea (`Your answer`, at most 280 characters, focused) and `Send`, disabled while blank.
- [ ] [ABRD-64] An `other` posted with an open option line's fingerprint runs `aco rule <n> --line <k> --other=<T> --via board --card-hash=<H> --json`, `<T>` the trimmed answer, `<H>` as ABRD-39 (E-ABRD-13).
- [ ] [ABRD-65] `Other…` and `Send` hide with the picks (ABRD-45), disable while a decision on the card waits and ignore clicks while the board reloads, so a pick and an Other never both post.
- [ ] [ABRD-66] The typed answer is kept per card: closing the panel, switching cards, `Undo` and a failed post keep it; `Undo` reopens the panel with it, and a stored decision drops it.
- [ ] [ABRD-67] `Send` closes the panel and starts the undo window with the strip `Decided: Other · <topic>` and `Undo` (ABRD-58, ABRD-59); `Undo` posts nothing.
- [ ] [ABRD-68] `Send` posts the card as shown when the panel opened, so a card changed since is refused (ABRD-02); the answer stays in the draft.
- [ ] [ABRD-69] A card that is with its head (ABRD-61) offers `Other…` as any open option card does.
- [ ] [ABRD-70] An `unclear` posted with an open option line's fingerprint runs `aco rule <n> --line <k> --unclear [--note=<T>] --card-hash=<H> --json`, no `--via`, `<T>` the trimmed note (E-ABRD-14).
- [ ] [ABRD-52] An option card's Decide row sticks to the pane's foot while the card runs on beneath it and then casts a shadow over that content; at the card's end it rests in place without one.

The browser proofs are `frontend/e2e/decide.spec.ts`,
`frontend/e2e/decideOption.spec.ts`, `frontend/e2e/decided.spec.ts`, `frontend/e2e/escapeRow.spec.ts`,
`frontend/e2e/openList.spec.ts`, `frontend/e2e/optionCard.spec.ts`, `frontend/e2e/pageFrame.spec.ts` and `frontend/e2e/pictureEnlargement.spec.ts`; ordering is additionally proven by
`frontend/src/app/model/boardSummary.test.ts`.

## Multiple repositories

- [ ] [ABRD-14] `aco serve --repo PATH` (repeatable) configures the repos served, labelled `<repo>` by each resolved directory's name; without `--repo`, the current directory is the one repository.
- [ ] [ABRD-15] `GET /api/board` answers once any repo's read succeeded; a failed repo carries its own error sentence and no items or cards, others unaffected (see E-ABRD-06).
- [ ] [ABRD-16] A decision naming a `repo` outside the configured labels is refused `bad request: decision` before any `aco` call (see E-ABRD-07).
- [ ] [ABRD-17] The one write turn (ABRD-03) spans every configured repo: a decision for one repo never writes while another repo's decision is being written (see E-ABRD-07).
- [ ] [ABRD-18] Stopping the board (ABRD-04) drains every repo: it waits for a running `aco rule` in any one, and refuses a waiting decision in any repo once stopping begins, without waiting for the running one.
- [ ] [ABRD-19] A `--repo` path that is not a directory is a usage error; two resolved paths with the same label refuse the start with `ERROR: two repositories named <repo>: <p1>, <p2>`.
- [ ] [ABRD-21] A card's fingerprint binds the `repo` it was read under; posted against another configured repo, identical content included, it is refused like a changed line (see E-ABRD-07).

## The JSON API

- [ ] [ABRD-08] `GET /api/board` answers `{"repos": [{"name", "error", "items"}]}` in order; `items` as before (E-ABRD-03); `error` is `null` once read, else aco's failure sentence, `items: []` (E-ABRD-06).
- [ ] [ABRD-09] `POST /api/rule` takes `repo`, `item`, `line`, `fingerprint` and one answer (ABRD-42); 200 `{"status", "message"}`, else 400 `bad request: decision` (E-ABRD-04, -07, -12, -13, -14).
- [ ] [ABRD-10] Every `/api/` request, any method, needs exactly one `X-Board-Token` header with the start token, else 403 `{"error": "forbidden: missing or wrong token"}` before any `aco` call (see E-ABRD-05).
- [ ] [ABRD-11] A body not complete 10 seconds after its headers, however it trickles, or that ends before its declared Content-Length is received, answers 408 `{"error": "request timeout: body incomplete"}`.
- [ ] [ABRD-20] Once every configured repo's `aco rulings` fails or hangs, `GET /api/board` answers 502 with the same `repos[]` envelope as ABRD-08, each entry its own reason (E-ABRD-06).
- [ ] [ABRD-12] Every answer, HTTP-layer refusals included, carries `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and a CSP with `base-uri`, `form-action`, and `frame-ancestors` set to `'none'`.
- [ ] [ABRD-13] With the token, an `/api/` method other than `GET` or `POST` answers 405 `{"error": "method not allowed"}` with `Allow` naming the route; elsewhere it answers 405 as text with the same header.
- [ ] [ABRD-34] A line with `"form": "options"` is listed as an option line (E-ABRD-11); a line without `form` stays a yes/no line as before. The board offers no yes/no outcome on an option line.
- [ ] [ABRD-35] An option line's fingerprint is the SHA-256 of `[item, index, card_hash]`, bound to its repo (ABRD-21); `stored_card_hash`, `default`, `via`, `returned_on`, `returned_note`, unknown keys leave it be.
- [ ] [ABRD-53] An option line lists `via`, as `aco rulings --json` names it (RUL-15): `board`, `chat`, `default` or `null` while open; any other value, or none, is unreadable (ABRD-07). A yes/no line lists none.
- [ ] [ABRD-62] An option line lists `returned_on` and `returned_note` after `other` as RUL-17 names them: ISO date, note, else `null`. A bad date, blank note, note without date, or either when ruled is unreadable.
- [ ] [ABRD-56] An option line lists `other` right after `via`: the answer verbatim as `aco rulings --json` names it (RUL-16) when its `ruling` is `other`, else `null`. A yes/no line lists none.
- [ ] [ABRD-60] A line with `"form": "withdrawn"` is skipped unparsed, whatever its keys: no list shows it, its repo stays readable, the item's other lines keep their `index`, an item of only such is not listed.

An option line's keys are `index`, `form`, `text`, `question`, `problem`, `picture`,
`caption`, `decision_kind`, `area`, `topic`, `recommended`, `reason`, `options`, `ruling`,
`ruled_on`, `via`, `other`, `returned_on`, `returned_note`, `fingerprint`; each option is RUL-13's object. It has no `default`, no `example`
and no `card_hash`; pictures are SVG text as stored.

## The SPA shell

- [ ] [ABRD-22] `GET /` answers the committed shell and `GET /assets/**` its committed built files, no token needed; each refuses a method other than `GET` with 405 and `Allow: GET` (see E-ABRD-08).
- [ ] [ABRD-23] `GET /assets/**` answers only a regular file under the committed `static/` directory: a `..` segment, encoded or not, or an in-between symlink answers `not found`, like a missing file.
- [ ] [ABRD-24] Shell/assets CSP adds `script-src 'self'`, `style-src 'self'`, `img-src data:` to ABRD-12, no nonce/inline/external styles; built CSS is `text/css; charset=utf-8` (E-ABRD-08).
- [ ] [ABRD-25] `aco serve` refuses to start with `ERROR: <path> is missing; build the frontend first (...)` once the committed shell is absent, never binding a board that could only answer its API.
- [ ] [ABRD-26] `aco serve --json` is refused by the argument parser as plain text, never in the envelope: `aco: error: unrecognized arguments: --json`, exit `2` (see E-ABRD-09).
- [ ] [ABRD-27] The global `aco --repo OWNER/REPO` before `serve` is refused `ERROR: aco serve reads checkout directories; pass them as aco serve --repo PATH`, exit `2` (see E-ABRD-10).

## Never

- The board never writes a decision for a line it did not just read as open with the same shown fields: ABRD-02 compares before every write.
- An option's `--card-hash` is the hash the board just read from the line whose fingerprint was posted, and aco compares it again at its write (RULE-17).
- The board never sends `--via chat` or `--via default`. Its `--via board` is the cooperative record of `specs/rule.spec.md`'s Never, not proof that a person clicked.
- The board never runs two `aco rule` commands at once across any configured repo, and never starts one after stopping began (ABRD-03, ABRD-04, ABRD-17, ABRD-18).
- No answer carries an `Access-Control-*` header, so a page from another origin can neither read an answer nor send the token header (ABRD-10).
- The board never resolves a repo label from a request into a path: a label is only ever a lookup key among the repos `--repo` configured at start (ABRD-16).
- A card's fingerprint never satisfies another configured repo's check, even with identical line content: it binds the repo label it was read under (ABRD-21).

## Examples

`Setup: fake-aco` is a repository directory whose `aco` on PATH is a fake
answering `aco rulings --json` from a stored list and applying `aco rule`
to it with aco's own refusals, logging every call; `aco serve` runs
in that directory (E-ABRD-01 through E-ABRD-05: `--repo` not given, so the
one repo is labelled by that directory's name) and each example posts one
decision to it.

### E-ABRD-01 -- deciding later

Setup: fake-aco, item `#42` with one open line `Guests?`; the operator posts outcome `later` for card `#42` line `1`

```text
decide: #42 line 1, outcome later, the shown card's fingerprint
aco calls: aco rulings --json, then aco rule 42 --line 1 --later --json
answer: {"status": "ruled", "message": null}
```

### E-ABRD-02 -- a changed recommendation refuses the stale card

Setup: fake-aco, item `#42` line `1` shown with recommended outcome `yes`, then changed to `no` before the operator posts `yes` for that card

```text
decide: #42 line 1, outcome yes, the fingerprint of the card as first shown
aco calls: aco rulings --json only
answer: {"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}
```

### E-ABRD-03 -- listing the board

Setup: fake-aco, item `#42` titled `Share page` with open line `Guests?` recommending `yes`, and ruled line `Hosts?` (`no` on 2026-10-01)

```text
request: GET /api/board, header X-Board-Token: <start token>
aco calls: aco rulings --json
answer 200: {"repos": [{"name": "<repo>", "error": null, "items": [{"number": 42, "title": "Share page", "lines": [
  {"index": 1, "text": "Guests?", "question": null, "example": null, "picture": null,
   "default": "yes", "ruling": null, "ruled_on": null, "fingerprint": "<hex>"},
  {"index": 2, "text": "Hosts?", "question": null, "example": null, "picture": null,
   "default": null, "ruling": "no", "ruled_on": "2026-10-01", "fingerprint": "<hex>"}]}]}]}
```

### E-ABRD-04 -- deciding through the API

Setup: fake-aco, item `#42` with one open line `Guests?` as listed by `GET /api/board`

```text
request: POST /api/rule, header X-Board-Token: <start token>
body: {"repo": "<repo>", "item": 42, "line": 1, "fingerprint": "<as listed>", "outcome": "no", "note": null}
aco calls: aco rulings --json, then aco rule 42 --line 1 --no --json
answer 200: {"status": "ruled", "message": null}
```

### E-ABRD-05 -- a request without the token

Setup: fake-aco, item `#42` with one open line `Guests?`

```text
request: GET /api/board?t=<start token>, no X-Board-Token header
aco calls: none
answer 403: {"error": "forbidden: missing or wrong token"}
```

### E-ABRD-06 -- two repos, one down

Setup: `aco serve --repo a --repo b`; repo `a`'s fake-aco lists item `#42` with one open line `Guests?`; repo `b`'s fake-aco fails `aco rulings` with `ERROR: no forge adapter for host`

```text
request: GET /api/board, header X-Board-Token: <start token>
aco calls: aco rulings --json in a, aco rulings --json in b
answer 200: {"repos": [
  {"name": "a", "error": null, "items": [{"number": 42, "title": "Share page", "lines": [
    {"index": 1, "text": "Guests?", "question": null, "example": null, "picture": null,
     "default": null, "ruling": null, "ruled_on": null, "fingerprint": "<hex>"}]}]},
  {"name": "b", "error": "aco rulings failed: ERROR: no forge adapter for host", "items": []}]}
```

Had `a`'s fake-aco failed too, the answer would be 502 with the same two-entry `repos[]` envelope (ABRD-20).

### E-ABRD-07 -- a decision routes only into its named repo

Setup: `aco serve --repo a --repo b`; repo `a` and repo `b`'s fake-acos each list an identical item `#42` with one open line `Guests?`

```text
request: POST /api/rule, header X-Board-Token: <start token>
body: {"repo": "a", "item": 42, "line": 1, "fingerprint": "<as listed in a>", "outcome": "yes", "note": null}
aco calls: aco rule 42 --line 1 --yes --json in a; no call in b
answer 200: {"status": "ruled", "message": null}
```

Posting the same body with `"repo": "c"` -- not a configured repo -- answers 400 `{"error": "bad request: decision"}`, no call in `a` or `b`.

Posting it with `"repo": "b"` instead -- `a`'s own fingerprint, against `b`'s identical card -- answers 200 `{"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}`, no call in `a` or `b` (ABRD-21).

### E-ABRD-08 -- the shell and its assets need no token

Setup: fake-aco, item `#42` with one open line `Guests?`

```text
request: GET / (no X-Board-Token header, no token in the path at all)
aco calls: none
answer 200: the committed `static/index.html`, Content-Type text/html

request: GET /assets/index.js
aco calls: none
answer 200: the committed `static/assets/index.js`, Content-Type text/javascript

request: GET /assets/index.css
aco calls: none
answer 200: the committed stylesheet, Content-Type text/css; charset=utf-8

request: GET /assets/../server.py (a traversal attempt, literal or percent-encoded)
aco calls: none
answer 404: not found (text/plain) -- the same answer a missing asset gets (ABRD-23)
```

### E-ABRD-09 -- `--json` is no mode of this command

Setup: none

```console
$ aco serve --json
2> usage: aco [-h] [--version] [--repo REPO]
2>            {bootstrap,reset,status,board,serve,rulings,next,start,claim,release,land,adopt,rescope,cut,rule,check,brief,item}
2>            ...
2> aco: error: unrecognized arguments: --json
exit 2
```

### E-ABRD-10 -- the global `--repo` names a forge repository, not a checkout

Setup: none

```console
$ aco --repo overnightworks/aco serve
2> ERROR: aco serve reads checkout directories; pass them as aco serve --repo PATH
exit 2
```

### E-ABRD-11 -- listing an option line beside a yes/no line

Setup: fake-aco, item `#12` titled `Song jump` with E-RUL-07's open option line, and item `#42` titled `Share page` with open line `Guests?` recommending `yes`

```text
request: GET /api/board, header X-Board-Token: <start token>
aco calls: aco rulings --json
answer 200: {"repos": [{"name": "<repo>", "error": null, "items": [{"number": 12, "title": "Song jump", "lines": [
  {"index": 1, "form": "options", "text": "The song stays open on the jump.",
   "question": "Keep the song open?", "problem": "The jump closes your song.",
   "picture": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>", "caption": "Today",
   "decision_kind": "product", "area": "Song page", "topic": "Jump", "recommended": "A",
   "reason": "Ends the loss.", "options": [
    {"letter": "A", "name": "Song stays open", "effect": "The app jumps itself.",
     "picture": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>", "caption": "Still open",
     "notice": "You stay in your song.", "cost": "More code.", "undo": "reversible",
     "undo_how": "Any time.", "contract": "The song stays open."},
    {"letter": "B", "name": "As today", "effect": "The browser jumps.", "same_as_today": true,
     "notice": "You pick the song again.", "cost": "None.", "undo": "final",
     "undo_how": "Nothing is built.", "contract": "The link stays a link."}],
   "ruling": null, "ruled_on": null, "via": null, "other": null, "returned_on": null, "returned_note": null, "fingerprint": "<hex>"}]},
  {"number": 42, "title": "Share page", "lines": [
  {"index": 1, "text": "Guests?", "question": null, "example": null, "picture": null,
   "default": "yes", "ruling": null, "ruled_on": null, "fingerprint": "<hex>"}]}]}]}
```

Posting `yes` for `#12` line `1` with the listed fingerprint still forwards `--yes` to `aco rule` until the board's argv path is re-pointed (K2); aco refuses the call as a usage error (one of the arguments `--option --other` is required), exit `2`, and the board answers 200 `{"status": "failed"}` carrying aco's message, with no write.

### E-ABRD-12 -- deciding an option line

Setup: fake-aco, item `#12` titled `Song jump` with E-RUL-07's open option line; the operator posts option `A` for that card

```text
request: POST /api/rule, header X-Board-Token: <start token>
body: {"repo": "<repo>", "item": 12, "line": 1, "fingerprint": "<as listed>", "option": "A"}
aco calls: aco rulings --json, then aco rule 12 --line 1 --option A --via board --card-hash=<card_hash of that line> --json
answer 200: {"status": "ruled", "message": null}
```

Posting the same body after aco answers `card_changed` (RULE-17) because the card changed between the board's read and aco's write answers 200 `{"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}`; the stored line is unchanged.

### E-ABRD-13 -- answering an option line with Other

Setup: fake-aco, item `#12` titled `Song jump` with E-RUL-07's open option line; the operator posts his own answer for that card

```text
request: POST /api/rule, header X-Board-Token: <start token>
body: {"repo": "<repo>", "item": 12, "line": 1, "fingerprint": "<as listed>", "other": "  Nur am Desktop.  "}
aco calls: aco rulings --json, then aco rule 12 --line 1 --other=Nur am Desktop. --via board --card-hash=<card_hash of that line> --json
answer 200: {"status": "ruled", "message": null}
```

A blank answer, one past 280 characters after trimming, or one beside `outcome`, `option` or `note` answers 400 `{"error": "bad request: decision"}` and runs no `aco` call.

### E-ABRD-14 -- sending an option line back to its head

Setup: fake-aco, item `#12` titled `Song jump` with E-RUL-07's open option line; the operator posts Unclear with a note

```text
request: POST /api/rule, header X-Board-Token: <start token>
body: {"repo": "<repo>", "item": 12, "line": 1, "fingerprint": "<as listed>", "unclear": true, "note": "  Mobile fehlt.  "}
aco calls: aco rulings --json, then aco rule 12 --line 1 --unclear --note=Mobile fehlt. --card-hash=<card_hash of that line> --json
answer 200: {"status": "ruled", "message": null}
```

The line stays open, now with its head. Posting Unclear again answers 200 `{"status": "failed", "message": "aco rule failed: line 1 is already with its head; it comes back once revised"}`. An `unclear` that is not `true`, or one beside `outcome`, `option` or `other`, or a note past 280 characters after trimming, answers 400 `{"error": "bad request: decision"}` and runs no `aco` call.
