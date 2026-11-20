# `aco next`

`aco next` names the one action the board recommends pulling right now,
plus a fixed tail of three further lines every run prints regardless of
which action it recommends: `parallel:`, `scope unknown:`, and `close:`.
This file owns every one of those lines' own shape, the
three `NextAction` variants' own text and `--json`, the `RECOVERY`
preamble and `SKIPPED` tail, and exit `0`/`3`. It cites rather than
restates: the forge-resolution precondition (`specs/board.spec.md`,
BOARD-01/BOARD-02/BOARD-42), `RECOVERY`'s own content and its always-first
placement (`specs/landing-grammar.spec.md`, LAND-53), the kind
exclusion a container without a recognized `kind` gets from every
container-shaped view (`specs/board.spec.md`, BOARD-08), and the scope
overlap grammar `aco claim`'s own cost line already defines
(`specs/claim-record.spec.md`, CLAIM-31..CLAIM-34); `specs/output.spec.md`
owns the `--json` envelope itself (OUT-nn: key order, `ok`, `message`)
that wraps NEXT-11..13's own action fields. `<n>` is an
item number, `<label>` an item as `specs/landing-grammar.spec.md` prints
it, `<s>` an integer score. A *display control* -- the one set this file
owns, which `next` escapes (NEXT-37), `aco land`'s refusal escapes
(`specs/land.spec.md`), `release`'s `next:` line, `rulings` text, `claim`'s
out-of-order warning, the board and brief configurations' unknown-key
refusals and, keeping their line feeds, the `brief` and `item show` bodies
escape as NEXT-37 does, a slice title refuses (`specs/body-block.spec.md`,
BODY-63) and a scope path refuses (`specs/claim-record.spec.md`, CLAIM-20)
-- is every control character but TAB (C0, DEL and C1), the line and paragraph
separators U+2028/U+2029, the bidi controls U+200E, U+200F, U+061C,
U+202A..U+202E and U+2066..U+2069, the zero-width characters U+200B..U+200D,
U+2060 and U+FEFF, and the tag characters U+E0000..U+E007F; NBSP and every
other printable space are text.

## Behavior table

| state \ trigger | text | `--json` |
|---|---|---|
| unsupported forge host / untracked pin | BOARD-01/02 (cited) | BOARD-01/02 (cited) |
| `--repo` under `storage = "state-ref"` | BOARD-42 (cited) | BOARD-42 (cited), NEXT-24 |
| no actionable item at all | NEXT-01 | NEXT-01 |
| a work item is the top action | NEXT-02, NEXT-03 | NEXT-11 |
| that action, run outside a linked non-default worktree | NEXT-41 | NEXT-11 |
| that action's scope is wide and the body names no `whole` | NEXT-42 | NEXT-11 |
| that item's expectations are proposed or old-ruled | NEXT-04 | NEXT-11 |
| that item carries a withdrawn expectation line | NEXT-48 | NEXT-11 |
| a container qualifies to be cut | NEXT-05, NEXT-31 | NEXT-12 |
| an advice command carries an option value | NEXT-27, NEXT-31 | NEXT-11, NEXT-12 |
| a title, `Next`, slice title or `SKIPPED` reason holds a display control | NEXT-37 | NEXT-11..14 |
| its first uncut row's title or `done_when` holds a line break or control character | NEXT-32 | NEXT-14 |
| a state-ref item the store cannot read | NEXT-36 | NEXT-14 |
| a container whose every open child is such an item | NEXT-38 | NEXT-14 |
| a container whose only open child is in another repository | NEXT-60 | NEXT-14 |
| a second cuttable container behind the top action | NEXT-34 | NEXT-14 |
| that container is itself a child of another item | NEXT-25, NEXT-29, NEXT-33 | NEXT-14 |
| a childless container has no uncut row | NEXT-07 | NEXT-13 |
| that same container has an open blocker | NEXT-07 | NEXT-13 |
| a landed-but-open item exists | LAND-53 (cited) | NEXT-14 |
| an unworkable item exists beside the top action | NEXT-08 | NEXT-14 |
| an item carries an operator `wait` | NEXT-39, NEXT-40 | NEXT-14 |
| an item carries the label `needs-operator` and no operator `wait` | NEXT-61 | NEXT-14 |
| a container carries an operator `wait` | NEXT-39, NEXT-28 | NEXT-14 |
| an item carries a `wait` that still holds | NEXT-59 | NEXT-14 |
| a childless container carries a trigger or `until` `wait` that still holds | NEXT-59 | NEXT-14 |
| an item carries the idea label | NEXT-43, NEXT-28 | NEXT-44 |
| further free items exist | NEXT-09, NEXT-21, NEXT-22 | NEXT-15 |
| a placed item meets a live claim, the first action or an earlier candidate | NEXT-56, NEXT-57 | NEXT-58 |
| more than three such candidates | NEXT-10 | NEXT-15 |
| the first action itself names no scope | NEXT-16 | NEXT-15 |
| a candidate names no scope of its own | NEXT-17 | NEXT-15 |
| a closable container or recovery item, any rank | NEXT-18, NEXT-19, NEXT-28 | NEXT-14 |
| neither exists | NEXT-20 | NEXT-14 |
| any item under `storage = "state-ref"` | its id, as labels print it | NEXT-35 |
| the trunk lists code built ahead of a closed, missing, pull request or unreadable item | NEXT-49 | NEXT-51 |
| the trunk lists it beside an open item only | NEXT-49 | NEXT-51 |
| the list is malformed or cannot be read | NEXT-50 | NEXT-52 |
| a red entry, no actionable item | NEXT-53 | NEXT-53 |
| an entry names an item of this repository or of another | NEXT-54 | NEXT-54 |
| an entry's state is closed, missing, a pull request, unreadable | NEXT-55 | NEXT-51 |
| the configuration declares no audit | no line | NEXT-63 |
| an audit is due by landings, by days, with no anchor, a malformed anchor | NEXT-62, NEXT-64 | NEXT-63 |
| an audit is not due | no line | NEXT-65 |
| an anchor names a commit only the fetched trunk holds, or no trunk holds | NEXT-66 | NEXT-66 |
| the fetch or the listing fails | NEXT-67 | NEXT-67 |
| an audit is due, no actionable item | NEXT-68 | NEXT-68 |

