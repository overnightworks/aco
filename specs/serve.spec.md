# `aco serve`

`aco serve --repo PATH...` shows one or
more repositories' open expectation lines in a browser SPA and writes each
decision in process, through aco's own library: it lists the rows `aco rulings`
lists and writes through the writer `aco rule` uses; without `--repo`, the
current directory is the one repository
served. This file owns the board's decision rules: which answers it writes,
when it refuses a decision, how writes are ordered and stopped, and the note
it may carry -- across every configured repository, since one write turn and
one drain span all of them. It cites the read shape `specs/rulings.spec.md`
owns (RUL-10) and the write `specs/rule.spec.md` owns (RULE-01, RULE-14, RULE-20, RULE-29)
rather than restating them. It also owns the JSON API under `/api/` -- its
shapes, token, and headers -- and the shell's own delivery contract (who may
fetch it, and how it is contained to its own files); the SPA's own behaviour
once loaded is `frontend/`'s. `<n>` is an item number, `<k>` an expectation
line's 1-based index, `<repo>` a configured repository's label -- the
resolved directory's name.

## Behavior table

| state \ trigger | load the page | decide a shown card |
|---|---|---|
| an open line | ABRD-06 | ABRD-58, ABRD-59 |
| the line's shown fields changed since the page was built | ABRD-06 | ABRD-02 |
| a ruled option line | ABRD-06, ABRD-37, ABRD-54, ABRD-57 | RULE-04 |
| a ruled yes/no line | ABRD-30, ABRD-37, ABRD-54 | — (read-only) |
| an item whose block is malformed or unreadable | ABRD-07 | ABRD-41 |
| an item with open option lines | ABRD-82 | ABRD-77 |
| an item with two or more open option lines | ABRD-83, ABRD-84, ABRD-85 | ABRD-86, ABRD-87, ABRD-88, ABRD-89, ABRD-90, ABRD-91, ABRD-92 |
| an option line, open or ruled | ABRD-34, ABRD-53, ABRD-56, ABRD-61, ABRD-62, ABRD-36, ABRD-37, ABRD-38, ABRD-43, ABRD-44, ABRD-45, ABRD-46, ABRD-47, ABRD-63, ABRD-65, ABRD-66, ABRD-67, ABRD-68, ABRD-69, ABRD-72, ABRD-73, ABRD-74, ABRD-75, ABRD-76 | ABRD-78 |
| a withdrawn line | ABRD-60 | ABRD-41 |
| a post without `lines` | — | ABRD-40 |
| its card changed, withdrawn, gone or closed since the page read it | — | ABRD-41 |
| a card post answering `other` | — | ABRD-64 |
| a card post answering `unclear` | — | ABRD-70, ABRD-71 |
| a card post naming every open option line of its item | — | ABRD-77, ABRD-78, ABRD-80 |
| a card post missing an open option line, or naming a changed or non-option line | — | ABRD-79 |
| a card post naming a line already ruled | — | ABRD-80 |
| a malformed card post | — | ABRD-81 |
| a second decision while one is being written, in any configured repo | — | ABRD-03, ABRD-17 |
| the board is stopping | — | ABRD-04, ABRD-18 |
| a note or an answer on the decision | — | ABRD-05 |
| one configured repo's read fails or times out | ABRD-15 | ABRD-15 |
| every configured repo's read fails or times out | ABRD-20 | ABRD-20 |
| an `/api/` request without the right token | ABRD-10 | ABRD-10 |
| a decision naming a repo outside the configured ones | — | ABRD-16 |
| a card's fingerprint submitted against a different configured repo | — | ABRD-21 |
| `aco serve --json` | ABRD-26 | — |
| the global `aco --repo OWNER/REPO` before `serve` | ABRD-27 | — |

## Writing a decision

