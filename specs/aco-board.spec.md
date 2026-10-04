# `aco-board serve`

`aco-board serve` (issues #617, #620) shows a repository's open
expectation lines on a loopback page and writes each decision through the
installed `aco` command line, never through aco's own modules. This file
owns the board's decision rules: which outcomes it writes, when it refuses
a decision, how writes are ordered and stopped, and the note it may carry.
It cites the read shape `specs/rulings.spec.md` owns (RUL-10) and the write
`specs/rule.spec.md` owns (RULE-01, RULE-03) rather than restating them.
It also owns the JSON API under `/api/` -- its shapes, token, and
headers; the legacy page at `/` and `POST /rule` is not specified here.
`<n>` is an item number, `<k>` an expectation line's 1-based index.

## Behavior table

| state \ trigger | load the page | decide a shown card |
|---|---|---|
| an open line | ABRD-06 | ABRD-01 |
| the line's shown fields changed since the page was built | ABRD-06 | ABRD-02 |
| a ruled line | ABRD-06 | RULE-04 |
| a second decision while one is being written | — | ABRD-03 |
| the board is stopping | — | ABRD-04 |
| a note on the decision | — | ABRD-05 |
| `aco rulings --json` names a field outside its shape | ABRD-07 | ABRD-07 |
| `aco rulings` fails or hangs | ABRD-11 | ABRD-11 |
| an `/api/` request without the right token | ABRD-10 | ABRD-10 |

## Writing a decision

- [ ] [ABRD-01] Deciding a shown open card with outcome `yes`, `no`, or `later` runs `aco rule <n> --line <k>` with `--yes`, `--no`, or `--later` and `--json` (see E-ABRD-01).
- [ ] [ABRD-02] A card whose title, text, question, example, picture, or recommended outcome changed since it was shown is refused `Diese Zeile hat sich geändert, bitte neu laden`, no `aco rule` run (see E-ABRD-02).
- [ ] [ABRD-03] The board runs one `aco rule` at a time; a decision arriving meanwhile waits. Decisions on distinct lines are both stored; on the same line, the later one answers `already_ruled` (RULE-04).
- [ ] [ABRD-04] Stopping the board waits for an `aco rule` already running; a decision still waiting for its turn or arriving after stopping began is refused `board is shutting down`, no `aco rule` run.
- [ ] [ABRD-05] A note is at most `280` characters after trimming, holds no NUL, and is valid UTF-8; any other note refuses the decision before any `aco` call; a blank note is no note.

## Reading the lines

- [ ] [ABRD-06] Every page load reads `aco rulings --json` afresh and shows each line whose `ruling` is `null` as a card, in aco's own order; the board keeps no copy.
- [ ] [ABRD-07] A line whose `default` or `ruling` is neither `null` nor `yes`/`no`/`later`, or whose `ruled_on` is neither `null` nor an ISO date, shows `aco rulings --json is unreadable: <detail>` instead of cards.

## The JSON API

- [ ] [ABRD-08] `GET /api/board` answers `{"items": [{"number", "title", "lines"}]}` in aco's order; each line has `index, text, question, example, picture, default, ruling, ruled_on, fingerprint` (see E-ABRD-03).
- [ ] [ABRD-09] `POST /api/rule` takes `item`, `line`, `fingerprint`, `outcome`, `note` and answers 200 `{"status", "message"}`; a malformed body answers 400 `{"error": "bad request: decision"}` (see E-ABRD-04).
- [ ] [ABRD-10] Every `/api/` request, any method, needs exactly one `X-Board-Token` header with the start token, else 403 `{"error": "forbidden: missing or wrong token"}` before any `aco` call (see E-ABRD-05).
- [ ] [ABRD-11] A body not complete 10 seconds after its headers, however it trickles, answers 408 `{"error": "request timeout: body incomplete"}`; a failing or hung `aco rulings` answers 502 `{"error": "<reason>"}`.
- [ ] [ABRD-12] Every answer, HTTP-layer refusals included, carries `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and a CSP with `base-uri`, `form-action`, and `frame-ancestors` set to `'none'`.
- [ ] [ABRD-13] With the token, an `/api/` method other than `GET` or `POST` answers 405 `{"error": "method not allowed"}`; elsewhere such a method answers 405 as text.

## Never

- The board never writes a decision for a line it did not just read as open with the same shown fields: ABRD-02 compares before every write.
- The board never runs two `aco rule` commands at once, and never starts one after stopping began (ABRD-03, ABRD-04).
- No answer carries an `Access-Control-*` header, so a page from another origin can neither read an answer nor send the token header (ABRD-10).
- A missing `default` key is never unreadable: a line from an aco whose RUL-10 rows do not yet carry that field has no recommended outcome.

## Examples

`Setup: fake-aco` is a repository directory whose `aco` on PATH is a fake
answering `aco rulings --json` from a stored list and applying `aco rule`
to it with aco's own refusals, logging every call; `aco-board serve` runs
in that directory and each example posts one decision to it.

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
answer 200: {"items": [{"number": 42, "title": "Share page", "lines": [
  {"index": 1, "text": "Guests?", "question": null, "example": null, "picture": null,
   "default": "yes", "ruling": null, "ruled_on": null, "fingerprint": "<hex>"},
  {"index": 2, "text": "Hosts?", "question": null, "example": null, "picture": null,
   "default": null, "ruling": "no", "ruled_on": "2026-10-01", "fingerprint": "<hex>"}]}]}
```

### E-ABRD-04 -- deciding through the API

Setup: fake-aco, item `#42` with one open line `Guests?` as listed by `GET /api/board`

```text
request: POST /api/rule, header X-Board-Token: <start token>
body: {"item": 42, "line": 1, "fingerprint": "<as listed>", "outcome": "no", "note": null}
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
