# `aco-board serve`

`aco-board serve --repo PFAD...` (issues #617, #620, #637, #652) shows one or
more repositories' open expectation lines in a browser SPA and writes each
decision through the installed `aco` command line, never through aco's own
modules; without `--repo`, the current directory is the one repository
served. This file owns the board's decision rules: which outcomes it writes,
when it refuses a decision, how writes are ordered and stopped, and the note
it may carry -- across every configured repository, since one write turn and
one drain span all of them. It cites the read shape `specs/rulings.spec.md`
owns (RUL-10) and the write `specs/rule.spec.md` owns (RULE-01, RULE-03)
rather than restating them. It also owns the JSON API under `/api/` -- its
shapes, token, and headers -- and the shell's own delivery contract (who may
fetch it, and how it is contained to its own files); the SPA's own behaviour
once loaded is `frontend/`'s. `<n>` is an item number, `<k>` an expectation
line's 1-based index, `<repo>` a configured repository's label -- the
resolved directory's name.

## Behavior table

| state \ trigger | load the page | decide a shown card |
|---|---|---|
| an open line | ABRD-06 | ABRD-01 |
| the line's shown fields changed since the page was built | ABRD-06 | ABRD-02 |
| a ruled line | ABRD-06 | RULE-04 |
| a second decision while one is being written, in any configured repo | — | ABRD-03, ABRD-17 |
| the board is stopping | — | ABRD-04, ABRD-18 |
| a note on the decision | — | ABRD-05 |
| `aco rulings --json` names a field outside its shape | ABRD-07 | ABRD-07 |
| one configured repo's `aco rulings` fails or hangs | ABRD-15 | ABRD-15 |
| every configured repo's `aco rulings` fails or hangs | ABRD-20 | ABRD-20 |
| an `/api/` request without the right token | ABRD-10 | ABRD-10 |
| a decision naming a repo outside the configured ones | — | ABRD-16 |
| a card's fingerprint submitted against a different configured repo | — | ABRD-21 |

## Writing a decision

- [ ] [ABRD-01] Deciding a shown open card with outcome `yes`, `no`, or `later` runs `aco rule <n> --line <k>` with `--yes`, `--no`, or `--later` and `--json` (see E-ABRD-01).
- [ ] [ABRD-02] A card whose title, text, question, example, picture, or recommended outcome changed since it was shown is refused `Diese Zeile hat sich geändert, bitte neu laden`, no `aco rule` run (see E-ABRD-02).
- [ ] [ABRD-03] The board runs one `aco rule` at a time; a decision arriving meanwhile waits. Decisions on distinct lines are both stored; on the same line, the later one answers `already_ruled` (RULE-04).
- [ ] [ABRD-04] Stopping the board waits for an `aco rule` already running; a decision still waiting for its turn or arriving after stopping began is refused `board is shutting down`, no `aco rule` run.
- [ ] [ABRD-05] A note is at most `280` characters after trimming, holds no NUL, and is valid UTF-8; any other note refuses the decision before any `aco` call; a blank note is no note.

## Reading the lines

- [ ] [ABRD-06] Every page load reads `aco rulings --json` afresh, for every configured repo, and shows each line whose `ruling` is `null` as a card, in aco's own order within its repo; the board keeps no copy.
- [ ] [ABRD-07] A line whose `default` or `ruling` is neither `null` nor `yes`/`no`/`later`, or whose `ruled_on` is neither `null` nor an ISO date, shows `aco rulings --json is unreadable: <detail>` instead of cards.

## Multiple repositories

- [ ] [ABRD-14] `aco-board serve --repo PFAD` (repeatable) configures the repos served, labelled `<repo>` by each resolved directory's name; without `--repo`, the current directory is the one repository.
- [ ] [ABRD-15] `GET /api/board` and the legacy page answer once any repo's read succeeded; a failed repo carries its own error sentence and no items or cards, others unaffected (see E-ABRD-06).
- [ ] [ABRD-16] A decision naming a `repo` outside the configured labels is refused `bad request: decision` before any `aco` call (see E-ABRD-07).
- [ ] [ABRD-17] The one write turn (ABRD-03) spans every configured repo: a decision for one repo never writes while another repo's decision is being written (see E-ABRD-07).
- [ ] [ABRD-18] Stopping the board (ABRD-04) drains every repo: it waits for a running `aco rule` in any one, and refuses a waiting decision in any repo once stopping begins, without waiting for the running one.
- [ ] [ABRD-19] A `--repo` path that is not a directory is a usage error; two resolved paths with the same label refuse the start with `ERROR: two repositories named <repo>: <p1>, <p2>`.
- [ ] [ABRD-21] A card's fingerprint binds the `repo` it was read under; posted against another configured repo, identical content included, it is refused like a changed line (see E-ABRD-07).