## No actionable item

- [ ] [NEXT-01] With nothing to pull, `next` prints `No actionable item.`, still followed by `parallel:`/`scope unknown:`/`close:`, exit `3`; `--json` is `{"ok": false, "reason": "nothing_actionable", ...}`.

## A work item action

- [ ] [NEXT-02] The top-ranked item prints `<label> score <s>: <title>`, then `Next: <item's own Next>`, then `Run: aco claim <n>` from a linked worktree on a non-default branch, exit `0` (see E-NEXT-01).
- [ ] [NEXT-41] From any other checkout, where `claim` refuses, `Run:` is `aco start <n> --slug=<slug>`, the title's slug, else the id: `!!! ???` gives the number under `github`, the id under `state-ref` (E-NEXT-14).
- [ ] [NEXT-42] A scope `claim` calls wide here (four paths, or a directory such as `src`) and no body `whole` ends `Run:` with `--whole <reason>`; with `whole` set, it is left out (E-NEXT-14).
- [ ] [NEXT-37] Text shows each display control in a title, `Next`, slice title or `SKIPPED` reason as its escape: `a\x1b[2J` prints as typed; TAB, NBSP and `Größe` as is; `--json` unchanged but BODY-68.
- [ ] [NEXT-03] An item naming its own top-level `scope` drops `--scope` from `Run:`; a scopeless item's `Run:` ends `--scope <paths>` and gains a further `scope unknown` line (see E-NEXT-02).
- [ ] [NEXT-30] A scopeless item whose only `[[slice]]` row names paths -- a retyped nested container (NEXT-29) -- instead prints `--scope=<path>` per path of that row, with no `scope unknown`.
- [ ] [NEXT-04] A still-proposed item adds `expectations unruled: refine before the pull`; a stale ruling adds `ruled <n> landings ago: refine again at the pull` -- never both (see E-NEXT-02).
- [ ] [NEXT-48] A withdrawn line (BODY-104) never adds `expectations unruled` and never dates a ruling; an item of only withdrawn lines adds neither NEXT-04 hint.
- [ ] [NEXT-23] A scopeless, sliceless item still qualifies as this action (`scope unknown`, NEXT-03); `claim`/`start`'s own precedence check reads a narrower rule (`specs/claim.spec.md` CLM-23).

## A container's own action

