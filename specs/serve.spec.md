# `aco serve`

`aco serve` shows the open expectation lines of every repository under the
configured root in a browser SPA and writes each decision in process, through
aco's own library: it lists the rows `aco rulings` lists and writes through the
writer `aco rule` uses; it takes no `--repo`.
This file owns the board's decision rules: which answers it writes,
when it refuses a decision, how writes are ordered and stopped, and the note
it may carry -- across every repository found, since one write turn and
one drain span all of them. It cites the read shape `specs/rulings.spec.md`
owns (RUL-10) and the write `specs/rule.spec.md` owns (RULE-01, RULE-14, RULE-20, RULE-29)
rather than restating them. It also owns the JSON API under `/api/` -- its
shapes, token, and headers -- and the shell's own delivery contract (who may
fetch it, and how it is contained to its own files); the SPA's own behaviour
once loaded is `frontend/`'s. It owns the log lines after the URL on standard output --
`server_listen.started`, `request.ended`, `request_handling.failed` and
`server_process.finished`, each one JSON record of the fleet's logger. `<n>` is an item number, `<k>` an expectation
line's 1-based index, `<repo>` a found repository's label, its forge name `owner/repo`.

## Behavior table

| state \ trigger | load the page | decide a shown card | answer a step |
|---|---|---|---|
| an item a non-member wrote, or whose author is unknown | ABRD-06 | — (not shown) | — |
| an item under `storage = "state-ref"` | ABRD-06, ABRD-112 | as its lines | — |
| an open line | ABRD-06 | ABRD-58, ABRD-59, ABRD-152, ABRD-153 | — |
| the line's shown fields changed since the page was built | ABRD-06 | ABRD-02 | — |
| a ruled option line | ABRD-06, ABRD-37, ABRD-54, ABRD-57 | RULE-04 | — |
| a ruled yes/no line | ABRD-30, ABRD-37, ABRD-54 | — (read-only) | — |
| an item whose block is malformed or unreadable | ABRD-07 | ABRD-41 | — |
| an item with open option lines | ABRD-82 | ABRD-77 | — |
| an item with two or more open option lines | ABRD-83, ABRD-84, ABRD-85 | ABRD-86, ABRD-87, ABRD-88, ABRD-89, ABRD-90, ABRD-91, ABRD-92, ABRD-154, ABRD-155, ABRD-156 | — |
| an option line, open or ruled | ABRD-34, ABRD-53, ABRD-56, ABRD-61, ABRD-62, ABRD-36, ABRD-37, ABRD-38, ABRD-43, ABRD-44, ABRD-45, ABRD-46, ABRD-47, ABRD-63, ABRD-65, ABRD-99, ABRD-100, ABRD-66, ABRD-67, ABRD-68, ABRD-69, ABRD-72, ABRD-73, ABRD-74, ABRD-75, ABRD-76 | ABRD-78 | — |
| a withdrawn line | ABRD-60 | ABRD-41 | — |
| a post without `lines` | — | ABRD-40 | — |
| its card changed, withdrawn, gone or closed since the page read it | — | ABRD-41 | — |
| a card post answering `other` | — | ABRD-64 | — |
| a card post answering `unclear` | — | ABRD-70, ABRD-71 | — |
| a card saving, from its undo window's end to its answer applied | — | ABRD-97, ABRD-100 | — |
| a read sent before an item's stored answer arrived | ABRD-98 | — | — |
| a read while a card waits | ABRD-105 | — | — |
| an item that waits on the operator | ABRD-157, ABRD-159, ABRD-160, ABRD-161, ABRD-163 | — | ABRD-168, ABRD-169, ABRD-171, ABRD-172, ABRD-173, ABRD-174, ABRD-175, ABRD-176, ABRD-177, ABRD-178 |
| a malformed step answer | — | — | ABRD-164, ABRD-165 |
| a step that changed, was answered, closed or removed since the page read it | — | — | ABRD-166 |
| an answer that does not fit its step | — | — | ABRD-167 |
| a step answer written over a change aco had not read, lost or not verified | — | — | ABRD-170 |
| a card post naming one or more open option lines of its item | — | ABRD-77, ABRD-78, ABRD-80 | — |
| a card post naming a changed or non-option line | — | ABRD-79 | — |
| a card post naming a line already ruled | — | ABRD-80 | — |
| a malformed card post | — | ABRD-81 | — |
| a second decision while one is being written, in any configured repo | — | ABRD-03, ABRD-17, ABRD-113 | ABRD-03, ABRD-17, ABRD-113 |
| a decision written | — | ABRD-122 | — |
| a decision written over a change aco had not read, which the body check keeps | — | ABRD-129, ABRD-130 | — |
| the board is stopping | — | ABRD-04, ABRD-18 | ABRD-04, ABRD-18 |
| a note or an answer on the decision | — | ABRD-05 | — |
| one found repo's read fails or times out | ABRD-15, ABRD-101 | ABRD-15 | — |
| every found repo's read fails or times out | ABRD-20, ABRD-102, ABRD-128 | ABRD-20 | — |
| an `/api/` request without the right token | ABRD-10 | ABRD-10 | ABRD-10 |
| a decision naming a repo the scan does not find | — | ABRD-16 | ABRD-16 |
| a card's fingerprint submitted against a different configured repo | — | ABRD-21 | — |
| `aco serve --json` | ABRD-26 | — | — |
| the global `aco --repo OWNER/REPO` before `serve` | ABRD-27 | — | — |
| no config file, a malformed one, no root, a relative root or one that is no directory | ABRD-108 | — | — |
| no repository found, at start or on a later read | ABRD-109 | — | — |
| a directory under the root that cannot be read | ABRD-110 | — | — |
| a repo with open containers, none, or a failed read of a container's parent, its sub-issues or the trunk | ABRD-131, ABRD-132, ABRD-133, ABRD-134, ABRD-135, ABRD-136, ABRD-137, ABRD-138, ABRD-139, ABRD-147, ABRD-148, ABRD-149, ABRD-150, ABRD-151 | — | — |
| any request answered | ABRD-180, ABRD-181, ABRD-182 | ABRD-180, ABRD-181, ABRD-182 | ABRD-180, ABRD-181, ABRD-182 |
| a request that raises, or whose browser leaves mid-answer | ABRD-183, ABRD-184 | ABRD-183, ABRD-184 | ABRD-183, ABRD-184 |
| the board starting, or stopping on Ctrl-C or SIGTERM | ABRD-179, ABRD-185 | — | — |

## Writing a decision