- ABRD-01 (removed 29.10.2026): the board writes no yes/no outcome; a card post is one write of its item (ABRD-78).
- [ ] [ABRD-02] A card whose shown fields (an option line's `card_hash`, ABRD-35) changed since shown is refused on its fresh read `Diese Zeile hat sich geändert, bitte neu laden`, nothing written (E-ABRD-02).
- [ ] [ABRD-03] The board writes one decision at a time; a decision arriving meanwhile waits. Decisions on distinct lines are both stored; on the same line, the later one answers `already_ruled` (RULE-04).
- [ ] [ABRD-04] Stopping the board waits for a write already running; a decision still waiting for its turn or arriving after stopping began is refused `board is shutting down`, nothing written.
- [ ] [ABRD-05] A note or answer is at most `280` characters after trimming, holds no NUL, and is valid UTF-8; any other refuses it before any forge request; a blank note is no note, a blank answer is refused.
- ABRD-39 (removed 30.10.2026): there is no argv; the hash stored is the fresh read's (ABRD-78).
- [ ] [ABRD-40] A post without `lines` answers 400 `bad request: decision`, no forge request (ABRD-77).
- [ ] [ABRD-41] A card changed, withdrawn, gone, closed or unreadable on its fresh read is `failed` `Diese Zeile hat sich geändert, bitte neu laden`; a ruled line `already_ruled`; else `failed`, aco's sentence.
- ABRD-42 (removed 29.10.2026): folded into ABRD-40.

- [ ] [ABRD-77] A post with `lines` decides one card: `repo`, `item`, and `lines` of `{"line", "fingerprint"}`, each with its own `option`, or one `other` or `unclear` for all (card key rules, see E-ABRD-15).
- [ ] [ABRD-78] It reads item `<n>` once and writes its body once through aco's writer: every posted line, `via board` for an option or `other`, each with that read's card hash, or every line back to its head.
- [ ] [ABRD-79] A card post is refused as ABRD-02 on the fresh read, nothing written, unless each posted line reads as an option line, each open one with its posted fingerprint, and every open option line is posted.
- [ ] [ABRD-80] A posted line already ruled is left to aco's writer: RULE-04 refuses the whole card `already_ruled`, the answer maps once as ABRD-41 and ABRD-71 say, and aco stores all lines or none (RULE-29).
- [ ] [ABRD-81] A card post that breaks the card key rules (no line, a line named twice, a misplaced or unknown key, not exactly one answer kind) answers 400 `bad request: decision`, no forge request.

The card key rules: `lines` is a non-empty list of objects, each with a positive `line` named once and a string `fingerprint`. An entry holds only `line`, `fingerprint` and an optional `option`; any other key in an entry refuses, and an entry's `option`, when present, is `A`-`D`; `null` refuses. Either every entry carries an `option` `A`-`D` and the post names no `other`, `unclear` or `note`, or no entry does and the post names exactly one of `other` (ABRD-05, no `note`) or `unclear` (literally `true`, an optional note, a blank one none). Beside `lines`, a top-level `line`, `fingerprint`, `option` or `outcome` refuses, even when `null`; for `other`, `unclear` and `note` an absent key and `null` name nothing.

## Reading the lines

- [ ] [ABRD-06] Each page load reads one open-item listing per configured repo and shows each open line in RUL-03's order, option lines as one card per item (ABRD-82); no copy is kept.
- [ ] [ABRD-07] An item whose block aco's grammar refuses, or that the store cannot read, is not listed, as RUL-20; its repository stays readable.

## Browser decision flow

- [ ] [ABRD-28] The decision list groups open rows by repository under its name and count; a row shows its state shape and an option card's name (ABRD-82).
- [ ] [ABRD-29] Within a repository, option cards come in aco's order, with-head cards after (ABRD-61). First load selects the first row; desktop shows its card, phones the list until a row is tapped.
- [ ] [ABRD-30] Decided groups the ruled lines of open board items by repository under its name and count; a row shows the Decided shape and an option line's topic, or a yes/no line's short question or sentence.
- [ ] [ABRD-31] Within a repository, Decided lists the newest date first, then item number and line index descending; with no ruled line and no failed repository it reads `Nothing decided yet`.
- [ ] [ABRD-32] Opening Decided selects its first row: its card on desktop, the list on phones. Returning to Open keeps its selection, list position and phone view; a background decision displaces neither view.
- [ ] [ABRD-33] During undo a question stays open; only successful storage and reload move it to Decided.
- [ ] [ABRD-36] A card with one open option line shows: repository, area, kind, `with head` (ABRD-61), `reversible` or `final`, question, Problem, Today, options A-D, Recommendation and Decide (ABRD-44).
- [ ] [ABRD-37] A selected ruled line shows the decided card: meta, question, Decided (`A — name`, `Ja`, `Nein`, `Später` or ABRD-57), How (ABRD-54) and Contract behind `Show` with its binding sentences and source.
- [ ] [ABRD-54] How reads `Board`, `From chat` or `Recommendation kept – no answer` for an option line's `via` (ABRD-53), `not recorded` for a yes/no line; then ` · ` and the ruling date as `DD.MM.YYYY`.
- [ ] [ABRD-57] A line ruled `other` shows Decided as `Other: „<answer>“` and binds that answer alone behind Contract's `Show`; How reads as ABRD-54; Open never lists it, Decided does (ABRD-30).
- [ ] [ABRD-38] Each option on an option card is a button that opens its Result (picture or `= TODAY`), You notice, Cost, Undo and Contract behind `Show`; opening one closes the other.
- [ ] [ABRD-43] Each Today and Result picture on an option card is an `Enlarge picture` button opening it with its caption in a modal dialog; `Close` or `Esc` closes it and focus returns to the button.
- [ ] [ABRD-44] A one-point card's Decide row has one pick per option, the recommended one in the accent; a pick waits out the undo window, then posts the card (ABRD-77); once stored, it moves to Decided.
- [ ] [ABRD-45] A refused post shows its sentence in the Decide row; "changed" (ABRD-02) or "already ruled" hide the picks and `Accept all` behind `Neu laden`, and any other failure keeps them.
- [ ] [ABRD-46] A `final` pick first opens a modal `Decide <X>?` with its Undo consequence and the warn mark, focus on `Cancel`; `Decide <X>` records it, and the window starts once every point is chosen (ABRD-87).
- [ ] [ABRD-47] `Cancel` or `Esc` closes the confirm, posts nothing and returns focus to the pick; `Decide <X>` keeps the card as shown when the confirm opened, so a card changed since is refused (ABRD-02).
- [ ] [ABRD-58] A one-point card's pick shows a strip above it for its 8 s window: the Decided shape, `Decided: <letter> — <option> · <topic>` and `Undo`, in view as the card scrolls and atop a phone's list.
- [ ] [ABRD-59] A pick that starts a window focuses its strip's `Undo`, so Enter undoes it; `Undo` cancels the post and focuses the shown card, else the list. An ended window removes its strip; ABRD-50 applies.
- [ ] [ABRD-48] Option card rows carry the Open or With head (ABRD-61) shape; each shape names its state, each row's title is its question or name (ABRD-82).
- [ ] [ABRD-61] A card with a line carrying `returned_on` is with its head: Open lists it muted, with the With head shape (ring, back chevron), after other option cards; it shows `with head`. Decide stays.
- [ ] [ABRD-49] Readable repositories with nothing open are named once under `Nothing open:`; with no open line and no failed repository the list reads `All decided`.
- [ ] [ABRD-50] Once the shown card's decision is stored, the stage moves to the list's first open option card, else to its first row; a card selected meanwhile stays (ABRD-32).
- [ ] [ABRD-51] A 56 px header (52 px on phones) holds the brand `Entscheidungs-Board` and the tabs `Open n` and `Decided n`: n counts the open list's rows and the ruled lines Decided lists.
- [ ] [ABRD-55] On phones a tapped row's card fills the pane without its card frame, under a header whose `‹ Open` or `‹ Decided` returns to that list with the row focused; the tabs hide meanwhile.
- [ ] [ABRD-63] An open option card's Decide row ends in `Other…`, beside the picks or `Accept all`; it opens a panel with a textarea (`Your answer`, up to 280 characters, focused) and `Send`, disabled while blank.
- [ ] [ABRD-64] A card post's `other` (ABRD-78) is the trimmed answer within ABRD-05, written once for every posted line with `via board` (E-ABRD-13).
- [ ] [ABRD-65] `Other…` and `Send` hide with the picks and `Accept all` (ABRD-45), disable while a decision on the card waits and ignore clicks while the board reloads, so a pick and an Other never both post.
- [ ] [ABRD-66] The typed answer is kept per card: closing the panel, switching cards, `Undo` and a failed post keep it; `Undo` reopens the panel with it, and a stored decision drops it.
- [ ] [ABRD-67] `Send` closes the panel and starts the undo window with the strip `Decided: Other · <name>` (ABRD-82) and `Undo` (ABRD-58, ABRD-59); `Undo` posts nothing.
- [ ] [ABRD-68] `Send` posts the card as shown when the panel opened, so a card changed since is refused (ABRD-02); the answer stays in the draft.
- [ ] [ABRD-69] A card that is with its head (ABRD-61) offers `Other…` as any open option card does.
- [ ] [ABRD-70] A card post's `unclear` (ABRD-78) stores no `via`; its note is trimmed, a blank one is none, and every posted line returns to its head (E-ABRD-14).
- [ ] [ABRD-71] An `unclear` aco stores answers 200 `{"status": "returned", "message": null}`: the line stays open, with its head; only a stored `option` or `other` answers `ruled`.
- [ ] [ABRD-72] An open option card's Decide row ends with `Other…` and `Unclear`; a card with its head (ABRD-61) shows no `Unclear` and no Unclear panel, and keeps its picks and `Other…`.
- [ ] [ABRD-73] `Unclear` opens the panel with one focused textarea (`What is unclear? (optional)`, at most 280 characters) and `Send`, enabled while blank; it closes `Other…`'s panel; each keeps its draft.
- [ ] [ABRD-74] `Send` closes the panel and starts the window with a grey strip: the With head shape, `With head: <name>` (ABRD-82) and `Undo` (ABRD-59); `Undo` posts nothing and reopens the panel with the note.
- [ ] [ABRD-75] After the window it posts the card with `unclear` and the trimmed note, none if blank (ABRD-77); `Unclear` locks, and posting and refusal follow ABRD-65, ABRD-66 and ABRD-68 for `Other…`.
- [ ] [ABRD-76] Once the post answers `returned` (ABRD-71), the stage moves to the list's first Open row, else stays on the card, now with its head; a card selected meanwhile stays (ABRD-32).
- [ ] [ABRD-82] An item's open option lines (its points) are one card with one Open row and one name: a one-point card's topic, else `<area> · <n> points`, distinct areas joined by ` / ` in point order.
- [ ] [ABRD-83] A card of two or more points has its name as title and no Problem; its meta reads `<repo> › ` with ABRD-82's areas, its distinct kinds, `with head` (ABRD-61), `final` or `reversible`.
- [ ] [ABRD-84] Its points are rows in aco's order: `<k>`, the question, a warn mark when an option is `final`, one pick per option (the recommended one in the accent); no point is open at first.
- [ ] [ABRD-85] Activating a point's question opens its Problem, Today, Options and Recommendation as on a one-point card and closes any other point; activating it again closes it.
- [ ] [ABRD-86] A pick marks its point chosen (`aria-pressed`) and posts nothing; the Decide row reads `<c> of <n> chosen` on desktop; a pick on the open point opens the first unchosen point instead.
- [ ] [ABRD-87] Once every point is chosen, the undo window starts with one strip `Decided: 1A 2B … · <name>` and `Undo`, which posts nothing and clears the picks; then the card posts every pick (ABRD-77).
- [ ] [ABRD-88] A point's pick on a `final` option first asks as ABRD-46, its line reading `Point <k>: <consequence>`; `Cancel` leaves the point as it was.
- [ ] [ABRD-89] `Accept all` leads a card of points' Decide row, in the accent: it picks each recommended letter, replacing earlier picks, and starts ABRD-87's window, after ABRD-90's confirm where one applies.
- [ ] [ABRD-90] When a recommended option is `final`, `Accept all` first asks `Accept all recommendations?` with `Point <k>: <consequence>` per such point, focus on `Cancel`; `Cancel` or `Esc` posts nothing.
- [ ] [ABRD-91] Picks keep their points as shown and the post names those fingerprints, so a point changed, added or ruled since is refused (ABRD-79, ABRD-80); a re-read drops a changed point's pick.
- [ ] [ABRD-92] `Other…` and `Unclear` answer a card of points with one text: strips `Decided: Other · <name>` and `With head: <name>`; each posts every point of the card (ABRD-77).
- [ ] [ABRD-52] An option card's Decide row sticks to the pane's foot while the card runs on beneath it and then casts a shadow over that content; at the card's end it rests in place without one.

The browser proofs are `frontend/e2e/decide.spec.ts`,
`frontend/e2e/decideOption.spec.ts`, `frontend/e2e/decided.spec.ts`, `frontend/e2e/escapeRow.spec.ts`,
`frontend/e2e/groupCard.spec.ts`, `frontend/e2e/openList.spec.ts`, `frontend/e2e/optionCard.spec.ts`, `frontend/e2e/pageFrame.spec.ts`, `frontend/e2e/pictureEnlargement.spec.ts`,
`frontend/e2e/unclear.spec.ts` and `frontend/e2e/withHead.spec.ts`; ordering is additionally proven by
`frontend/src/app/model/boardSummary.test.ts`.

## Multiple repositories

- [ ] [ABRD-14] `aco serve --repo PATH` (repeatable) configures the repos served, labelled `<repo>` by each resolved directory's name; without `--repo`, the current directory is the one repository.
- [ ] [ABRD-15] `GET /api/board` answers once any repo's read succeeded; a repo whose read fails, a gh or git call past its bound included, carries its own sentence and no items, others unaffected (E-ABRD-06).
- [ ] [ABRD-16] A decision naming a `repo` outside the configured labels is refused `bad request: decision` before any forge request (see E-ABRD-07).
- [ ] [ABRD-17] The one write turn (ABRD-03) spans every configured repo: a decision for one repo never writes while another repo's decision is being written (see E-ABRD-07).
- [ ] [ABRD-18] Stopping the board (ABRD-04) drains every repo: it waits for a running write in any one, and refuses a waiting decision in any repo once stopping begins, without waiting for the running one.
- [ ] [ABRD-19] A `--repo` path that is not a directory is a usage error; two resolved paths with the same label refuse the start with `ERROR: two repositories named <repo>: <p1>, <p2>`.
- [ ] [ABRD-21] A card's fingerprint binds the `repo` it was read under; posted against another configured repo, identical content included, it is refused like a changed line (see E-ABRD-07).

## The JSON API

- [ ] [ABRD-08] `GET /api/board` answers `{"repos": [{"name", "error", "items"}]}` in order; `items`: RUL-03's rows as `{"number", "title", "lines"}` (E-ABRD-03); `error`: `null` or a sentence, no items (E-ABRD-06).
- [ ] [ABRD-09] `POST /api/rule` takes a card (ABRD-77); 200 `{"status", "message"}`, else 400 `bad request: decision` (E-ABRD-04, -07, -12..15).
- [ ] [ABRD-10] Every `/api/` request, any method, needs exactly one `X-Board-Token` header with the board token, else 403 `{"error": "forbidden: missing or wrong token"}` before any forge request (see E-ABRD-05).
- [ ] [ABRD-93] The board token lives in a file, `$XDG_STATE_HOME/aco/board-token` when that value is an absolute path, else `~/.local/state/aco/board-token`; `aco serve` reads it before binding.
- [ ] [ABRD-94] An absent token file is created with a fresh token: file mode `0600`, every missing directory `0700`, written whole or not at all.
- [ ] [ABRD-95] A restart reuses the token, so an open tab keeps working; deleting the file rotates it.
- [ ] [ABRD-96] A file that is not one token (one line of 43 or more characters from `A-Z a-z 0-9 - _`, optional newline) is refused, exit `1`, nothing bound (E-ABRD-16).
- [ ] [ABRD-11] A body not complete 10 seconds after its headers, however it trickles, or that ends before its declared Content-Length is received, answers 408 `{"error": "request timeout: body incomplete"}`.
- [ ] [ABRD-20] Once every configured repo's read fails or times out, `GET /api/board` answers 502 with the same `repos[]` envelope as ABRD-08, each entry its own reason (E-ABRD-06).
- [ ] [ABRD-12] Every answer, HTTP-layer refusals included, carries `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and a CSP with `base-uri`, `form-action`, and `frame-ancestors` set to `'none'`.
- [ ] [ABRD-13] With the token, an `/api/` method other than `GET` or `POST` answers 405 `{"error": "method not allowed"}` with `Allow` naming the route; elsewhere it answers 405 as text with the same header.
- [ ] [ABRD-34] A line with `"form": "options"` is listed as an option line (E-ABRD-11); a line without `form` is a ruled yes/no line, with no `default` and no fingerprint (E-ABRD-03). No line offers an outcome.
- [ ] [ABRD-35] An option line's fingerprint is the SHA-256 of `[repo, item, index, card_hash]` (ABRD-21); `ruling`, `via`, `returned_on`, `returned_note` and `stored_card_hash` leave it be.
- [ ] [ABRD-53] An option line lists `via`, as `aco rulings --json` names it (RUL-15): `board`, `chat`, `default` or `null` while open. A yes/no line lists none.
- [ ] [ABRD-62] An option line lists `returned_on` and `returned_note` after `other` as RUL-17 names them: ISO date, note, else `null`.
- [ ] [ABRD-56] An option line lists `other` right after `via`: the answer verbatim as `aco rulings --json` names it (RUL-16) when its `ruling` is `other`, else `null`. A yes/no line lists none.
- [ ] [ABRD-60] A withdrawn line (BODY-104) is not listed: no list shows it, its repo stays readable, the item's other lines keep their `index`, and an item of only such lines is not listed.

Each listed line is `aco rulings --json`'s line (RUL-10); an option line adds
`fingerprint` last, a yes/no line has none; pictures are SVG text as stored.

## The SPA shell

- [ ] [ABRD-22] `GET /` answers the committed shell and `GET /assets/**` its committed built files, no token needed; each refuses a method other than `GET` with 405 and `Allow: GET` (see E-ABRD-08).
- [ ] [ABRD-23] `GET /assets/**` answers only a regular file under the committed `static/` directory: a `..` segment, encoded or not, or an in-between symlink answers `not found`, like a missing file.
- [ ] [ABRD-24] Shell/assets CSP adds `script-src 'self'`, `style-src 'self'`, `img-src data:` to ABRD-12, no nonce/inline/external styles; built CSS is `text/css; charset=utf-8` (E-ABRD-08).
- [ ] [ABRD-25] `aco serve` refuses to start with `ERROR: <path> is missing; build the frontend first (...)` once the committed shell is absent, never binding a board that could only answer its API.
- [ ] [ABRD-26] `aco serve --json` is refused by the argument parser as plain text, never in the envelope: `aco: error: unrecognized arguments: --json`, exit `2` (see E-ABRD-09).
- [ ] [ABRD-27] The global `aco --repo OWNER/REPO` before `serve` is refused `ERROR: aco serve reads checkout directories; pass them as aco serve --repo PATH`, exit `2` (see E-ABRD-10).

## Never

- The board never writes a decision for a line it did not just read as open with the same shown fields: ABRD-02 compares on the item's fresh read, and the write uses that read.
- An option's stored card hash is the hash the board just read from the line whose fingerprint was posted, and aco's writer compares it again on that same read (RULE-17).
- The board never splits a card: a card post is one write of its item naming every posted line, which stores all or none (RULE-29), Accept all included.
- The board never writes `via chat` or `via default`. Its `via board` is the cooperative record of `specs/rule.spec.md`'s Never, not proof that a person clicked.
- The board never runs two writes at once across any configured repo, and never starts one after stopping began (ABRD-03, ABRD-04, ABRD-17, ABRD-18).
- The board never writes an item through a second path: every ruling goes through the writer `aco rule` uses.
- No answer carries an `Access-Control-*` header, so a page from another origin can neither read an answer nor send the token header (ABRD-10).
- The board never resolves a repo label from a request into a path: a label is only ever a lookup key among the repos `--repo` configured at start (ABRD-16).
- A card's fingerprint never satisfies another configured repo's check, even with identical line content: it binds the repo label it was read under (ABRD-21).

## Examples

`Setup: test-forge` is a checkout whose items live in a file-backed forge
that logs every request; `aco serve` runs aco's library over it in that
directory (E-ABRD-02 through E-ABRD-05: `--repo` not given, so the one repo
is labelled by that directory's name) and each example sends one request.

- E-ABRD-01 (removed 29.10.2026): the board writes no yes/no outcome, so there is no example (ABRD-01).

### E-ABRD-02 -- a changed card refuses the stale post

Setup: test-forge, item `#12` titled `Song jump` with E-RUL-07's open option line shown, then its `card_hash` changed before the operator posts option `A` for that card

```text
decide: #12 line 1, option A, the fingerprint of the card as first shown
forge requests: read #12, no write
answer: {"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}
```

### E-ABRD-03 -- listing the board

Setup: test-forge, item `#42` titled `Share page` with ruled lines `Guests?` (`yes` on 2026-10-01) and `Hosts?` (`no` on 2026-10-01)

```text
request: GET /api/board, header X-Board-Token: <board token>
forge requests: the open-item listing
answer 200: {"repos": [{"name": "<repo>", "error": null, "items": [{"number": 42, "title": "Share page", "lines": [
  {"index": 1, "text": "Guests?", "ruling": "yes", "ruled_on": "2026-10-01"},
  {"index": 2, "text": "Hosts?", "ruling": "no", "ruled_on": "2026-10-01"}]}]}]}
```

### E-ABRD-04 -- a post naming an outcome is refused

Setup: test-forge, item `#42` with ruled line `Guests?` as listed by `GET /api/board`

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 42, "line": 1, "fingerprint": "<any>", "outcome": "no", "note": null}
forge requests: none
answer 400: {"error": "bad request: decision"}
```

### E-ABRD-05 -- a request without the token

Setup: test-forge, item `#42` with one open line `Guests?`

```text
request: GET /api/board?t=<board token>, no X-Board-Token header
forge requests: none
answer 403: {"error": "forbidden: missing or wrong token"}
```

### E-ABRD-06 -- two repos, one down

Setup: `aco serve --repo a --repo b`; repo `a`'s test-forge lists item `#42` with one line `Guests?` ruled `yes` on 2026-10-01; repo `b`'s test-forge fails its listing with `no forge adapter for host`

```text
request: GET /api/board, header X-Board-Token: <board token>
forge requests: the open-item listing in a, the open-item listing in b
answer 200: {"repos": [
  {"name": "a", "error": null, "items": [{"number": 42, "title": "Share page", "lines": [
    {"index": 1, "text": "Guests?", "ruling": "yes", "ruled_on": "2026-10-01"}]}]},
  {"name": "b", "error": "no forge adapter for host", "items": []}]}
```

Had `b`'s test-forge listed only an item whose block aco's grammar refuses instead, `b`'s entry would read `{"name": "b", "error": null, "items": []}` (ABRD-07).

Had `a`'s test-forge failed too, the answer would be 502 with the same two-entry `repos[]` envelope (ABRD-20).

### E-ABRD-07 -- a decision routes only into its named repo

Setup: `aco serve --repo a --repo b`; repo `a` and repo `b`'s test-forges each list an identical item `#12` with E-RUL-07's open option line

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "a", "item": 12, "lines": [{"line": 1, "fingerprint": "<as listed in a>", "option": "A"}]}
forge requests: read #12, then one write of #12's body in a; none in b
answer 200: {"status": "ruled", "message": null}
```

Posting the same body with `"repo": "c"` -- not a configured repo -- answers 400 `{"error": "bad request: decision"}`, no forge request in `a` or `b`.

Posting it with `"repo": "b"` instead -- `a`'s own fingerprint, against `b`'s identical card -- answers 200 `{"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}`; `b` reads #12 once and nothing is written in `a` or `b` (ABRD-21).

### E-ABRD-08 -- the shell and its assets need no token

Setup: test-forge, item `#42` with one open line `Guests?`

```text
request: GET / (no X-Board-Token header, no token in the path at all)
forge requests: none
answer 200: the committed `static/index.html`, Content-Type text/html

request: GET /assets/index.js
forge requests: none
answer 200: the committed `static/assets/index.js`, Content-Type text/javascript

request: GET /assets/index.css
forge requests: none
answer 200: the committed stylesheet, Content-Type text/css; charset=utf-8

request: GET /assets/../server.py (a traversal attempt, literal or percent-encoded)
forge requests: none
answer 404: not found (text/plain) -- the same answer a missing asset gets (ABRD-23)
```

### E-ABRD-09 -- `--json` is no mode of this command

Setup: none

```console
$ aco serve --json
2> usage: aco [-h] [--version] [--repo REPO]
2>            {bootstrap,reset,status,board,serve,rulings,next,start,claim,release,land,adopt,rescope,cut,rule,withdraw,check,brief,item}
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

### E-ABRD-11 -- listing an option line beside a ruled yes/no line

Setup: test-forge, item `#12` titled `Song jump` with E-RUL-07's open option line, and item `#42` titled `Share page` with line `Guests?` ruled `yes` on 2026-10-01

```text
request: GET /api/board, header X-Board-Token: <board token>
forge requests: the open-item listing
answer 200: {"repos": [{"name": "<repo>", "error": null, "items": [{"number": 12, "title": "Song jump", "lines": [
  {"index": 1, "form": "options", "text": "The song stays open on the jump.", "asked_on": "2026-10-28",
   "ruling": null, "ruled_on": null,
   "card_hash": "sha256:b3f1720e7b5b083f5ae59eaf99559b438d1e729dc9034e3ea534cf5806f23b8a",
   "stored_card_hash": null, "via": null, "other": null, "returned_on": null, "returned_note": null,
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
   "fingerprint": "<hex>"}]},
  {"number": 42, "title": "Share page", "lines": [
  {"index": 1, "text": "Guests?", "ruling": "yes", "ruled_on": "2026-10-01"}]}]}]}
```

### E-ABRD-12 -- deciding an option line

Setup: test-forge, item `#12` titled `Song jump` with E-RUL-07's open option line; the operator posts option `A` for that one-point card

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 12, "lines": [{"line": 1, "fingerprint": "<as listed>", "option": "A"}]}
forge requests: read #12, then one write of #12's body: line 1 ruled `A`, `via board`, the card hash just read
answer 200: {"status": "ruled", "message": null}
```

Posting the same body after the card changed since the page read it answers 200 `{"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}` on the item's fresh read; the stored line is unchanged. The single-line body `{"repo": "<repo>", "item": 12, "line": 1, "fingerprint": "<as listed>", "option": "A"}` answers 400 `{"error": "bad request: decision"}`, no forge request.

### E-ABRD-13 -- answering an option line with Other

Setup: test-forge, item `#12` titled `Song jump` with E-RUL-07's open option line; the operator posts his own answer for that one-point card

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 12, "lines": [{"line": 1, "fingerprint": "<as listed>"}], "other": "  Nur am Desktop.  "}
forge requests: read #12, then one write of #12's body: line 1 ruled `other` with `Nur am Desktop.`, `via board`, the card hash just read
answer 200: {"status": "ruled", "message": null}
```

A blank answer, one past 280 characters after trimming, or one beside `outcome`, `option` or `note` answers 400 `{"error": "bad request: decision"}`, no forge request.

### E-ABRD-14 -- sending an option line back to its head

Setup: test-forge, item `#12` titled `Song jump` with E-RUL-07's open option line; the operator posts Unclear with a note for that one-point card

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 12, "lines": [{"line": 1, "fingerprint": "<as listed>"}], "unclear": true, "note": "  Mobile fehlt.  "}
forge requests: read #12, then one write of #12's body: line 1 back to its head with the note `Mobile fehlt.`
answer 200: {"status": "returned", "message": null}
```

The line stays open, now with its head. Posting Unclear again answers 200 `{"status": "failed", "message": "line 1 is already with its head; it comes back once revised"}`. An `unclear` that is not `true`, or one beside `outcome`, `option` or `other`, or a note past 280 characters after trimming, answers 400 `{"error": "bad request: decision"}`, no forge request.

### E-ABRD-15 -- deciding a whole card

Setup: test-forge, item `#7` with two open option lines (2 and 3); the operator posts a pick for each

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 7, "lines": [{"line": 2, "fingerprint": "<as listed>", "option": "A"}, {"line": 3, "fingerprint": "<as listed>", "option": "B"}]}
forge requests: read #7, then one write of #7's body: line 2 ruled `A` and line 3 ruled `B`, each `via board` with its card hash just read
answer 200: {"status": "ruled", "message": null}
```

A post naming only line 2 while line 3 is open answers 200 `{"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}`; #7 is read once and not written. Posting `"other": "Nur am Desktop."` with no `option` on the entries rules both lines `other` with that answer in the same one write; posting `"unclear": true` sends both back to their head instead and answers `{"status": "returned", "message": null}`.

### E-ABRD-16 -- a token file that holds no token

Setup: the token file, `<state home>/aco/board-token`, holds `not a token`

```console
$ aco serve
2> ERROR: <state home>/aco/board-token holds no board token; delete it to start with a new one
exit 1
```
