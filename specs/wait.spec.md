# `aco wait`

`aco wait ITEM --line N [--line N …] [--json]` waits on option lines of one
item and ends, exit `0`, as soon as one of the named lines is no longer open:
ruled, returned to its head or withdrawn. A session that has asked the
operator a card runs it in the background; the session wakes when the command
ends and reads the answer. `aco wait [--json]` with no item waits on the
repository's board and ends when `aco next` names an action or a line that
waited on the operator no longer does; a head with nothing to do runs it in the
background and wakes to pull. `--help` lists `--line` and `--json`, each with a
help line. This file owns the command, its `reason` vocabulary and the signal
that wakes it; `specs/output.spec.md` owns the `--json` envelope itself
(OUT-01), `specs/storage-pin.spec.md` the state-ref forge gate (PIN-04). `<n>`
is the item's own number, a printed `#<n>` its `storage = "github"` form and
the item id under `storage = "state-ref"` (PIN-30); `<k>` the 1-based line
index `--line` names, the same index `rulings` prints. An open line is an
option line neither ruled nor returned to its head (RUL-02's `open`).

## Behavior table

| state \ trigger | `aco wait ITEM --line N` or `aco wait` | `--json` |
|---|---|---|
| every named line open | WAIT-01, WAIT-07, WAIT-08, WAIT-09 | WAIT-02 |
| a named line not open at the start | WAIT-03 | WAIT-02 |
| a named line ruled, returned or withdrawn while it waits | WAIT-01 | WAIT-02 |
| `N` out of range | WAIT-05 | WAIT-11 |
| item does not exist, is a pull request, is closed, or its body is malformed | WAIT-04 | WAIT-11 |
| `--repo` given, `storage = "state-ref"` | WAIT-06 | WAIT-11 |
| a forge failure at the start, a forge failure that is not transient while it waits, or a signal that cannot be read | WAIT-10 | WAIT-10 |
| a transient forge failure while it waits | WAIT-10 | — |
| a ruling, return or withdrawal written by aco | WAIT-12 | — |
| the signal cannot be touched | WAIT-13 | — |
| no item, `aco next` names an action at the start or while it waits | WAIT-14, WAIT-15 | WAIT-16 |
| no item, a line that waited on the operator is no longer open | WAIT-14, WAIT-15 | WAIT-16 |
| no item, a ruling written by aco, a closed blocker, a released claim or an `until` date that arrives | WAIT-17, WAIT-18, WAIT-19 | — |
| no item, a transient failure while it waits | WAIT-20 | — |
| no item, a failure that is not transient | WAIT-20 | WAIT-20 |
| `--line` without an item, or an item without `--line` | WAIT-21 | WAIT-21 |

- [ ] [WAIT-01] `aco wait ITEM --line N` ends, exit `0`, as soon as one named line is no longer open, printing `CHANGED <label> line <k>: <state>` for each such named line (see E-WAIT-01).
  - The lines come in the item's order; a line named twice counts once.
  - `<state>` is the text `aco rulings` prints after the index (RUL-02, RUL-18, RUL-22): `ruled <ruling> <date>`, `with head <date>` or `withdrawn <date>`.
- [ ] [WAIT-02] `--json` on the same call prints the envelope with `reason: "changed"`, then `"item": <n>, "lines": [{"index": <k>, "state": "<state>"}, …]`, the lines as WAIT-01 names them (see E-WAIT-01).
- [ ] [WAIT-03] A named line that is not open when the command starts ends it at once, the same way as WAIT-01; a yes/no line is never open (see E-WAIT-02).
- [ ] [WAIT-04] A missing item, a pull request, a closed item or a MALFORMED body refuses, exit `2`, before any waiting (see E-WAIT-03):
  - a missing item: `<label> does not exist`; a pull request: `#<n> is a pull request, not an issue; wait needs an issue`
  - a closed item: `<label> is closed; there is nothing to wait for`
  - a MALFORMED body: `<label> <body defect sentence>; wait needs a valid aco block`; PIN-14/PIN-15's sentence replaces it under `state-ref`
- [ ] [WAIT-05] `--line N` outside the item's lines refuses `line <k> out of range: this item has <m> expectation line(s)`, exit `2`, before any waiting; `<m>` counts withdrawn lines (see E-WAIT-03).
- [ ] [WAIT-06] Under `storage = "state-ref"` it resolves the state-ref forge like `rule` (PIN-30's label); `--repo` there refuses the same as PIN-04.
- [ ] [WAIT-07] The command reads the item once at its start, then only the modification time of the item's signal file (WAIT-12), every two seconds; waiting costs no forge read.
  - It reads the item again when that time has moved, and ends or goes on waiting by WAIT-01; every read is fresh from the store, under `state-ref` a new fetch of the state ref.
- [ ] [WAIT-08] Every ten minutes it reads the item again whether or not the signal moved, so a line changed outside aco (a hand edit, another machine) ends it too.
- [ ] [WAIT-09] The command has no timeout and no other end of its own; the session that started it stops it.
- [ ] [WAIT-10] A forge failure at the start refuses `ERROR: <sentence>`, exit `2`, `--json` `reason: "unavailable"`, so do an unreadable signal file and a later read's forge failure that is not transient:
  - `cannot watch the item's signal at <signal path>: <detail>`, before the item is read
  - a later read that fails transiently prints one `WARNING: the item could not be read, still waiting: <sentence>` to stderr for a run of failed reads; the wait goes on and the next read that answers decides (WAIT-01, WAIT-04)
- [ ] [WAIT-11] `--json` on a refusal prints the envelope with the table's `reason` and the refusal sentence as `message`, exit `2` (see E-WAIT-03).
- [ ] [WAIT-12] Every write of a ruled, returned or withdrawn line that aco makes touches one file per item, after the write has been verified (see E-WAIT-04):
  - the writers are `aco rule`, `aco withdraw`, the board's decision and the `record_answer` tool
  - the file is `item-signals/<digest>` under aco's state directory, `<digest>` the one that names the item's lock file (RULE-40)
  - `ask`, `step`, `aco rescope` and `aco item edit` never touch it
- [ ] [WAIT-13] A signal that cannot be created or touched leaves the write standing, its result and exit status unchanged, and prints one warning line to stderr (see E-WAIT-04):
  - `WARNING: the ruling stands, but its signal at <signal path> could not be touched: <detail>`
  - a waiting session then learns the answer by WAIT-08
- [ ] [WAIT-14] `aco wait [--json]` without an item ends, exit `0`, when `aco next` names an action or a line that waited on the operator at its previous read no longer does (see E-WAIT-05, E-WAIT-06).
  - It ends at once when `aco next` names an action at its start; it has no timeout (WAIT-09).
  - A line of an item that is no longer open is not reported.
- [ ] [WAIT-15] It prints `ACTIONABLE <label>` for the item `aco next` names, then `CHANGED <label> line <k>: <state>` (the WAIT-01 shape) for each changed line, in board order (see E-WAIT-05, E-WAIT-06).
- [ ] [WAIT-16] `--json` prints `reason: "actionable"` with `"item": <n>` when an action is named, else `reason: "changed"`, and `"lines": [{"item": <n>, "index": <k>, "state": "<state>"}, …]` (see E-WAIT-05).
  - An `actionable` envelope carries `lines` only when lines changed too; a `changed` one always does (see E-WAIT-06).
- [ ] [WAIT-17] Every two seconds it looks at the signal (WAIT-12) of each item with a line that waited on the operator at its last read, and reads only that item again when its signal moved (see E-WAIT-05).
  - A ruling through the board, `record_answer` or `aco rule` thus ends it in about two seconds, with the lines of that item that no longer wait; the board read is not needed and `aco next` is not asked.
  - A signal is first looked at after the read that found its item, so the item is read once more then: a ruling in between is not lost.
  - An item that is closed is not reported; one that no longer reads as an item is left to the next board read.
- [ ] [WAIT-18] Every minute it checks whether the board changed, and reads it when it did:
  - under `storage = "github"`: one conditional request each for the repository's most recently updated issue and for each open blocker in another repository
  - under either storage: a read of the state ref's tip; under `state-ref` it is the only check
  - an open blocker in another repository that a read found for the first time is read once more after its first probe, for it may have closed in between
- [ ] [WAIT-19] It reads the board every hour, and on the first tick on or after 00:00 UTC of the earliest `until` date still ahead; the date is compared on each tick and found again after each read.
- [ ] [WAIT-20] A forge answer "not modified" means unchanged, whatever the exit status of the call; "modified" means changed and its tag is sent back as it came (see E-WAIT-08):
  - a transient forge failure, or a failed read of the state ref's tip, prints one `WARNING: the board could not be read, still waiting: <sentence>` to stderr per run of failures; the wait goes on
  - a failure at the start, or any other failure, refuses `ERROR: <sentence>`, exit `2`, `--json` `reason: "unavailable"`
- [ ] [WAIT-21] `--line` without an item, or an item without `--line`, refuses `wait needs an item together with --line, or neither of them`, exit `2`, `--json` `reason: "invalid_usage"` (see E-WAIT-07).
  - `aco wait ITEM --line N` is WAIT-01 to WAIT-13 unchanged.

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| (the success) | `changed` |
| (the success, with an item) | `actionable` |
| WAIT-04 (missing item, pull request, closed item, malformed body) | `invalid_item` |
| WAIT-05 (out of range) | `line_out_of_range` |
| WAIT-06 (`--repo` under `storage = state-ref`), WAIT-21, the parser's own refusals | `invalid_usage` |
| WAIT-10 and WAIT-20 (a forge failure at the start or that is not transient, a signal that cannot be read) | `unavailable` |

## Never

- `aco wait` never writes: it reads the item or the board, the signals' modification times and the forge's answers, nothing else.
- `aco wait` never ends on its own: no timeout, no limit of reads (WAIT-09).
- `aco wait` never reports a change it did not read: a signal or an answer only makes it read sooner, the item's lines and `aco next` decide (WAIT-07, WAIT-14).
- `aco wait` never pushes into a session: the head that ran it wakes when the command ends.
- A failed signal never fails a ruling, a return or a withdrawal (WAIT-13).
- The signal records nothing about who asked or who waits: a session that restarts starts `aco wait` again.
- `aco wait` never tells who changed the line.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local
bare repository with `main` at one commit, a git identity and `origin/HEAD`;
`<item-id>` is the state-ref id a session itself minted, `<today>` the
runner's own UTC date. Each example starts from the same item: line 1 a ruled
yes/no line, lines 2 and 3 open option lines.

### E-WAIT-01 — a line ruled while the command waits, text and `--json`

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with the three lines above

Started in one shell while nobody has ruled either line, then
`aco rule <item-id> --line 3 --option A --via chat` run in another:

```console
$ aco wait <item-id> --line 2 --line 3
CHANGED <item-id> line 3: ruled A <today>
exit 0
```

With `--json`, the same run ends with:

```console
$ aco wait <item-id> --line 2 --line 3 --json
{"ok": true, "reason": "changed", "item": <n>, "lines": [{"index": 3, "state": "ruled A <today>"}]}
exit 0
```

Each `aco wait` ends within a few seconds of the ruling; it read the item once
at its start and once more when the signal moved.

### E-WAIT-02 — a line that is not open at the start ends the command at once

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with the three lines above, line 2 withdrawn

```console
$ aco wait <item-id> --line 1 --line 2 --line 3
CHANGED <item-id> line 1: ruled yes <today>
CHANGED <item-id> line 2: withdrawn <today>
exit 0
```

### E-WAIT-03 — refusals before any waiting

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with the three lines above

```console
$ aco wait <item-id> --line 4
2> ERROR: line 4 out of range: this item has 3 expectation line(s)
exit 2
$ aco wait <item-id> --line 4 --json
2> ERROR: line 4 out of range: this item has 3 expectation line(s)
{"ok": false, "reason": "line_out_of_range", "message": "line 4 out of range: this item has 3 expectation line(s)"}
exit 2
```

### E-WAIT-04 — the signal after a ruling, and a signal that cannot be touched

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with the three lines above, `XDG_STATE_HOME` naming a directory

```console
$ aco rule <item-id> --line 2 --option A --via chat
RULED <item-id> line 2 A; 1 line(s) still open
exit 0
```

`<state>/aco/item-signals/<digest>` exists, `<digest>` the name of the item's file under `<state>/aco/item-locks/`. The same call with `<state>/aco/item-signals` a regular file prints `RULED …` as above, exit `0`, and on stderr:

```console
2> WARNING: the ruling stands, but its signal at <state>/aco/item-signals/<digest> could not be touched: <detail>
```

### E-WAIT-05 — an idle head waits on the board and a card is ruled

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open, labelled `needs-operator`, with the three lines above and no other open item

Started in one shell, then `aco rule <item-id> --line 3 --option A --via chat` run in another:

```console
$ aco wait
CHANGED <item-id> line 3: ruled A <today>
exit 0
$ aco wait --json
{"ok": true, "reason": "changed", "lines": [{"item": "<item-id>", "index": 3, "state": "ruled A <today>"}]}
exit 0
```

Each ends within a few seconds of the ruling.

### E-WAIT-06 — an action at the start

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open and unclaimed, with a complete `aco` block and no blocker

```console
$ aco wait
ACTIONABLE <item-id>
exit 0
$ aco wait --json
{"ok": true, "reason": "actionable", "item": "<item-id>"}
exit 0
```

A blocker in another repository that closes, a claim that is released or an `until` date that arrives ends it the same way, within a minute, a minute and the day's first tick respectively.

### E-WAIT-07 — half a target

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked

```console
$ aco wait <item-id>
2> ERROR: wait needs an item together with --line, or neither of them
exit 2
$ aco wait --line 2 --json
2> ERROR: wait needs an item together with --line, or neither of them
{"ok": false, "reason": "invalid_usage", "message": "wait needs an item together with --line, or neither of them"}
exit 2
```

### E-WAIT-08 — a failure while it waits

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, the remote unreachable for two minutes while `aco wait` runs

```console
$ aco wait
2> WARNING: the board could not be read, still waiting: <sentence>
exit 0
```

The warning appears once for the failed minutes; the wait goes on and ends by WAIT-14 once the remote answers.
