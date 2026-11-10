# `aco wait`

`aco wait ITEM --line N [--line N …] [--json]` waits on option lines of one
item and ends, exit `0`, as soon as one of the named lines is no longer open:
ruled, returned to its head or withdrawn. A session that has asked the
operator a card runs it in the background; the session wakes when the command
ends and reads the answer. `--help` lists `--line` and `--json`, each with a
help line. This file owns the command, its `reason` vocabulary and the signal
that wakes it; `specs/output.spec.md` owns the `--json` envelope itself
(OUT-01), `specs/storage-pin.spec.md` the state-ref forge gate (PIN-04). `<n>`
is the item's own number, a printed `#<n>` its `storage = "github"` form and
the item id under `storage = "state-ref"` (PIN-30); `<k>` the 1-based line
index `--line` names, the same index `rulings` prints. An open line is an
option line neither ruled nor returned to its head (RUL-02's `open`).

## Behavior table

| state \ trigger | `aco wait ITEM --line N` | `--json` |
|---|---|---|
| every named line open | WAIT-01, WAIT-07, WAIT-08, WAIT-09 | WAIT-02 |
| a named line not open at the start | WAIT-03 | WAIT-02 |
| a named line ruled, returned or withdrawn while it waits | WAIT-01 | WAIT-02 |
| `N` out of range | WAIT-05 | WAIT-11 |
| item does not exist, is a pull request, is closed, or its body is malformed | WAIT-04 | WAIT-11 |
| `--repo` given, `storage = "state-ref"` | WAIT-06 | WAIT-11 |
| a forge failure, at the start or while it waits | WAIT-10 | WAIT-10 |
| a ruling, return or withdrawal written by aco | WAIT-12 | — |
| the signal cannot be touched | WAIT-13 | — |

- [ ] [WAIT-01] `aco wait ITEM --line N` ends, exit `0`, as soon as one named line is no longer open, and prints one `CHANGED <label> line <k>: <state>` per named line that is no longer open, in the order of the item's lines; `<state>` is the text `aco rulings` prints for that line after its index (RUL-02, RUL-18, RUL-22): `ruled <ruling> <date>`, `with head <date>` or `withdrawn <date>` (see E-WAIT-01).
- [ ] [WAIT-02] `--json` on the same call prints the envelope with `reason: "changed"`, then `"item": <n>, "lines": [{"index": <k>, "state": "<state>"}, …]`, the lines as WAIT-01 names them (see E-WAIT-01).
- [ ] [WAIT-03] A named line that is not open when the command starts ends it at once, the same way as WAIT-01; a yes/no line is never open (see E-WAIT-02).
- [ ] [WAIT-04] A missing item refuses `<label> does not exist`, a pull request `#<n> is a pull request, not an issue; wait needs an issue`, a closed item `<label> is closed; there is nothing to wait for`, a MALFORMED body `<label> <body defect sentence>; wait needs a valid aco block` (PIN-14/PIN-15's sentence replaces it under `state-ref`), exit `2`, before any waiting (see E-WAIT-03).
- [ ] [WAIT-05] `--line N` outside the item's lines refuses `line <k> out of range: this item has <m> expectation line(s)`, exit `2`, before any waiting; `<m>` counts withdrawn lines (see E-WAIT-03).
- [ ] [WAIT-06] Under `storage = "state-ref"` it resolves the state-ref forge like `rule` (PIN-30's label); `--repo` there refuses the same as PIN-04.
- [ ] [WAIT-07] The command reads the item once at its start and then only the modification time of the item's signal file (WAIT-12), every two seconds; it reads the item again when that time has moved, and ends or goes on waiting by WAIT-01. Waiting costs no forge read.
- [ ] [WAIT-08] Every ten minutes it reads the item again whether or not the signal moved, so a line changed outside aco (a hand edit, another machine) ends it too.
- [ ] [WAIT-09] The command has no timeout and no other end of its own; the session that started it stops it.
- [ ] [WAIT-10] Every forge failure, the read at the start and a later read included, refuses `ERROR: <sentence>`, exit `2`, `--json` `reason: "unavailable"`.
- [ ] [WAIT-11] `--json` on a refusal prints the envelope with the table's `reason` and the refusal sentence as `message`, exit `2` (see E-WAIT-03).
- [ ] [WAIT-12] Every write of a ruled, returned or withdrawn line that aco makes (`aco rule`, `aco withdraw`, the board's decision, the `record_answer` tool) touches one file per item, `item-signals/<digest>` under aco's state directory, after the write has been verified; `<digest>` is the one that names the item's lock file (RULE-40), from one function. `ask`, `step`, `aco rescope` and `aco item edit` never touch it (see E-WAIT-04).
- [ ] [WAIT-13] A signal that cannot be created or touched leaves the write standing, its result and exit status unchanged, and prints one `WARNING: the ruling stands, but its signal at <signal path> could not be touched: <detail>` line to stderr; a waiting session then learns the answer by WAIT-08 (see E-WAIT-04).

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| (the success) | `changed` |
| WAIT-04 (missing item, pull request, closed item, malformed body) | `invalid_item` |
| WAIT-05 (out of range) | `line_out_of_range` |
| WAIT-06 (`--repo` under `storage = state-ref`), the parser's own refusals | `invalid_usage` |
| WAIT-10 (a forge failure) | `unavailable` |

## Never

- `aco wait` never writes: it reads the item and the signal's modification time, nothing else.
- `aco wait` never ends on its own: no timeout, no limit of reads (WAIT-09).
- `aco wait` never reports a change it did not read: the signal only makes it read sooner, the item's lines decide (WAIT-07).
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