- ABRD-01 (removed).
- [ ] [ABRD-02] A card whose shown fields (an option line's `card_hash`, ABRD-35) changed since shown is refused on its fresh read `Diese Zeile hat sich geändert, bitte neu laden`, nothing written (E-ABRD-02).
- [ ] [ABRD-03] The board writes one decision at a time; a decision arriving meanwhile waits. Decisions on distinct lines are both stored; on the same line, the later one answers `already_ruled` (RULE-04).
- [ ] [ABRD-113] Every decision takes the item's per-machine lock (RULE-40), so other writers wait; a lock that cannot be taken fails the card naming it, nothing written (RULE-41); a held one prints RULE-42's line.
- [ ] [ABRD-04] Stopping the board waits for a write already running; a decision still waiting for its turn or arriving after stopping began is refused `board is shutting down`, nothing written.
- [ ] [ABRD-05] A note or answer is at most `280` characters after trimming, holds no NUL, and is valid UTF-8; any other refuses it before any forge request; a blank note is no note, a blank answer is refused.
- ABRD-39 (removed).
- [ ] [ABRD-40] A post without `lines` answers 400 `bad request: decision`, no forge request (ABRD-77).
- [ ] [ABRD-41] A card changed, withdrawn, gone, closed or unreadable on its fresh read is `failed` `Diese Zeile hat sich geändert, bitte neu laden`; a ruled line `already_ruled`; else `failed`, aco's sentence.
- ABRD-42 (removed).
- [ ] [ABRD-129] A write kept over a change aco had not read answers `ruled` (or `returned`) with the item and `note`: `Written over a change aco had not read; that change is only in the item's edit history.`
- [ ] [ABRD-130] The page shows a ruled answer's card with a note as decided, the note beside it, never as `failed`; an overwritten write and one the check could not verify stay `failed` (ABRD-41).

- [ ] [ABRD-77] A post with `lines` decides one card: `repo`, `item`, and `lines` of `{"line", "fingerprint"}`, each with its own `option`, or one `other` or `unclear` for all (see E-ABRD-15).
- [ ] [ABRD-78] It reads item `<n>` once and writes its body once through aco's writer: every posted line, `via board` for an option or `other`, each with that read's card hash, or every line back to its head.
- [ ] [ABRD-79] A card post is refused as ABRD-02 on the fresh read, nothing written, unless each posted line reads as an option line, each open one with its posted fingerprint; an open line not posted stays open.
- [ ] [ABRD-80] A posted line already ruled is left to aco's writer: RULE-04 refuses the whole card `already_ruled`, the answer maps once as ABRD-41 and ABRD-71 say, and aco stores all lines or none (RULE-29).
- [ ] [ABRD-81] A card post that breaks the card key rules (no line, a line named twice, a misplaced or unknown key, not exactly one answer kind) answers 400 `bad request: decision`, no forge request.

The card key rules: `lines` is a non-empty list of objects, each with a positive `line` named once and a string `fingerprint`. An entry holds only `line`, `fingerprint` and an optional `option`; any other key in an entry refuses, and an entry's `option`, when present, is `A`-`D`; `null` refuses. Either every entry carries an `option` `A`-`D` and the post names no `other`, `unclear` or `note`, or no entry does and the post names exactly one of `other` (ABRD-05, no `note`) or `unclear` (literally `true`, an optional note, a blank one none). Beside `lines`, a top-level `line`, `fingerprint`, `option` or `outcome` refuses, even when `null`; for `other`, `unclear` and `note` an absent key and `null` name nothing.

## Reading the lines

- [ ] [ABRD-06] A page load reads one open-item listing per repo and shows open lines of items a member (owner, member, collaborator) wrote in RUL-03's order, one card per item (ABRD-82); no copy is kept.
- [ ] [ABRD-112] Under `storage = "state-ref"` every item counts as a member's: only a writer of the state ref can create one.
- [ ] [ABRD-07] An item whose block aco's grammar refuses, or that the store cannot read, is not listed, as RUL-20; its repository stays readable.

## Browser decision flow

- [ ] [ABRD-28] The decision list groups open rows by repository under its name and count (ABRD-107); a row shows its state shape, an option card's name (ABRD-82) and its day (ABRD-106).
- [ ] [ABRD-29] Within a repository, option cards come in aco's order, with-head cards after (ABRD-61). First load selects the first row; desktop shows its card, phones the list until a row is tapped.
- [ ] [ABRD-30] Decided groups open items' ruled lines by repository under name and count; a row shows the Decided shape, an option line's topic or a yes/no line's short question or sentence, and its day (ABRD-106).
- [ ] [ABRD-31] Within a repository, Decided lists the newest date first, then item number and line index descending; with no ruled line and no failed repository it reads `Nothing decided yet`.
- [ ] [ABRD-32] Opening Decided selects its first row: its card on desktop, the list on phones. Returning to Open keeps its selection, list position and phone view; a background decision displaces neither view.
- [ ] [ABRD-33] During undo a question stays open; only its stored answer, applied in place without a read, moves it to Decided.
- [ ] [ABRD-36] A one-point card has: repository, area, kind, `with head` (ABRD-61), `reversible` or `final`, `Asked` (ABRD-106), question, Problem, Today (ABRD-43), options A-D, Recommendation and Decide (ABRD-44).
- [ ] [ABRD-37] A selected ruled line shows the decided card: meta, question, Decided (`A — name`, `Ja`, `Nein`, `Später` or ABRD-57), How (ABRD-54) and Contract behind `Show` with its binding sentences and source.
- [ ] [ABRD-54] How reads `Board`, `From chat` or `Recommendation kept – no answer` for an option line's `via` (ABRD-53), `not recorded` for a yes/no line; then ` · ` and the ruling date as `DD.MM.YYYY`.
- [ ] [ABRD-57] A line ruled `other` shows Decided as `Other: „<answer>“` and binds that answer alone behind Contract's `Show`; How reads as ABRD-54; Open never lists it, Decided does (ABRD-30).
- [ ] [ABRD-38] Each option on an option card is a button opening its Result (picture or `= TODAY`; none when it gives neither), You notice, Cost, Undo and Contract behind `Show`; opening one closes the other.
- [ ] [ABRD-43] A card without a Today picture has no Today row. Each option-card picture is an `Enlarge picture` button showing it with caption in a modal; `Close` or `Esc` closes it, returning focus to that button.
- [ ] [ABRD-44] A one-point card's Decide row has one pick per option, the recommended one in the accent; a pick waits out the undo window (ABRD-99), then posts the card (ABRD-77); once stored, it moves to Decided.
- [ ] [ABRD-45] A refused post shows its sentence in the Decide row; "changed" (ABRD-02) or "already ruled" hide picks and `Accept all` behind `Neu laden`, whose read locks only that card; other failures keep them.
- [ ] [ABRD-46] A `final` pick first opens a modal `Decide <X>?` with its Undo consequence and the warn mark, focus on `Cancel`; `Decide <X>` records it, and the window starts once it is confirmed (ABRD-87).
- [ ] [ABRD-47] `Cancel` or `Esc` closes the confirm, posts nothing and returns focus to the pick; `Decide <X>` keeps the card as shown when the confirm opened, so a card changed since is refused (ABRD-02).
- [ ] [ABRD-58] A one-point card's pick shows a strip above it for its 8 s window: the Decided shape, `Saves shortly: <letter> — <option> · <topic>` and `Undo`, in view as the card scrolls and atop a phone's list.
- [ ] [ABRD-59] A pick that starts a window focuses its strip's `Undo`, so Enter undoes it; `Undo` cancels the post and focuses the shown card, else the list. An ended window removes its strip; ABRD-50 applies.
- [ ] [ABRD-152] When the page is hidden or closed, every decision in its undo window is posted at once, each answer its own write with the token header; the window ends there, and nothing not yet chosen is posted.
- [ ] [ABRD-153] A refused or failed post keeps a warning strip `Not saved: <name>` with its sentence above the stage until that card is shown; the card's own banner stays (ABRD-45).
- [ ] [ABRD-154] Each point has its own `Other…` and text, kept per point also on a one-point card; `Send` posts that point alone with the strip `Saves shortly: Other · <topic>` (ABRD-67).
- [ ] [ABRD-155] After a stored answer the stage stays on its card while the item has an open point and moves on (a noted answer to Decided, ABRD-129) once the last point is stored.
- [ ] [ABRD-48] Option card rows carry the Open, With head (ABRD-61) or Saving (ABRD-100) shape; each shape names its state, each row's title is its question or name (ABRD-82).
- [ ] [ABRD-61] A card with a line carrying `returned_on` is with its head: Open lists it muted, with the With head shape (ring, back chevron), after other option cards; it shows `with head`. Decide stays.
- [ ] [ABRD-49] Readable repositories with nothing open are named once, in configured order, under `Nothing open:`; with no open line and no failed repository the list reads `All decided`.
- [ ] [ABRD-101] A repository whose read failed is a group under its name above one warning box with the warn mark, `Not read`, its sentence and `last read HH:MM` once read; it keeps its last rows, decidable.
- [ ] [ABRD-102] A read with no answer, or with neither `repos[]` nor `error` keeps every repository's rows as ABRD-101 with `aco antwortet nicht.` once read; a first load shows it and the status line.
- [ ] [ABRD-128] A refused read shows what its answer carries: `repos[]` (ABRD-20) as any reading, an `error` sentence in place of the status line of ABRD-102; with neither, ABRD-102 applies.
- [ ] [ABRD-103] The page reads on load, on Refresh, on return to the tab when its last read is over 10 s old, and every 30 minutes while visible; a read asked for during one runs once after it.
- [ ] [ABRD-104] Refresh shows a turning arrow, `Refresh` (`Reading…` and `aria-busy` while a read runs, still clickable) and the last read's `HH:MM`, named `<label> · read HH:MM`; phones hide the label.
- [ ] [ABRD-105] A read leaves the item of a card that waits (ABRD-99) as shown, kept when the read omits it; a read that answers once the card no longer waits applies as ABRD-98 allows.
- [ ] [ABRD-106] A card's meta ends in `Asked DD.MM.YYYY` when its line carries `asked_on`, a card of points its newest point's day; its row shows that day as `DD.MM.`, a Decided row its decision day.
- [ ] [ABRD-107] On the Open and Decided tabs groups stand by their first row: open before with head, then the newest day, then the higher item; a failed repository with kept cards too, one without cards last.
- [ ] [ABRD-50] Once the shown card's decision is stored, the stage moves to the list's first open option card, else to its first row; a card selected meanwhile stays (ABRD-32).
- [ ] [ABRD-51] A 56 px header (52 px on phones) holds `Entscheidungs-Board`, the tabs `Open n`, `Decided n`, `Progress`, `Steps n` and Refresh (ABRD-104); n counts open rows, ruled lines, steps.
- [ ] [ABRD-125] The tabs are pills; `Open`'s count is an accent badge, quiet at 0. On phones they start left; the brand shows where none do (loading, no access, failure) and yields to the tabs or back header.
- [ ] [ABRD-126] The selected row carries an accent bar on a light accent ground without hover; every row has one height; a repository's heading keeps the case it is typed in.
- [ ] [ABRD-127] With no row to list, the list shows one centred state with its check and sentences, no stage beside it; loading a turning ring, still if motion is reduced; no access or no answer a centred warn card.
- [ ] [ABRD-123] The board opens on Open at every width; a reload returns to Open, as Decided is not kept across a reload.
- [ ] [ABRD-55] On phones a tapped row's card fills the pane without its card frame, under a header whose `‹ Open` or `‹ Decided` returns to that list with the row focused; the tabs hide meanwhile.
- [ ] [ABRD-63] An open option card's Decide row ends in `Other…`, beside the picks or `Accept all`; it opens a panel with a textarea (`Your answer`, up to 280 characters, focused) and `Send`, disabled while blank.
- [ ] [ABRD-64] A card post's `other` (ABRD-78) is the trimmed answer within ABRD-05, written once for every posted line with `via board` (E-ABRD-13).
- [ ] [ABRD-65] `Other…` and `Send` of a point hide with the picks and `Accept all` (ABRD-45) and disable while a decision on that point waits (ABRD-99), so a pick and an Other of one point never both post.
- [ ] [ABRD-97] A point is saving (ABRD-100) from its window's end until its answer is applied: its picks and `Other…` take no click; `Accept all` and `Unclear` take none while every open point saves.
- [ ] [ABRD-98] A read's rows for an item apply only if the read was sent after that item's last stored answer arrived; until then the page keeps the item that answer carried.
- [ ] [ABRD-99] From the start of its undo window until its answer is applied, a point marks its chosen letter at full strength and dims the rest, without the accent; `Other…` and `Unclear` mark none.
- [ ] [ABRD-100] A card with a saving point shows the Saving shape on its row (a dashed ring, turning unless motion is reduced), also with its head; its meta reads `saving`; what stays clickable is ABRD-97.
- [ ] [ABRD-66] The typed answer is kept per point, also on a one-point card: closing the panel, switching cards, `Undo` and a failed post keep it; `Undo` reopens the panel with it, and a stored decision drops it.
- [ ] [ABRD-67] `Send` closes the panel and starts the undo window with the strip `Saves shortly: Other · <name>` (ABRD-82, ABRD-154) and `Undo` (ABRD-58, ABRD-59); `Undo` posts nothing.
- [ ] [ABRD-68] `Send` posts the point as shown when the panel opened, so a point changed since is refused (ABRD-02); the answer stays in the draft.
- [ ] [ABRD-69] A card that is with its head (ABRD-61) offers `Other…` as any open option card does.
- [ ] [ABRD-70] A card post's `unclear` (ABRD-78) stores no `via`; its note is trimmed, a blank one is none, and every posted line returns to its head (E-ABRD-14).
- [ ] [ABRD-71] An `unclear` aco stores answers 200 `{"status": "returned", "message": null, "item"}` (ABRD-09): the line stays open, with its head; only a stored `option` or `other` answers `ruled`.
- [ ] [ABRD-72] An open option card's Decide row ends with `Other…` and `Unclear`; a card with its head (ABRD-61) shows no `Unclear` and no Unclear panel, and keeps its picks and `Other…`.
- [ ] [ABRD-73] `Unclear` opens the panel with one focused textarea (`What is unclear? (optional)`, at most 280 characters) and `Send`, enabled while blank; it closes `Other…`'s panel; each keeps its draft.
- [ ] [ABRD-74] `Send` closes the panel and starts the window with a grey strip: the With head shape, `With head: <name>` (ABRD-82) and `Undo` (ABRD-59); `Undo` posts nothing and reopens the panel with the note.
- [ ] [ABRD-75] After the window it posts the card with `unclear` and the trimmed note, none if blank (ABRD-77); `Unclear` locks, and posting and refusal follow ABRD-65, ABRD-66 and ABRD-68 for `Other…`.
- [ ] [ABRD-76] Once the post answers `returned` (ABRD-71), the stage moves to the list's first Open row, else stays on the card, now with its head; a card selected meanwhile stays (ABRD-32).
- [ ] [ABRD-82] An item's open option lines (its points) are one card with one Open row and one name: a one-point card's topic, else `<area> · <n> points` of the open points, areas joined by ` / `.
- [ ] [ABRD-83] A card of several points has its name as title and no Problem; its meta reads `<repo> › ` with ABRD-82's areas, its distinct kinds, `with head` (ABRD-61), `final` or `reversible`, `Asked` (ABRD-106).
- [ ] [ABRD-84] Its points are rows in aco's order: `<k>` (among open points), the question, a warn mark when an option is `final`, one pick per option (recommended one accented), `Other…`; none is open at first.
- [ ] [ABRD-156] Storing point 1 of 3 shows the old points 2 and 3 as 1 and 2 and the name as `<area> · 2 points`; the last open point shows as a one-point card (ABRD-36).
- [ ] [ABRD-85] Activating a point's question opens its Problem, Today (when given, ABRD-43), Options and Recommendation as on a one-point card and closes any other point; activating it again closes it.
- [ ] [ABRD-86] A pick answers its point alone and posts only it, after its window (ABRD-87); the other points stay open and usable.
- [ ] [ABRD-87] A pick starts its own undo window with the strip `Saves shortly: <k><letter> · <name>` and `Undo`, which posts nothing; then it posts that point alone (ABRD-77).
- [ ] [ABRD-88] A point's pick on a `final` option first asks as ABRD-46, its line reading `Point <k>: <consequence>`; `Cancel` leaves the point as it was.
- [ ] [ABRD-89] `Accept all` leads the Decide row of points, in the accent: it picks each recommended letter of the open points not waiting, in one window (after ABRD-90); one with no valid recommendation stays open.
- [ ] [ABRD-90] When a recommended option is `final`, `Accept all` first asks `Accept all recommendations?` with `Point <k>: <consequence>` per such point, focus on `Cancel`; `Cancel` or `Esc` posts nothing.
- [ ] [ABRD-91] A post names its points' fingerprints, so a point changed or ruled since is refused (ABRD-79, ABRD-80); a point added since stays open.
- [ ] [ABRD-92] `Other…` answers its point (ABRD-154); `Unclear` answers the open points that do not wait with one note, strip `With head: <name>`.
- [ ] [ABRD-52] An option card's Decide row sticks to the pane's foot while the card runs on beneath it and then casts a shadow over that content; at the card's end it rests in place without one.

The browser proofs are `frontend/e2e/decide.spec.ts`,
`frontend/e2e/decideOption.spec.ts`, `frontend/e2e/decided.spec.ts`, `frontend/e2e/escapeRow.spec.ts`, `frontend/e2e/failedRead.spec.ts`,
`frontend/e2e/groupCard.spec.ts`, `frontend/e2e/houseFonts.spec.ts` (ABRD-124), `frontend/e2e/openList.spec.ts`, `frontend/e2e/optionCard.spec.ts`, `frontend/e2e/pageLeave.spec.ts` (ABRD-152, ABRD-153), `frontend/e2e/pageFrame.spec.ts`, `frontend/e2e/pictureEnlargement.spec.ts`, `frontend/e2e/picturelessCard.spec.ts`, `frontend/e2e/quietStates.spec.ts` (ABRD-127, ABRD-128),
`frontend/e2e/refresh.spec.ts`, `frontend/e2e/stepCard.spec.ts` (ABRD-159, ABRD-160), `frontend/e2e/unclear.spec.ts` and `frontend/e2e/withHead.spec.ts`; ordering is additionally proven by
`frontend/src/app/model/boardSummary.test.ts`.

## Multiple repositories

- [ ] [ABRD-14] `aco serve` serves each checkout under the config file's `root` tracking `.aco/board.toml`, labelled `owner/repo`, one per forge repository (first sorted path); it takes no `--repo`.
- [ ] [ABRD-15] `GET /api/board` answers once any repo's read succeeded; a repo whose read fails or times out carries its own sentence and no items (E-ABRD-06); the page shows it per ABRD-101.
- [ ] [ABRD-16] A decision or step answer naming a `repo` the scan does not find is refused `bad request: decision` (`bad request: step` for a step) before any forge request (see E-ABRD-07).
- [ ] [ABRD-17] The one write turn (ABRD-03) spans every configured repo: a decision for one repo never writes while another repo's decision is being written (see E-ABRD-07).
- [ ] [ABRD-18] Stopping the board (ABRD-04) drains every repo: it waits for a running write in any one, and refuses a waiting decision in any repo once stopping begins, without waiting for the running one.
- [ ] [ABRD-19] Every read and every decision scans the root afresh, so a checkout added or removed since the last shows or goes at once; `GET /api/board` names the `root` it scanned (E-ABRD-03).
- [ ] [ABRD-108] A missing or malformed config file, one without `root`, a relative `root` or a `root` that is no directory refuses the start, naming the file, exit `2` (see E-ABRD-17).
- [ ] [ABRD-109] Finding no repository refuses the start naming the root, exit `2`; a later read answers 502 `{"error": "<sentence>"}` naming the root, never an empty board (see E-ABRD-18).
- [ ] [ABRD-110] A directory under the root that cannot be read is listed as a repo named by its path, its sentence in `error`, no items; it is never skipped (see E-ABRD-19).
- [ ] [ABRD-111] The walk stops at each checkout and follows no symlink; a linked worktree, a submodule and a checkout that does not track `.aco/board.toml` are not served.
- [ ] [ABRD-21] A card's fingerprint binds the `repo` it was read under; posted against another configured repo, identical content included, it is refused like a changed line (see E-ABRD-07).

## The JSON API

- [ ] [ABRD-08] `GET /api/board` answers `{"root", "repos": [{"name", "error", "items", "progress", "steps"}]}`; `items`: RUL-03 rows (E-ABRD-03); `error`: a sentence or `null` (E-ABRD-06); `progress`: ABRD-131.
- [ ] [ABRD-09] `POST /api/rule` takes a card (ABRD-77); 200 `{"status", "message"}`, plus `"item"` (ABRD-08's row) once stored, and `"note"` (ABRD-129); else 400 `bad request: decision` (E-ABRD-04, -07, -12..15).
- [ ] [ABRD-10] Every `/api/` request, any method, needs exactly one `X-Board-Token` header with the board token, else 403 `{"error": "forbidden: missing or wrong token"}` before any forge request (see E-ABRD-05).
- [ ] [ABRD-93] The board token lives in a file, `$XDG_STATE_HOME/aco/board-token` when that value is an absolute path, else `~/.local/state/aco/board-token`; `aco serve` reads it before binding.
- [ ] [ABRD-94] An absent token file is created with a fresh token: file mode `0600`, every missing directory `0700`, written whole or not at all.
- [ ] [ABRD-95] A restart reuses the token, so an open tab keeps working; deleting the file rotates it.
- [ ] [ABRD-96] A file that is not one token (one line of 43 or more characters from `A-Z a-z 0-9 - _`, optional newline) is refused, exit `1`, nothing bound (E-ABRD-16).
- [ ] [ABRD-11] On `/api/rule` and `/api/step`, a body not complete 10 seconds after its headers or ending before its declared Content-Length answers 408 `{"error": "request timeout: body incomplete"}`.
- [ ] [ABRD-20] Once every found repo's read fails or times out, `GET /api/board` answers 502 with the same `repos[]` envelope as ABRD-08, each entry its own reason (E-ABRD-06); the page shows it per ABRD-128.
- [ ] [ABRD-12] Every answer, HTTP-layer refusals included, carries `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and a CSP with `base-uri`, `form-action`, and `frame-ancestors` set to `'none'`.
- [ ] [ABRD-13] With the token, an `/api/` method other than `GET` or `POST` answers 405 `{"error": "method not allowed"}` with `Allow` naming the route; elsewhere it answers 405 as text with the same header.
- [ ] [ABRD-34] A line with `"form": "options"` is listed as an option line (E-ABRD-11); a line without `form` is a ruled yes/no line, with no `default` and no fingerprint (E-ABRD-03). No line offers an outcome.
- [ ] [ABRD-35] An option line's fingerprint is the SHA-256 of `[repo, item, index, card_hash]` (ABRD-21); `ruling`, `via`, `returned_on`, `returned_note` and `stored_card_hash` leave it be.
- [ ] [ABRD-53] An option line lists `via`, as `aco rulings --json` names it (RUL-15): `board`, `chat`, `default` or `null` while open. A yes/no line lists none.
- [ ] [ABRD-62] An option line lists `returned_on` and `returned_note` after `other` as RUL-17 names them: ISO date, note, else `null`.
- [ ] [ABRD-56] An option line lists `other` right after `via`: the answer verbatim as `aco rulings --json` names it (RUL-16) when its `ruling` is `other`, else `null`. A yes/no line lists none.
- [ ] [ABRD-60] A withdrawn line (BODY-104) is not listed: no list shows it, its repo stays readable, the item's other lines keep their `index`, and an item of only such lines is not listed.
- [ ] [ABRD-122] A decision that is written and verified touches the item's signal (WAIT-12), as `aco rule` does (RULE-44), so a session waiting with `aco wait` learns it.
- ABRD-114, ABRD-115, ABRD-116, ABRD-117, ABRD-118, ABRD-119, ABRD-120, ABRD-121 (retired).

Each listed line is `aco rulings --json`'s line (RUL-10); an option line adds
`fingerprint` last, a yes/no line has none; pictures are SVG text as stored.

## Progress

- [ ] [ABRD-131] A repo's `progress` lists top-level containers with `closed`, `landed`, `planned`, `open`, `uncut`, `waiting`, `percent`, `lanes_left`, `estimate`, `closed_children` (ABRD-136 to ABRD-147; E-ABRD-20).
- [ ] [ABRD-132] `percent` (rounded down) is 100 only when nothing is open or uncut and `null` while nothing is planned; a repo's line sums its top-level containers, a container with a parent anywhere has none.
- [ ] [ABRD-133] `progress.waiting` counts the repo's items that wait on the operator, `aco inbox`'s steps (E-ABRD-20).
- [ ] [ABRD-134] A failed read of a container's parent, sub-issues or the trunk leaves that repo's `progress` as `{"error": "<sentence>"}` with no counts; its items stay listed (E-ABRD-21).
- [ ] [ABRD-135] The tab `Progress` shows per container a bar of `Landed` and `Closed otherwise` children and `closed/planned · percent %` (`7/48 · 14 %`); an unknown progress shows its sentence.
- [ ] [ABRD-136] A closed child is `landed` when a trunk commit (the last `5000` first-parent) names it in a `Work-Item:` trailer; a child in another repository never is; `landed` is at most `closed`.
- [ ] [ABRD-137] A container's `waiting` counts its open children in this repository that wait on the operator, `aco inbox`'s steps; `progress.waiting` stays the repo's total.
- [ ] [ABRD-138] `closed` and `open` count the container's sub-issue list; a container that is unreadable, not a member's or without counts is neither listed nor summed.
- [ ] [ABRD-139] The tab shows a repo's landed, closed otherwise, open, uncut and waiting counts and a container's waiting count when not 0; with nothing planned it shows only `Nothing planned`, no bar.
- [ ] [ABRD-140] A container's `lanes_left` is its open children not waiting on the operator plus its uncut rows; with none left its `estimate` is `null`. The work of waiting children is never in the range.
- [ ] [ABRD-141] A container's `estimate` prices each lane left at the median to 80th percentile of finished lane seconds of its size class: the middle two averaged, nearest rank; the range sums both ends.
- [ ] [ABRD-142] A finished item is one sample: its lanes' seconds summed, sized by its latest landed lane; one lane of unknown time, or none landed, makes it none. A class under `5` samples is priced pooled.
- [ ] [ABRD-143] A lane with no declared size, a nested container, a child in another repository or an uncut row is priced pooled. Per class the estimate lists `lanes`, `basis` (`measured` or `pooled`) and `samples`.
- [ ] [ABRD-144] Under `5` pooled samples `estimate` is `{"error": "not enough lane records yet"}`, with no lane records `"no lane records"`, with them unreadable `"lane records unreadable"`; the counts stay.
- [ ] [ABRD-145] A range is `{"error": null, "low_seconds", "high_seconds", "samples", "classes"}` in whole seconds, `samples` being the pooled items; the tab rounds to hours and never shows a date.
- [ ] [ABRD-146] The tab shows per container `5 lanes left · about 3 to 7 h agent work · from 31 finished items` (`under 1 h` below an hour), or the lanes left and the sentence; waiting stays its own chip.
- [ ] [ABRD-147] A container's `closed_children` lists its closed children of this repository by number, each `{"number", "title", "wall_seconds", "fix_rounds", "recorded"}`; no other repository's child.
- [ ] [ABRD-148] A closed child's `wall_seconds` and `fix_rounds` are the sums over all lane records that name it; either is `null` when any of those records lacks it.
- [ ] [ABRD-149] A closed child that no lane record names has `recorded` false and both figures `null`, else `recorded` is true.
- [ ] [ABRD-150] With the lane records unreadable every closed child has `recorded` true and both figures `null`; the counts stay.
- [ ] [ABRD-151] The tab lists under a container its closed children as `#12 Title · 1.5 h · 2 fix rounds` (`45 min` below an hour, `time unknown` and `fix rounds unknown` for a `null`), or `#12 Title · no record`.

A closed child counts however it closed, not-planned included. A container whose own state is closed is not listed, so its children are not counted. Landed plus closed otherwise plus open plus uncut is planned.

## Steps

- [ ] [ABRD-157] A repo's `steps` lists its members' readable items whose `wait` names the operator, each `{"number", "title", "step", "purpose", "actions", "expected", "answer"}`; a failed repo has none.
- [ ] [ABRD-158] An item a non-member wrote, or one that waits on nobody, is no step.
- [ ] [ABRD-159] The tab `Steps n` shows per step its title, purpose, the actions in a block, `Expected` and its result, then `Antwort: Ja / Nein` or, if the step names one, `Antwort: <answer>`; n counts the steps.
- [ ] [ABRD-160] `Copy` beside the block puts exactly the block's text on the clipboard and then reads `Copied`; a refused copy reads `Copy failed, try again`.
- [ ] [ABRD-161] A step without its fields (`null`) shows its number, title and one-line `step` only, with no button.
- [ ] [ABRD-162] With no step the tab says `No step is waiting for you.`; a repo that could not be read shows `Not read` and its sentence instead, never an empty list.
- [ ] [ABRD-163] Each `steps` entry also carries `fingerprint`, which follows its repo, item, `step` and the four fields of its card, so it changes when any of them does.
- [ ] [ABRD-164] `POST /api/step` takes `repo`, `item`, `fingerprint` and `result`: `yes` with no `text`, or `no` or `report` with a `text`; any other key or shape is refused `bad request: step` (see E-ABRD-22).
- [ ] [ABRD-165] A step answer's `text` follows ABRD-05's rules and is not blank; a refused one reaches no forge.
- [ ] [ABRD-166] A step no longer as shown on the item's fresh read (ABRD-113), because it changed, was answered, closed or removed, answers `failed` `This step changed; reload.`, nothing written (see E-ABRD-23).
- [ ] [ABRD-167] A `yes` on a step that asks for a report, or a `report` on one that does not, answers `failed` with a sentence, nothing written; `no` fits every step (see E-ABRD-24).
- [ ] [ABRD-168] A stored answer removes `wait` and `step` and writes `now` as `The operator answered "<step>" <channel> on <date>: ` and `Erfolgreich`, `Fehlgeschlagen: <note>` or the report (see E-ABRD-25).
- [ ] [ABRD-178] The `<channel>` of ABRD-168 is `on the board` for `POST /api/step` and `in chat` for the MCP tool `answer_step` (MCP-72).
- [ ] [ABRD-169] Under `storage = "github"` the label `needs-operator` goes after the body write; a refused removal keeps the answer and adds a `note` naming `gh issue edit <n> --remove-label needs-operator`.
- [ ] [ABRD-170] A write the forge's body check keeps answers `answered` with ABRD-129's note and removes the label; a lost or unverified write answers `failed` with the forge's sentence and leaves the label.
- [ ] [ABRD-171] The board never closes the item, never writes an expectation line and never touches the item's signal (WAIT-12); every other field and byte of the body stays.
- [ ] [ABRD-172] A stored answer leaves `next` as it is, in one body write, and answers `answered` with no `item`.

- [ ] [ABRD-173] A step with its fields shows `Erfolgreich` and `Fehlgeschlagen`; `Erfolgreich` posts `yes`. A step that names an answer shows a text field `Bericht` with `Senden` instead, which posts `report`.
- [ ] [ABRD-174] `Fehlgeschlagen` opens a field `Notiz`; `Senden` stays disabled while it is blank and then posts `no` with the note.
- [ ] [ABRD-175] An answer starts the 8 second window of ABRD-58 with the strip `Saves shortly: <answer> · #n` and `Undo` in the card; `Undo` posts nothing, and leaving the page posts it at once (ABRD-152).
- [ ] [ABRD-176] A stored answer removes the card after a re-read; a refused one keeps the card and shows its sentence, with `Neu laden`; the answer buttons stay disabled until `Neu laden`.
- [ ] [ABRD-177] `Copied` reads `Copy` again once the step's card has changed.

Proofs: `tests/board/test_board_api_steps.py`, `tests/board/test_board_api_step_answers.py`, `frontend/e2e/stepCard.spec.ts` and `frontend/e2e/stepAnswer.spec.ts` (390 and 1280 px).

## The SPA shell

- [ ] [ABRD-22] `GET /` answers the committed shell and `GET /assets/**` its committed built files, no token needed; each refuses a method other than `GET` with 405 and `Allow: GET` (see E-ABRD-08).
- [ ] [ABRD-23] `GET /assets/**` answers only a regular file under the committed `static/` directory: a `..` segment, encoded or not, or an in-between symlink answers `not found`, like a missing file.
- [ ] [ABRD-24] Shell/assets CSP adds `script-src 'self'`, `style-src 'self'`, `font-src 'self'`, `img-src data:` to ABRD-12, no nonce, inline or external source; built CSS is `text/css; charset=utf-8` (E-ABRD-08).
- [ ] [ABRD-25] `aco serve` refuses to start with `ERROR: <path> is missing; build the frontend first (...)` once the committed shell is absent, never binding a board that could only answer its API.
- [ ] [ABRD-26] `aco serve --json` is refused by the argument parser as plain text, never in the envelope: `aco: error: unrecognized arguments: --json`, exit `2` (see E-ABRD-09).
- [ ] [ABRD-27] The global `aco --repo OWNER/REPO` before `serve` is refused `ERROR: aco serve finds its repositories itself; --repo does not apply to it`, exit `2` (see E-ABRD-10).
- [ ] [ABRD-124] `GET /assets/**` answers a built `.woff2` file as `font/woff2`; the shell's stylesheets load Open Sans and Oswald from there and the board makes no request to another host (see E-ABRD-08).

## Logging

- [ ] [ABRD-179] After the URL every stdout line is one JSON record: `server_listen.started` follows the URL, `server_process.finished` the stop on Ctrl-C or SIGTERM (ABRD-04 holds under both).
- [ ] [ABRD-180] Every answered request, refusals of the HTTP layer included, writes one `request.ended` with `outcome`, `method`, `route`, `status`, `duration_ms`, `sub` (null), `ip`; 5xx is `failed`, else `ok`.
- [ ] [ABRD-181] `route` is `/`, `/api/board`, `/api/rule`, `/api/step` or `/assets/` (any asset path, found or not); any other path is null. A connection closed before a request line writes none.
- [ ] [ABRD-182] No line holds the token, the URL, a request's path or query or a header value; a traceback holds source frames and exception messages, never local variables.
- [ ] [ABRD-183] An unexpected exception ends `request.ended` as `failed` (500 if no status was sent), then writes one `request_handling.failed` with `error_type`, traceback and the same `trace_id`; no stderr.
- [ ] [ABRD-184] A browser that leaves mid-answer reads `ok` with the status sent and writes no `request_handling.failed`.
- [ ] [ABRD-185] `service` is `aco-board` and `version` aco's version unless `SERVICE_VERSION` is set; a malformed `LOG_LEVEL` refuses `ERROR: <sentence>`, exit `2`, nothing bound (see E-ABRD-27).

Proofs: `tests/board/test_board_server_request_line.py` and `tests/board/test_board_cli.py`; `scripts/package_smoke.sh` proves the lines from an installed tool. A request answered after the URL reads as E-ABRD-26.

## Never

- The board never writes a decision for a line it did not just read as open with the same shown fields: ABRD-02 compares on the item's fresh read, and the write uses that read.
- An option's stored card hash is the hash the board just read from the line whose fingerprint was posted, and aco's writer compares it again on that same read (RULE-17).
- The board never splits a post: each post is one write of its item naming every posted line, which stores all or none (RULE-29), Accept all included.
- The board never writes `via chat` or `via default`. Its `via board` is the cooperative record of `specs/rule.spec.md`'s Never, not proof that a person clicked.
- The board never runs two writes at once across any configured repo, and never starts one after stopping began (ABRD-03, ABRD-04, ABRD-17, ABRD-18).
- The board never writes an item through a second path: every ruling goes through the writer `aco rule` uses.
- The board answers a step only on the item's fresh read of that step (ABRD-166) and removes its label only after a write that stands (ABRD-170); it never closes the item (ABRD-171).
- No answer carries an `Access-Control-*` header, so a page from another origin can neither read an answer nor send the token header (ABRD-10).
- The board never resolves a repo label from a request into a path: a label is only ever a lookup key among the repos a fresh scan found (ABRD-16).
- A card's fingerprint never satisfies another found repo's check, even with identical line content: it binds the repo label it was read under (ABRD-21).

## Examples

`Setup: test-forge` is a checkout whose items live in a file-backed forge
that logs every request; `aco serve` runs aco's library over it in that
directory (E-ABRD-02 through E-ABRD-05: the root holds that one checkout, so the one repo
is labelled by its forge name) and each example sends one request.

- E-ABRD-01 (removed).

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
answer 200: {"root": "<root>", "repos": [{"name": "<repo>", "error": null, "items": [{"number": 42, "title": "Share page", "lines": [
  {"index": 1, "text": "Guests?", "ruling": "yes", "ruled_on": "2026-10-01"},
  {"index": 2, "text": "Hosts?", "ruling": "no", "ruled_on": "2026-10-01"}]}], "progress": {"error": null, "closed": 0, "planned": 0, "open": 0, "uncut": 0, "percent": null, "waiting": 0, "containers": []}, "steps": []}]}
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

Setup: the root holds checkouts of `owner/a` and `owner/b`; repo `owner/a`'s test-forge lists item `#42` with one line `Guests?` ruled `yes` on 2026-10-01; repo `owner/b`'s test-forge fails its listing with `no forge adapter for host`

```text
request: GET /api/board, header X-Board-Token: <board token>
forge requests: the open-item listing in owner/a, the open-item listing in owner/b
answer 200: {"root": "<root>", "repos": [
  {"name": "owner/a", "error": null, "items": [{"number": 42, "title": "Share page", "lines": [
    {"index": 1, "text": "Guests?", "ruling": "yes", "ruled_on": "2026-10-01"}]}], "progress": {"error": null, ...}, "steps": []},
  {"name": "owner/b", "error": "no forge adapter for host", "items": [], "progress": null, "steps": []}]}
```

Had `owner/b`'s test-forge listed only an item whose block aco's grammar refuses instead, its entry would read `{"name": "owner/b", "error": null, "items": [], "progress": {...}, "steps": []}` (ABRD-07).

Had `owner/a`'s test-forge failed too, the answer would be 502 with the same two-entry `repos[]` envelope (ABRD-20).

### E-ABRD-07 -- a decision routes only into its named repo

Setup: the root holds checkouts of `owner/a` and `owner/b`; their test-forges each list an identical item `#12` with E-RUL-07's open option line

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "owner/a", "item": 12, "lines": [{"line": 1, "fingerprint": "<as listed in a>", "option": "A"}]}
forge requests: read #12, then one write of #12's body in owner/a; none in owner/b
answer 200: {"status": "ruled", "message": null, "item": <#12 as GET /api/board lists it after the write>}
```

Posting the same body with `"repo": "owner/c"` -- no checkout of it under the root -- answers 400 `{"error": "bad request: decision"}`, no forge request in `owner/a` or `owner/b`.

Posting it with `"repo": "owner/b"` instead -- `owner/a`'s own fingerprint, against `owner/b`'s identical card -- answers 200 `{"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}`; `owner/b` reads #12 once and nothing is written in either (ABRD-21).

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

request: GET /assets/fonts/oswald-latin-400-normal.woff2
forge requests: none
answer 200: the committed font file, Content-Type font/woff2

request: GET /assets/../server.py (a traversal attempt, literal or percent-encoded)
forge requests: none
answer 404: not found (text/plain) -- the same answer a missing asset gets (ABRD-23)
```

### E-ABRD-09 -- `--json` is no mode of this command

Setup: none

```console
$ aco serve --json
2> usage: aco [-h] [--version] [--repo REPO]
2>            {bootstrap,reset,status,board,serve,mcp,rulings,fleet-plans,stats,next,start,claim,release,land,lane-record,adopt,rescope,handover,cut,rule,withdraw,wait,check,brief,item} ...
2> aco: error: unrecognized arguments: --json
exit 2
```

### E-ABRD-10 -- the global `--repo` does not apply to `serve`

Setup: none

```console
$ aco --repo overnightworks/aco serve
2> ERROR: aco serve finds its repositories itself; --repo does not apply to it
exit 2
```

### E-ABRD-11 -- listing an option line beside a ruled yes/no line

Setup: test-forge, item `#12` titled `Song jump` with E-RUL-07's open option line, and item `#42` titled `Share page` with line `Guests?` ruled `yes` on 2026-10-01

```text
request: GET /api/board, header X-Board-Token: <board token>
forge requests: the open-item listing
answer 200: {"root": "<root>", "repos": [{"name": "<repo>", "error": null, "items": [{"number": 12, "title": "Song jump", "lines": [
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
answer 200: {"status": "ruled", "message": null, "item": <#12 as GET /api/board lists it after the write>}
```

Posting the same body after the card changed since the page read it answers 200 `{"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}` on the item's fresh read; the stored line is unchanged. The single-line body `{"repo": "<repo>", "item": 12, "line": 1, "fingerprint": "<as listed>", "option": "A"}` answers 400 `{"error": "bad request: decision"}`, no forge request.

### E-ABRD-13 -- answering an option line with Other

Setup: test-forge, item `#12` titled `Song jump` with E-RUL-07's open option line; the operator posts his own answer for that one-point card

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 12, "lines": [{"line": 1, "fingerprint": "<as listed>"}], "other": "  Nur am Desktop.  "}
forge requests: read #12, then one write of #12's body: line 1 ruled `other` with `Nur am Desktop.`, `via board`, the card hash just read
answer 200: {"status": "ruled", "message": null, "item": <#12 as GET /api/board lists it after the write>}
```

A blank answer, one past 280 characters after trimming, or one beside `outcome`, `option` or `note` answers 400 `{"error": "bad request: decision"}`, no forge request.

### E-ABRD-14 -- sending an option line back to its head

Setup: test-forge, item `#12` titled `Song jump` with E-RUL-07's open option line; the operator posts Unclear with a note for that one-point card

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 12, "lines": [{"line": 1, "fingerprint": "<as listed>"}], "unclear": true, "note": "  Mobile fehlt.  "}
forge requests: read #12, then one write of #12's body: line 1 back to its head with the note `Mobile fehlt.`
answer 200: {"status": "returned", "message": null, "item": <#12 as GET /api/board lists it after the write>}
```

The line stays open, now with its head. Posting Unclear again answers 200 `{"status": "failed", "message": "line 1 is already with its head; it comes back once revised"}`. An `unclear` that is not `true`, or one beside `outcome`, `option` or `other`, or a note past 280 characters after trimming, answers 400 `{"error": "bad request: decision"}`, no forge request.

### E-ABRD-15 -- deciding a whole card

Setup: test-forge, item `#7` with two open option lines (2 and 3); the operator posts a pick for each

```text
request: POST /api/rule, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 7, "lines": [{"line": 2, "fingerprint": "<as listed>", "option": "A"}, {"line": 3, "fingerprint": "<as listed>", "option": "B"}]}
forge requests: read #7, then one write of #7's body: line 2 ruled `A` and line 3 ruled `B`, each `via board` with its card hash just read
answer 200: {"status": "ruled", "message": null, "item": <#7 as GET /api/board lists it after the write>}
```

A post naming only line 2 stores line 2 alone and leaves line 3 open: #7 is read once and written once, and the answer lists #7 with line 3 still open. A post naming line 2 with a changed fingerprint answers 200 `{"status": "failed", "message": "Diese Zeile hat sich geändert, bitte neu laden"}`; #7 is read once and not written. Posting `"other": "Nur am Desktop."` with no `option` on the entries rules the posted lines `other` with that answer in the same one write; posting `"unclear": true` sends them back to their head instead and answers `{"status": "returned", "message": null, "item": <#7 as listed>}`.

### E-ABRD-16 -- a token file that holds no token

Setup: the token file, `<state home>/aco/board-token`, holds `not a token`

```console
$ aco serve
2> ERROR: <state home>/aco/board-token holds no board token; delete it to start with a new one
exit 1
```

### E-ABRD-17 -- a config file that names no usable root

Setup: `<config home>/aco/config.toml` holds `root = "repositories"`

```console
$ aco serve
2> ERROR: <config home>/aco/config.toml: root repositories is not an absolute path
exit 2
```

The other refusals read `<file> does not exist; create it with root = "<absolute path>"`, `<file> is not valid TOML: <reason>`, `<file> sets no root = "<absolute path>"` and `<file>: root <root> is not a directory`; each exits `2` with nothing bound.

### E-ABRD-18 -- no repository under the root

Setup: the config file's root is `<root>`, an existing directory holding no checkout that tracks `.aco/board.toml`

```console
$ aco serve
2> ERROR: no repository tracking .aco/board.toml under <root>
exit 2
```

Had the last checkout been removed while the board ran, `GET /api/board` would answer 502 `{"error": "no repository tracking .aco/board.toml under <root>"}` (ABRD-109).

### E-ABRD-19 -- a checkout that cannot be read

Setup: the root holds a checkout of `owner/a` listing item `#42`, and `<root>/broken/.git`, a directory git does not read as a repository

```text
request: GET /api/board, header X-Board-Token: <board token>
answer 200: {"root": "<root>", "repos": [
  {"name": "owner/a", "error": null, "items": [{"number": 42, ...}]},
  {"name": "<root>/broken", "error": "<git's refusal>", "items": [], "progress": null, "steps": []}]}
```

### E-ABRD-20 -- progress per top-level container

Setup: test-forge, open container `#10` titled `Song jump` whose sub-issue list holds 3 closed children, two of them named by a trunk commit's `Work-Item:` trailer, and the open child `#20` carrying a `wait` naming `operator`, with 2 uncut `[[slice]]` rows, and container `#11` with a parent `#10`

```text
request: GET /api/board, header X-Board-Token: <board token>
forge requests: the open-item listing, the parent of #10, the parent of #11, the sub-issues of #10
answer 200: {"root": "<root>", "repos": [{"name": "<repo>", "error": null, "items": [], "progress": {
  "error": null, "closed": 3, "landed": 2, "planned": 6, "open": 1, "uncut": 2, "percent": 50, "waiting": 1,
  "containers": [{"number": 10, "title": "Song jump", "closed": 3, "landed": 2, "planned": 6, "open": 1, "uncut": 2, "percent": 50, "waiting": 1,
    "lanes_left": 2, "estimate": {"error": "no lane records"}}]}, "steps": [...]}]}
```

### E-ABRD-21 -- a container's parent cannot be read

Setup: test-forge, open container `#10` with 3 children closed of 4, whose parent read (or sub-issue read) fails with `GitHub is down`

```text
request: GET /api/board, header X-Board-Token: <board token>
answer 200: {"root": "<root>", "repos": [{"name": "<repo>", "error": null, "items": [], "progress": {"error": "GitHub is down"}, "steps": []}]}
```

### E-ABRD-22 -- a step answer without its note is refused

Setup: test-forge, item `#7` waiting on the operator with a `step` table, as listed by `GET /api/board`

```text
request: POST /api/step, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 7, "fingerprint": "<as listed>", "result": "no"}
forge requests: none
answer 400: {"error": "bad request: step"}
```

### E-ABRD-23 -- a step changed since the page read it

Setup: test-forge, item `#7` waiting on the operator, then its `expected` text changed before the operator answers `yes`

```text
request: POST /api/step, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 7, "fingerprint": "<as first listed>", "result": "yes"}
forge requests: read #7, no write
answer 200: {"status": "failed", "message": "This step changed; reload."}
```

### E-ABRD-24 -- an Erfolgreich answer to a step that asks for a report

Setup: test-forge, item `#7` waiting on the operator whose `step` table names `answer = "the run report"`

```text
request: POST /api/step, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 7, "fingerprint": "<as listed>", "result": "yes"}
forge requests: read #7, no write
answer 200: {"status": "failed", "message": "#7 asks for a report; the answer does not fit"}
```

### E-ABRD-25 -- Fehlgeschlagen with a note

Setup: test-forge, open item `#7` labelled `needs-operator`, waiting on `Decide.` with a `step` table, the board's day 2026-10-03

```text
request: POST /api/step, header X-Board-Token: <board token>
body: {"repo": "<repo>", "item": 7, "fingerprint": "<as listed>", "result": "no", "text": "Stayed red."}
forge requests: read #7, write #7's body, remove the label needs-operator from #7
answer 200: {"status": "answered", "message": null}
stored block: no `wait`, no `[step]`, now = The operator answered "Decide." on the board on 2026-10-03: Fehlgeschlagen: Stayed red.
              next = as it was before the answer
```

### E-ABRD-26 -- the lines after the URL

Setup: a root holding one checkout; `/api/board` is called once with the token only in the query and once with the header token

```console
$ aco serve
http://127.0.0.1:<port>/#t=<board token>
{"event": "server_listen.started", "logger": "aco.board.cli", "level": "info", "ts": "<time>", "service": "aco-board", "version": "<aco version>", "trace_id": null}
{"outcome": "ok", "method": "GET", "route": "/api/board", "status": 403, "duration_ms": <ms>, "sub": null, "ip": "127.0.0.1", "event": "request.ended", "logger": "logline.request", "level": "info", "ts": "<time>", "service": "aco-board", "version": "<aco version>", "trace_id": "<32 hex digits>"}
{"outcome": "ok", "method": "GET", "route": "/api/board", "status": 200, "duration_ms": <ms>, "sub": null, "ip": "127.0.0.1", "event": "request.ended", "logger": "logline.request", "level": "info", "ts": "<time>", "service": "aco-board", "version": "<aco version>", "trace_id": "<32 hex digits>"}
^C
{"event": "server_process.finished", "logger": "aco.board.cli", "level": "info", "ts": "<time>", "service": "aco-board", "version": "<aco version>", "trace_id": null}
exit 0
```

The first request carried the token only in the query, which `/api/` refuses (ABRD-10); neither line shows the query, the path or the token.

### E-ABRD-27 -- a malformed `LOG_LEVEL`

Setup: `LOG_LEVEL=loud`

```console
$ aco serve
2> ERROR: LOG_LEVEL is 'loud'; accepted names are debug, info, warning, error, critical
exit 2
```

Nothing is bound and standard output stays empty; the logger's sentence is its own wording.