## The JSON API

- [ ] [ABRD-08] `GET /api/board` answers `{"repos": [{"name", "error", "items"}]}` in order; `items` as before (E-ABRD-03); `error` is `null` once read, else aco's failure sentence, `items: []` (E-ABRD-06).
- [ ] [ABRD-09] `POST /api/rule` takes `repo`, `item`, `line`, `fingerprint`, `outcome`, `note`; answers 200 `{"status", "message"}`, else 400 `{"error": "bad request: decision"}` (E-ABRD-04, E-ABRD-07).
- [ ] [ABRD-10] Every `/api/` request, any method, needs exactly one `X-Board-Token` header with the start token, else 403 `{"error": "forbidden: missing or wrong token"}` before any `aco` call (see E-ABRD-05).
- [ ] [ABRD-11] A body not complete 10 seconds after its headers, however it trickles, answers 408 `{"error": "request timeout: body incomplete"}`.
- [ ] [ABRD-20] Once every configured repo's `aco rulings` fails or hangs, `GET /api/board` answers 502 with the same `repos[]` envelope as ABRD-08, each entry its own reason (E-ABRD-06).
- [ ] [ABRD-12] Every answer, HTTP-layer refusals included, carries `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and a CSP with `base-uri`, `form-action`, and `frame-ancestors` set to `'none'`.
- [ ] [ABRD-13] With the token, an `/api/` method other than `GET` or `POST` answers 405 `{"error": "method not allowed"}` with `Allow` naming the route; elsewhere it answers 405 as text with the same header.

## The SPA shell

- [ ] [ABRD-22] `GET /` answers the committed shell and `GET /assets/**` its committed built files, no token needed; each refuses a method other than `GET` with 405 and `Allow: GET` (see E-ABRD-08).
- [ ] [ABRD-23] `GET /assets/**` answers only a regular file under the committed `static/` directory: a `..` segment, encoded or not, or an in-between symlink answers `not found`, like a missing file.
- [ ] [ABRD-24] The CSP on the shell and its assets carries no nonce: `script-src 'self'` (its one script loads from `/assets/`) and `img-src data:`, alongside ABRD-12's own directives.
- [ ] [ABRD-25] `aco-board serve` refuses to start with `ERROR: <path> is missing; build the frontend first (...)` once the committed shell is absent, never binding a board that could only answer its API.

## Never

- The board never writes a decision for a line it did not just read as open with the same shown fields: ABRD-02 compares before every write.
- The board never runs two `aco rule` commands at once across any configured repo, and never starts one after stopping began (ABRD-03, ABRD-04, ABRD-17, ABRD-18).
- No answer carries an `Access-Control-*` header, so a page from another origin can neither read an answer nor send the token header (ABRD-10).
- A missing `default` key is never unreadable: a line from an aco whose RUL-10 rows do not yet carry that field has no recommended outcome.
- The board never resolves a repo label from a request into a path: a label is only ever a lookup key among the repos `--repo` configured at start (ABRD-16).
- A card's fingerprint never satisfies another configured repo's check, even with identical line content: it binds the repo label it was read under (ABRD-21).

## Examples

`Setup: fake-aco` is a repository directory whose `aco` on PATH is a fake
answering `aco rulings --json` from a stored list and applying `aco rule`
to it with aco's own refusals, logging every call; `aco-board serve` runs
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

Setup: `aco-board serve --repo a --repo b`; repo `a`'s fake-aco lists item `#42` with one open line `Guests?`; repo `b`'s fake-aco fails `aco rulings` with `ERROR: no forge adapter for host`

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

Setup: `aco-board serve --repo a --repo b`; repo `a` and repo `b`'s fake-acos each list an identical item `#42` with one open line `Guests?`

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

request: GET /assets/../server.py (a traversal attempt, literal or percent-encoded)
aco calls: none
answer 404: not found (text/plain) -- the same answer a missing asset gets (ABRD-23)
```