- [ ] [NEXT-05] A childless container with an undispatched `[[slice]]` row prints `cut_slice <label>: <title>`, that row's title, then `Next: aco cut <n>`, which cuts that row (CUT-06), exit `0` (E-NEXT-03).
- [ ] [NEXT-27] Every argument an advice line prints inside a command is quoted for a POSIX shell, so it runs as printed: scope path `docs/my notes.md` prints `--scope='docs/my notes.md'`.
- [ ] [NEXT-31] An advice command attaches each option's value as `--<option>=<quoted>`, so a value starting with `-` still reaches it; a cut advice carries no title at all (see E-NEXT-10).
- [ ] [NEXT-32] A display control in the first uncut row's title or `done_when` withholds `cut`; `SKIPPED`: `slice row <i> <field> holds a line break or control character; make it one printable line` (E-NEXT-10).
- [ ] [NEXT-36] An item PIN-14/PIN-15 refuses is named under `SKIPPED` as `<item-id>: body malformed: <field>: <message>`; every other item still reads, one it blocks stays blocked (see E-NEXT-11).
- [ ] [NEXT-38] A container whose every open child, ITEM-54's included, is such an item reads `container; its open children do not read: <item-ids>` under `SKIPPED`, never `close:` (see E-NEXT-12).
- NEXT-06 (retired).
- [ ] [NEXT-07] A childless container without an uncut row prints `close_container <label>: <closed>/<total> children closed, no uncut row` (BOARD-58), whatever its `Next`, blocker or `wait` (E-NEXT-04).
- [ ] [NEXT-25] A childless container with an uncut row that is a child of any item -- any type, open or closed, any repository -- never gets `cut_slice` (CUT-03); `SKIPPED` names its repair (E-NEXT-09).
- [ ] [NEXT-29] That repair for one row claims as the retyped item's `Run:` will (NEXT-03): bare with a top-level `scope`, else `--scope=<path>` per row path, else `--scope <paths>` (E-NEXT-09).
- [ ] [NEXT-33] Every claim a `SKIPPED` reason names ends `--out-of-order <reason>`, since a skipped item is never the first action; `<reason>`, like `<paths>`, is for the agent to fill in.

## `RECOVERY` and `SKIPPED`

- [ ] [NEXT-08] Every other unworkable item is named once under a trailing `SKIPPED` block, `<label>: <reason>`; a container `next` itself recommends cutting or closing is left out of that list.
- NEXT-26, NEXT-47 (retired).
- [ ] [NEXT-34] A NEXT-05 container not the first action reads `cut slice "<title>"; run <its cut command>` under `SKIPPED`, `\` and `"` in `<title>` escaped in text and `--json`; never `container; claim a child`.
- [ ] [NEXT-28] An item `close:` lists is never also named under `SKIPPED`, `waiting on operator:` or `ideas:`, in text or `--json` (see E-NEXT-06).
- [ ] [NEXT-39] An item with an `operator` wait is never pulled, cut or first; `waiting on operator: <labels>` lists it unless `close:` does; a claimed one reads `waiting: <step>` in `SKIPPED` (E-NEXT-13, E-NEXT-15).
- [ ] [NEXT-59] A holding `wait` (`trigger`, or `until <date>` up to it) leaves an item unpulled, a container uncut and never first; a closable one stays in `close:`; `SKIPPED` reads `waiting: <text>` (E-NEXT-15).
- [ ] [NEXT-61] The label `needs-operator` on an item without an operator `wait` holds nothing: the item is pulled or cut like any other.
- [ ] [NEXT-60] A container whose open children all live in other repositories reads `container; waiting on <owner>/<repo>#<n>, ...` under `SKIPPED`, never `container; claim a child` (NEXT-38 appends it).
- [ ] [NEXT-40] `aco next --help` names `wait.operator` as what holds an item for the operator, the `step` tool as the way to set it, and the label `needs-operator` as its GitHub view.
- [ ] [NEXT-43] An item labelled `idea_label` (PIN-49) is never pulled, cut or closed, whatever its body or merged pull request; `ideas: <labels>` names it after `waiting on operator:`, not under `SKIPPED`.
- [ ] [NEXT-45] `with head: <label> line <k>, …` follows `ideas:` and names each open item's option lines sent back by `rule --unclear` (RULE-22); absent when none; an unreadable body names none (E-NEXT-16).

## `parallel:`

- [ ] [NEXT-09] `parallel:` lists every further free item the walk placed, `<label> (<n> path[s])`, comma-joined, in board order, alongside the first action (see E-NEXT-05, E-NEXT-18).
- [ ] [NEXT-21] `parallel:` walks further qualifying actions in board order, skipping a close or recovery item outright, and holds none back for an overlap (see E-NEXT-05, E-NEXT-18).
- [ ] [NEXT-22] A candidate with a `scope` is placed whatever that scope meets; its `scope` is then met by the candidates after it (see E-NEXT-05, E-NEXT-18).
- [ ] [NEXT-56] A candidate meeting a live claim's, the first action's or an earlier candidate's scope prints `<label> (<n> path[s]; overlaps issue <label> on <paths>, lane <branch> on <paths>)` (E-NEXT-18).
- [ ] [NEXT-57] That note lists the live claims first, then the first action, then the earlier candidates, in CLAIM-31's grammar with CLAIM-33's deeper path and CLAIM-34's cap of three paths (E-NEXT-18).
- [ ] [NEXT-10] Beyond three placed candidates, only the first three are named, followed by `, and <n> more`; `--json`'s own `candidates` array still carries every one (see E-NEXT-05).
- [ ] [NEXT-16] Once the first action names no scope, the tail collapses to `parallel: unknown (first action names no scope)`; `scope unknown:` is skipped, never printed as `none` (see E-NEXT-02).
- [ ] [NEXT-17] `scope unknown:` lists, in board order, every candidate the walk could not place for lacking a scope of its own, or `none`; printed whenever the first action does name a scope.

## `close:`

- [ ] [NEXT-18] `close:` unions closable containers (kind, no open child, no uncut `[[slice]]` row) then recovery items, in board order, first-seen, whatever the first action (E-NEXT-06).
- [ ] [NEXT-19] `close:` never names a container the forge reports no recognized `kind` for (BOARD-08's own exclusion): such an item is read as ordinary, not as one with nothing left to do.
- [ ] [NEXT-20] `close:` prints `none` when neither a closable container nor a recovery item exists.

## `--json`

- [ ] [NEXT-11] A work-item action's `reason` is `work_item` (`ok: true`), adding `number`, `score`, `title`, `next`, `command`, `ruling_landings`/`ruling_old`/`ruling_hint` per NEXT-04 (E-NEXT-07).
- [ ] [NEXT-12] A cut proposal's `reason` is `"cut_slice"` (`ok: true`), the object adding `number`, `title`, `slice`, `cut_title`, `command` (see E-NEXT-07).
- [ ] [NEXT-13] A close proposal's `reason` is `"close_container"` (`ok: true`), adding `number`, `closed`, `total`, `next_step` (always `null`), never `command`.
- [ ] [NEXT-14] The object always carries `recovery` (`{number, title, step}`), `skipped` (`{number, reason}`), `close`, `waiting_on_operator` (bare number arrays), whatever `reason`; see NEXT-44, NEXT-51, NEXT-52.
- [ ] [NEXT-15] `parallel` always carries `first_scope_unknown`, `candidates` (`{number, scope, overlaps}` each, uncapped), and `scope_unknown` (a bare number array).
- [ ] [NEXT-58] A candidate's `overlaps` holds one `{issue, lane, claim_id, paths}` per note, `[]` when none: `lane` a lane claim's branch, else `issue` (NEXT-35); `claim_id` null off a claim; `paths` uncapped.
- [ ] [NEXT-44] The object always carries `ideas`, a bare number array after `waiting_on_operator`, `[]` when no item carries the idea label (NEXT-43).
- [ ] [NEXT-46] The object always carries `with_head`, after `ideas`: `{number, lines}` per item named by NEXT-45, `lines` the bare line indexes, `[]` when no line is with its head.
- [ ] [NEXT-35] Under `storage = "state-ref"` each item these fields name, `number` included, is the `aco-xxxxxx` id the text prints, a string in place of the bare number.
- [ ] [NEXT-24] `--json` on a dispatched refusal (BOARD-02, BOARD-42) prints OUT-nn's envelope with the sentence as `message` and `reason` from the table below, exit `2` (see E-NEXT-08).

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| PIN-04 (`--repo` under `storage = state-ref`) | `invalid_usage` |
| BOARD-02 (no forge adapter for host), PIN-05 (no resolvable default branch) | `unavailable` |

## Code built ahead of its caller

`specs/ahead-of-caller.spec.md` owns the list and what makes an entry red; this section owns what `next` prints and carries.

- [ ] [NEXT-49] After `with head:`, before `SKIPPED`, text prints a line per red entry: `ahead of caller: <path>: item <item> <state> (<reason>)`, `<state>` per NEXT-55.
- [ ] [NEXT-50] A malformed or unreadable list prints the one line `ahead of caller: unavailable (<sentence>)`; the rest is unchanged. Every foreign part of these lines is escaped as NEXT-37 does.
- [ ] [NEXT-51] `--json` always carries `ahead_of_caller` after `with_head`: `{path, item, reason, state, error}`; `state` is `open`, `closed`, `missing`, `pull_request`, `unreadable`; `error` else `null`.
- [ ] [NEXT-52] `--json` always carries `ahead_of_caller_unavailable` after `ahead_of_caller`: `null`, or the sentence NEXT-50 prints, and then `ahead_of_caller` is `[]`.
- [ ] [NEXT-53] A red entry or an unavailable list never changes the exit status: a red entry beside `No actionable item.` prints its line and exits `3`, as today.
- [ ] [NEXT-54] `<item>` is this repository's item as NEXT-35 names it (the bare number under `github`, the `aco-xxxxxx` id under `state-ref`), else `<owner>/<repo>#<n>`; `--json` `item` is that number, id or string.
- [ ] [NEXT-55] `<state>` reads `is closed` for `closed`, `is not found or not accessible` for `missing`, `is a pull request` for `pull_request`, `is unreadable: <error>` for `unreadable`; open prints no line.

## Recurring audits

`.aco/board.toml` declares audits (PIN-58..62). An entry's *anchor* is the newest issue (`state-ref`: item) carrying its label, open or closed, whose body holds a line `audited through <sha>` once stripped; of several in one body the last counts. `<k>` counts the first-parent trunk landings after that commit, `<d>` the UTC days from its committer date to today.

- [ ] [NEXT-62] Between `RECOVERY` and the action or `No actionable item.`, each due audit prints `audit_due <name>: <sentence>`, `Next: <run>` escaped as NEXT-37 does, and a blank line; `<run>` is never interpreted.
- [ ] [NEXT-63] `--json` always carries `audits` after `ahead_of_caller_unavailable`: `{name, reason, anchor, sha, landings_since, days_since, run, error}` per due or unavailable entry, `[]` else; `run` is unescaped.
- [ ] [NEXT-64] `reason` and `<sentence>` follow the table below; `<anchor>` names the issue as NEXT-35 does, `<sha7>` is the commit's first seven characters; `anchor` is its number or id, `sha` the commit or `null`.
- [ ] [NEXT-65] An audit not due prints nothing and carries no entry. Each entry costs one listing of its label's newest issues, none without an entry, none under `state-ref`; landings come from local git.
- [ ] [NEXT-66] An anchor commit the local trunk lacks fetches the canonical remote once and reads the trunk again; one still absent is `anchor_off_trunk`, one now found is counted by the rule below.
- [ ] [NEXT-67] A failed fetch or listing prints `audit <name>: unavailable (<sentence>)`, no `Next:` line; `--json` has `reason` `unavailable`, `error` the sentence; work item and exit status stay (see E-NEXT-19).
- [ ] [NEXT-68] A due or unavailable audit never changes the exit status or the top-level `reason`: with no actionable item `next` still exits `3` and `reason` is `nothing_actionable`.

| `reason` | when | `<sentence>` |
|---|---|---|
| `landings` | `<k>` reaches the entry's `landings` | `<k> landings since <anchor>, audited through <sha7>` |
| `days` | `<k>` is below it, at least 1, and `<d>` reaches `days` | `<d> days and <k> landing(s) since <anchor>, audited through <sha7>` |
| `no_anchor` | no labelled issue holds the line | `no item labelled <label> holds an audited through line` |
| `anchor_malformed` | the newest line names no full 40-hex commit | `<anchor>'s audited through line names no full commit` |
| `anchor_off_trunk` | the commit is not among the last 5000 first-parent landings, NEXT-66 | `<anchor> audited through <sha7>, which is not among the last 5000 landings on <trunk>` |

## Never

- `aco next` never writes anything: it is a pure projection: it reads what `board` reads, plus the trunk's ahead-of-caller list and the state of each item that list names (NEXT-49..55), each audit's newest labelled issues and, only for an anchor the local trunk lacks, one fetch of the canonical remote (NEXT-62..68).
- `close:` never fires the cut proposal's own `Next:`/`Run:` lines: a closable container's own action, when it is also the top action, never carries a command -- NEXT-07 refuses to invent one.
- `parallel:`/`scope unknown:` never occupy or place a `board.recovery` item: a landed-but-open item is `close:`'s domain alone, never a `parallel:` candidate or an occupant that could crowd out a real free item behind it.
- The first action's own row is never repeated inside `parallel:`'s candidate list, whatever its own scope is.
- An overlap never withholds a free item: `parallel:` names the item with the overlap as its note, and the first action carries no note (`aco start` prints its overlaps, CLAIM-31).
- Exit `3` never carries any action-specific line: `No actionable item.` alone stands where `Next:`/`Run:` would; a due audit's own `Next:` line (NEXT-62) precedes it and is no action of the board.
- Exit `3` is never returned for a refusal (NEXT-24's `invalid_usage`/`unavailable`): those exit `2`, matching every other emitter refusal; `3` is `nothing_actionable`'s alone.
- `next --json` never carries an `action` key; the action type is the `reason` token.
- `next` never drops NEXT-42 because a git failure made a directory look like a file; it refuses with git's detail.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local
bare repository with `main` at one commit, a git identity, `origin/HEAD`, a
tracked `.aco/board.toml`, and `ACO_AGENT` set to `Ada`. Every
session below also names a fixed, deterministic fake `gh` as a setup
precondition (the shape `specs/landing-grammar.spec.md` already uses).
Every session runs from a linked worktree on branch `ada/lane` unless its
setup names the main checkout.

### E-NEXT-01 — the top-ranked work item, scoped

Setup: bare-remote, fake `gh`, issue `#10` open, complete, `scope = ["README.md"]`

```console
$ aco next
#10 score -10: Work
Next: Claim #10.
Run: aco claim 10
parallel: none
scope unknown: none
close: none
exit 0
```

### E-NEXT-02 — a scopeless item, proposed expectations, `--scope <paths>`

Setup: bare-remote, fake `gh`, issue `#10` open, no `scope`, one proposed `[[expectation]]`

```console
$ aco next
#10 score -10: Work
Next: Claim #10.
Run: aco claim 10 --scope <paths>
scope unknown
expectations unruled: refine before the pull
parallel: unknown (first action names no scope)
close: none
exit 0
```

### E-NEXT-03 — a container with an uncut slice row

Setup: bare-remote, fake `gh`, container `#181`, no open child, one `[[slice]]` row titled `Scheibe C`

```console
$ aco next
cut_slice #181: Scheibe C
Next: aco cut 181
parallel: none
scope unknown: none
close: none
exit 0
```

### E-NEXT-04 — a closable container, whatever its `Next` line says

Setup: bare-remote, fake `gh`, container `#182` with three closed children and no open child, no `[[slice]]` row, `Next` line `keiner`

```console
$ aco next
close_container #182: 3/3 children closed, no uncut row
parallel: none
scope unknown: none
close: #182
exit 0
```

The same container with a `Next` line still naming the next slice, or with open `#9` blocking it, prints the same lines.

### E-NEXT-05 — five candidates meeting nothing, capped at three

Setup: bare-remote, fake `gh`, six open items each naming its own disjoint scope

```console
$ aco next
#60 score -10: Alpha
Next: Ship Alpha.
Run: aco claim 60
parallel: #61 (1 path), #62 (1 path), #63 (1 path), and 2 more
scope unknown: none
close: none
exit 0
```

### E-NEXT-06 — `close:` unions a closable container and a recovery item

Setup: bare-remote, fake `gh`, a top-ranked item `#70`, a closable container `#71`, a
recovery item `#72` whose merged pull request typed a `Work-Item:` line for it while it stayed open

```console
$ aco next
RECOVERY
#72: close or re-project

#70 score 40: Top ranked work
Next: Ship it.
Run: aco claim 70
parallel: none
scope unknown: none
close: #71, #72
exit 0
```

### E-NEXT-07 — `--json`, the three action shapes

Setup: bare-remote, fake `gh`, container `#181` as in E-NEXT-03

```console
$ aco next --json
{"ok": true, "reason": "cut_slice", "recovery": [], "skipped": [], "parallel": {"first_scope_unknown": false, "candidates": [], "scope_unknown": []}, "close": [], "waiting_on_operator": [], "ideas": [], "number": 181, "title": "Epic", "slice": "Scheibe C", "cut_title": "Scheibe C", "command": "aco cut 181"}
exit 0
```

### E-NEXT-08 — `--json` refusal envelope, `--repo` under `storage = state-ref`

Setup: bare-remote, `storage = "state-ref"` tracked

```console
$ aco --repo acme/items next --json
2> ERROR: --repo is meaningless under storage = state-ref
{"ok": false, "reason": "invalid_usage", "message": "--repo is meaningless under storage = state-ref"}
exit 2
```

### E-NEXT-09 — a nested container's uncut row, never a `cut` that `cut` refuses

Setup: bare-remote, fake `gh`, container `#298` with one open child, the container `#299`; `#299` has no open child and one `[[slice]]` row titled `Scheibe Z` with `scope = ["docs/z.md"]`

```console
$ aco next
No actionable item.
parallel: none
scope unknown: none
close: none

SKIPPED
#298: container; claim a child
#299: nested container, which cut refuses; run aco item edit 299 --kind task and claim it with aco claim 299 --scope=docs/z.md --out-of-order <reason>
exit 3
$ aco cut 299 --title "Scheibe Z"
2> ERROR: #299 is itself a child of example/agent-coordination#298; nested containers are not supported
exit 2
```

The named `item edit --kind task` runs under either storage (ITEM-47), `#299` printed as the id the storage takes back; the named claim then claims the row's paths past any higher-ranked free item (NEXT-33), and once retyped `next`'s own `Run:` line names that same claim without `--out-of-order <reason>` (NEXT-30). A container naming its own top-level `scope` ends the reason `claim it with aco claim 299 --out-of-order <reason>` instead, the claim that derives that scope (NEXT-03); a row without a `scope` of its own, under a container without one, ends it `claim it with aco claim 299 --scope <paths> --out-of-order <reason>`. With two or more uncut rows, the `SKIPPED` reason reads `nested container, which cut refuses; move its slice rows to example/agent-coordination#298`, the parent named as `cut`'s refusal names it. The same holds when `#298` is a Feature or Task, closed, or in another repository: `next` reads the parent relation `cut` refuses on.

### E-NEXT-10 — a second cuttable container, and row fields holding a line break or control character

Setup: bare-remote, fake `gh`, containers `#181`, `#183`, `#184` and `#185`, each with no open child; `#181`'s row is `Scheibe C` and `#183`'s `-draft`, both with `scope = ["docs/c.md"]`; `#184`'s row 2 is titled `Zeile eins`, a line break, `Zeile zwei`; `#185`'s row 1 `done_when` holds U+000B

```console
$ aco next
cut_slice #181: Scheibe C
Next: aco cut 181
parallel: none
scope unknown: none
close: none

SKIPPED
#183: cut slice "-draft"; run aco cut 183
#184: slice row 2 title holds a line break or control character; make it one printable line
#185: slice row 1 done_when holds a line break or control character; make it one printable line
exit 0
```

### E-NEXT-11 — an unreadable item beside a readable one

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked; `aco-4470c5`'s file was stored before BODY-63 with a raw U+000B in a slice title, `aco-2620d6` is an unfilled Task

```console
$ aco next
No actionable item.
parallel: none
scope unknown: none
close: none

SKIPPED
aco-2620d6: body incomplete: Now, Next, Done when
aco-4470c5: body malformed: aco: aco block is not valid TOML: Illegal character '\x0b' (at line 8, column 18)
exit 3
$ aco item show aco-4470c5
2> ERROR: item aco-4470c5 has a malformed aco block (body malformed: aco: aco block is not valid TOML: Illegal character '\x0b' (at line 8, column 18)); repair it with aco item edit aco-4470c5 --base <body_hash> and a body whose aco block carries a valid [record]; aco item show aco-4470c5 --json prints the body_hash
exit 2
```

### E-NEXT-12 — a container whose one open child may be an unreadable item

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked; `aco-000001` is a filled Container whose one readable child is closed, `aco-3e26d9`'s file was hand-written with no `aco` block

```console
$ aco next
No actionable item.
parallel: none
scope unknown: none
close: none

SKIPPED
aco-3e26d9: body malformed: aco: no aco block
aco-000001: container; its open children do not read: aco-3e26d9
exit 3
$ aco item close aco-000001
2> ERROR: item aco-3e26d9 has a malformed aco block (body malformed: aco: no aco block); repair it with aco item edit aco-3e26d9 --base <body_hash> and a body whose aco block carries a valid [record]; aco item show aco-3e26d9 --json prints the body_hash
exit 2
```

### E-NEXT-13 — the top item waits on the operator

Setup: bare-remote, fake `gh`; `#230` is labelled `security` and carries a `wait` naming `operator`, `#11` is a scopeless open item

```console
$ aco next
#11 score -10: Top work
Next: Claim #11.
Run: aco claim 11 --scope <paths>
scope unknown
parallel: unknown (first action names no scope)
close: none
waiting on operator: #230
exit 0
$ aco next --json
{"ok": true, "reason": "work_item", "recovery": [], "skipped": [], "parallel": {"first_scope_unknown": true, "candidates": [], "scope_unknown": []}, "close": [], "waiting_on_operator": [230], "ideas": [], "number": 11, "score": -10, "title": "Top work", "next": "Claim #11.", "command": "aco claim 11 --scope <paths>", "ruling_landings": null, "ruling_old": null}
exit 0
```

### E-NEXT-14 — the top-ranked work item, seen from the main checkout

Setup: bare-remote, run from the main checkout on `main`, fake `gh`, issue `#10` titled `Work` open, complete, `scope = ["README.md"]`

```console
$ aco next
#10 score -10: Work
Next: Claim #10.
Run: aco start 10 --slug=work
parallel: none
scope unknown: none
close: none
exit 0
```

`aco start 10 --slug=work` then builds `issue-10-work` beside the checkout and claims `#10` there, as E-NEXT-01's `claim` would from that worktree. A title yielding no slug, such as `!!! ???`, prints `Run: aco start 10 --slug=10`; under `storage = "state-ref"` the id's own, `Run: aco start aco-1234ab --slug=aco-1234ab`.

The same item with `scope` naming five paths and no `whole` prints `Run: aco start 10 --slug=work --whole <reason>`; with the reason filled in, `aco start 10 --slug=work --whole 'One sweep over five files.'` claims it.

### E-NEXT-15 — containers the operator holds

Setup: bare-remote, fake `gh`, each container with no open child; `#441` carrying an `operator` wait with one `[[slice]]` row, `#442` carrying an `operator` wait with `Next` naming work and no row, `#443` carrying an `operator` wait with `Next` line `keiner` and no row, `#444` carrying a `trigger` wait with one `[[slice]]` row; `#11` a scopeless open item

```console
$ aco next
#11 score -10: Top work
Next: Claim #11.
Run: aco claim 11 --scope <paths>
scope unknown
parallel: unknown (first action names no scope)
close: #442, #443
waiting on operator: #441

SKIPPED
#444: waiting: <trigger text>
exit 0
```

`#441` gets no `cut`; `#444`, a trigger wait, is no operator wait: it gets no `cut` either, and `SKIPPED` names its wait (NEXT-59); `#442` and `#443` carry no uncut row, so they stay under `close:` alone whatever their wait or `Next` line says (NEXT-07, NEXT-28).

### E-NEXT-16 — a line sent back to its head

Setup: bare-remote, fake `gh`, `#7` with a ruled yes/no line 1 and an option line 2 sent back with `aco rule 7 --line 2 --unclear`; `#11` a scopeless open item

```console
$ aco next
#11 score -10: Top work
Next: Claim #11.
Run: aco claim 11 --scope <paths>
scope unknown
parallel: unknown (first action names no scope)
close: none
with head: #7 line 2
exit 0
$ aco next --json
{"ok": true, ..., "ideas": [], "with_head": [{"number": 7, "lines": [2]}], ...}
exit 0
```

### E-NEXT-17 — code built ahead of a closed item

Setup: bare-remote, fake `gh`, run from the main checkout, the trunk holds `.aco/ahead-of-caller.toml` with `[[code]]` `path = "src/token.py"`, `item = "#12"`, `reason = "token helper"`; `#12` is closed, `#11` a scopeless open item

```console
$ aco next
#11 score -10: Top work
Next: Claim #11.
Run: aco start 11 --slug=top-work --scope <paths>
scope unknown
parallel: unknown (first action names no scope)
close: none
ahead of caller: src/token.py: item 12 is closed (token helper)
exit 0
$ aco next --json
{"ok": true, ..., "with_head": [], "ahead_of_caller": [{"path": "src/token.py", "item": 12, "reason": "token helper", "state": "closed", "error": null}], "ahead_of_caller_unavailable": null, ...}
exit 0
```

### E-NEXT-18 — a candidate meeting a live claim and the first action

Setup: bare-remote, fake `gh`, open items `#50` (scope `src/a.py`) and `#51` (scope `docs/guide.md`, `src/a.py`); a live claim on issue `#99` holds scope `docs`

```console
$ aco next
#50 score -10: Alpha
Next: Ship Alpha.
Run: aco start 50 --slug=alpha
parallel: #51 (2 paths; overlaps issue #99 on docs/guide.md, issue #50 on src/a.py)
scope unknown: none
close: none
exit 0
$ aco next --json
{"ok": true, ..., "parallel": {"first_scope_unknown": false, "candidates": [{"number": 51, "scope": ["docs/guide.md", "src/a.py"], "overlaps": [{"issue": 99, "lane": null, "claim_id": "claim-99", "paths": ["docs/guide.md"]}, {"issue": 50, "lane": null, "claim_id": null, "paths": ["src/a.py"]}]}], "scope_unknown": []}, ...}
exit 0
```

### E-NEXT-19 — a due audit and a failed listing beside the top work item

Setup: bare-remote, fake `gh`, run from the main checkout, `.aco/board.toml` declares `[[audit]]` `name = "tests"`, `label = "audit-tests"`, `landings = 3`, `days = 7`, `run = "Run the audit skill."`, `name = "owners"` with `label = "audit-owners"` the same way; three landings follow the `audited through` commit of the newest `audit-tests` issue `#20`, the listing of `audit-owners` fails with `GitHub is down`; `#11` is a scopeless open item

```console
$ aco next
audit_due tests: 3 landings since #20, audited through 1a2b3c4
Next: Run the audit skill.

audit owners: unavailable (GitHub is down)

#11 score -10: Top work
Next: Claim #11.
Run: aco start 11 --slug=top-work --scope <paths>
scope unknown
parallel: unknown (first action names no scope)
close: none
exit 0
$ aco next --json
{"ok": true, ..., "ahead_of_caller_unavailable": null, "audits": [{"name": "tests", "reason": "landings", "anchor": 20, "sha": "1a2b3c4...", "landings_since": 3, "days_since": 0, "run": "Run the audit skill.", "error": null}, {"name": "owners", "reason": "unavailable", "anchor": null, "sha": null, "landings_since": null, "days_since": null, "run": "Run the audit skill.", "error": "GitHub is down"}], ...}
exit 0
```
