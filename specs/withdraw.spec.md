# `aco withdraw`

`aco withdraw ITEM --line N [--line N …] [--json]` takes back expectation
lines nobody has ruled: an open option line, or one the operator sent back to
its head. It is the head's own act on its own question; the operator's
decisions go through `aco rule` (`specs/rule.spec.md`). A withdrawn line keeps
its index and its `text` and gains `withdrawn_on`, the form
`specs/body-block.spec.md` owns (BODY-104..106); every reader leaves it off
the board and out of the open count. `aco withdraw ITEM --step [--json]`
takes back the head's own step: the item's `wait` on the operator and its
`[step]` table, as the line form takes back a line. `--help` lists `--line`,
`--step` and `--json`, each with a help line. This file owns the `WITHDRAWN` line, `withdraw`'s own
refusals and its `reason` vocabulary; `specs/output.spec.md` owns the
`--json` envelope itself (OUT-nn), and `specs/storage-pin.spec.md` the
state-ref forge gate (PIN-04). `<n>` is the item's own number, a printed
`#<n>` its `storage = "github"` form and the item id under
`storage = "state-ref"` (PIN-30); `<k>` the 1-based line index `--line` names,
the same index `rulings` prints; `<m>` in a success line counts the open lines
left, never a withdrawn one.

## Behavior table

| state \ trigger | `aco withdraw ITEM --line N` | `aco withdraw ITEM --step` | `--json` |
|---|---|---|---|
| an open option line | WITHDRAW-01, WITHDRAW-02 | — | WITHDRAW-03 |
| an option line with its head | WITHDRAW-01, WITHDRAW-02 | — | WITHDRAW-03 |
| several named lines | WITHDRAW-04, WITHDRAW-05 | — | WITHDRAW-05 |
| `N` out of range | WITHDRAW-06 | — | WITHDRAW-14 |
| line `N` already withdrawn | WITHDRAW-07 | — | WITHDRAW-14 |
| line `N` ruled, an option line or a yes/no line | WITHDRAW-08 | — | WITHDRAW-14 |
| a line named twice | WITHDRAW-09 | — | WITHDRAW-14 |
| an operator `wait`, with a step table of any form or none | — | WITHDRAW-19, WITHDRAW-20, WITHDRAW-22 | WITHDRAW-24 |
| the label cannot be removed | — | WITHDRAW-25 | WITHDRAW-24 |
| no operator `wait` (none, a date, a trigger) | — | WITHDRAW-21 | WITHDRAW-14 |
| item does not exist, or is a pull request | WITHDRAW-10 | WITHDRAW-10 | WITHDRAW-14 |
| item body malformed | WITHDRAW-11 | WITHDRAW-11 | WITHDRAW-14 |
| `--repo` given, `storage = "state-ref"` | WITHDRAW-12 | WITHDRAW-12 | WITHDRAW-14 |
| both `--line` and `--step`, or neither | WITHDRAW-23 | WITHDRAW-23 | WITHDRAW-23 |
| a forge failure, the body write included | WITHDRAW-13 | WITHDRAW-13 | WITHDRAW-13 |
| the body check answers the write | WITHDRAW-17 | WITHDRAW-17 | WITHDRAW-17 |
| the item's lock cannot be taken | WITHDRAW-16 | WITHDRAW-16 | WITHDRAW-16 |
| two writers of one item on this machine | WITHDRAW-15 | WITHDRAW-15 | — |
| a withdrawal written | WITHDRAW-18 | WITHDRAW-18 | — |

- WITHDRAW-01: An open or returned option line makes `aco withdraw ITEM --line N` print `WITHDRAWN #<n> line <k>; <m> line(s) still open`, exit `0` (see E-WITHDRAW-01).
- WITHDRAW-02: That line's entry becomes its `text` and today's UTC `withdrawn_on`, nothing else, at the same index; every other entry keeps its values (BODY-88, BODY-104).
- WITHDRAW-03: `--json` on the same call prints the envelope with `reason: "withdrawn"`, then `"item": <n>, "index": <k>, "withdrawn_on": "<date>", "open": <m>` (see E-WITHDRAW-01).
- WITHDRAW-04: `--line` may repeat: each named line is checked in the order written by WITHDRAW-06..08, and all are written in one body write with one UTC date, or none is.
- WITHDRAW-05: Several lines print `WITHDRAWN #<n> lines <k>, …; <m> line(s) still open`; their `--json` carries `"lines": [{"index": <k>}, …]` in place of `index` (see E-WITHDRAW-02).
- WITHDRAW-06: `--line N` outside the item's lines refuses `line <k> out of range: this item has <m> expectation line(s)`, exit `2`, before any write; `<m>` counts withdrawn lines.
- WITHDRAW-07: A line already withdrawn refuses `line <k> was withdrawn by its head`, exit `2`, before any write, after WITHDRAW-06 (see E-WITHDRAW-03).
- WITHDRAW-08: A ruled line, an option line or a yes/no line, refuses `line <k> is already ruled; a ruled line stays as it is`, exit `2`, before any write, after WITHDRAW-07 (see E-WITHDRAW-03).
- WITHDRAW-09: A `--line` naming a line an earlier `--line` named refuses `line <k> is named twice`, exit `2`, before any forge call.
- WITHDRAW-10: A missing item refuses `<label> does not exist`, a pull request `#<n> is a pull request, not an issue; withdraw needs an issue`, exit `2`, before any write.
- WITHDRAW-11: A MALFORMED item body refuses `<label> <body defect sentence>; withdraw needs a valid aco block`, exit `2`, before any write; PIN-14/PIN-15's sentence replaces it under `state-ref`.
- WITHDRAW-12: Under `storage = "state-ref"` it resolves the state-ref forge like `rule` (PIN-30's label); `--repo` there refuses the same as PIN-04.
- WITHDRAW-17: A withdrawal write the body check answers (OUT-10) refuses with its sentence, exit `2`, `--json` OUT-11's `reason` and `kept`; the withdrawal is written, a step's label stays (see E-WITHDRAW-06).
- WITHDRAW-13: Every other forge failure, the read and the write included, refuses `ERROR: <sentence>`, exit `2`, `--json` `reason: "unavailable"`; under `state-ref` a write since the read refuses with CAS-20.
- WITHDRAW-15: Every withdrawal runs in the item's turn (RULE-40): writers of one item on this machine are serialized, so a withdrawal and a ruling on distinct lines both land; a held lock prints RULE-42's line.
- WITHDRAW-16: A lock that the item's turn cannot take refuses as RULE-41 does, `--json` `reason: "unavailable"`, nothing read or written (see E-WITHDRAW-05).
- WITHDRAW-18: A verified line withdrawal touches the item's signal (WAIT-12), a step withdrawal none; a failed signal changes no result or exit status (WAIT-13); a refused write touches nothing.
- WITHDRAW-14: `--json` on a refusal prints the envelope with the table's `reason` and the refusal sentence as `message`, exit `2` (see E-WITHDRAW-04).
- WITHDRAW-19: `aco withdraw ITEM --step` takes back the head's own step: its `wait` and `[step]` table go, then the `github` label `needs-operator`; it prints `WITHDRAWN #<n> step`, exit `0` (see E-WITHDRAW-07).
- WITHDRAW-20: It writes no other field (`now` and `next` included), never closes the item, writes the body once in the item's turn (WITHDRAW-15) and removes the label after that write stands.
- WITHDRAW-21: An item whose block holds no operator `wait` (none, a date or a trigger) refuses `#<n> waits on no step of the operator`, exit `2`, before any write; `reason` is `no_step` (see E-WITHDRAW-08).
- WITHDRAW-22: The item's state decides nothing: a closed item, one a non-member wrote and a step of any stored form (a `paste` table, an old `actions` table, none) are withdrawn alike.
- WITHDRAW-23: `--line` and `--step` exclude each other and one is required: both, or neither, refuse as the parser does (`invalid_usage`); `--help` lists `--step` with a help line.
- WITHDRAW-24: `--json` prints `reason: "withdrawn"`, `"item": <n>`, `"step": "<the step line>"` and, with WITHDRAW-25, `"note": "<its sentence>"` (see E-WITHDRAW-07).
- WITHDRAW-25: A label the forge will not remove keeps the written body: stderr gets `WARNING: <note>`, which names `gh issue edit <n> --remove-label needs-operator`, exit `0`.

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| WITHDRAW-07 (already withdrawn) | `already_withdrawn` |
| WITHDRAW-08 (ruled) | `already_ruled` |
| WITHDRAW-06 (out of range) | `line_out_of_range` |
| WITHDRAW-10 (missing item, pull request), WITHDRAW-11 (malformed body) | `invalid_item` |
| WITHDRAW-09 (a line named twice), WITHDRAW-12 (`--repo` under `storage = state-ref`), WITHDRAW-23 (both forms, or neither), the parser's own refusals | `invalid_usage` |
| WITHDRAW-21 (no operator `wait`) | `no_step` |
| WITHDRAW-13 (a forge failure), WITHDRAW-16 (the item's lock) | `unavailable` |
| WITHDRAW-17 (the body check answers the write) | `overwritten` (with `kept`) or `not_verified`, as OUT-11 |

An already withdrawn line answers its own `reason`, so a head that re-runs
after an `unavailable`, an `overwritten` or a `not_verified` on `github`, where
the write may have landed, tells "done" from "stop, it is ruled".

## Never

- `aco withdraw` never withdraws a ruled line: every check runs on the body it read in the same call. Writers of one item through aco on this machine are serialized (WITHDRAW-15), so none overwrites another's ruling; on `github` a hand edit (`gh issue edit`, the browser) or another machine's write is found by the check when it lands between aco's read and the check right after its write, and refuses with its sentence (WITHDRAW-17); a hand edit saved later over an older copy still overwrites the write unseen; under `state-ref` that write refuses (CAS-20).
- `aco withdraw` never writes a key beside `text` and `withdrawn_on`: a returned line's `returned_on` and `returned_note` leave with it; the forge's edit history keeps the note.
- `aco withdraw` never changes another expectation line's values or a byte outside the block; the block itself is rendered canonically (BODY-88), and under `state-ref` the record merge sets `updated_at` as for `rule`.
- `aco withdraw` never takes `--via` or `--card-hash`: it decides nothing for the operator.
- `aco withdraw` never checks who runs it: aco cannot tell a head from another session, and the forge's edit history is the record.
- `aco serve`'s decision board never calls `aco withdraw`.
- `aco withdraw` reaches the same checkout-less refusal `specs/check.spec.md` owns (CHECK-10) before it resolves the forge or the item.
- `aco withdraw --step` never answers the step, never writes `now` and never touches an option line; the operator's own way stays the board's and `answer_step`'s (ABRD-168, MCP-72).

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local
bare repository with `main` at one commit, a git identity, `origin/HEAD`,
and `ACO_AGENT` set to `Ada`; `<item-id>` is the state-ref id a session
itself minted, `<n>` that same item's own bare number, `<today>` the
runner's own UTC date. Each example starts from the same item: line 1 a ruled
yes/no line, lines 2 and 3 open option lines.

### E-WITHDRAW-01 — withdrawing one open line, text and `--json`

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with the three lines above

```console
$ aco withdraw <item-id> --line 2
WITHDRAWN <item-id> line 2; 1 line(s) still open
exit 0
$ aco withdraw <item-id> --line 3 --json
{"ok": true, "reason": "withdrawn", "item": <n>, "index": 3, "withdrawn_on": "<today>", "open": 0}
exit 0
```

After the first call `aco rulings` lists `2 withdrawn <today>: <its text>`
and `aco check <item-id>` prints `ISSUE <item-id> body ok`.

### E-WITHDRAW-02 — two lines in one body write

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with the three lines above

```console
$ aco withdraw <item-id> --line 2 --line 3
WITHDRAWN <item-id> lines 2, 3; 0 line(s) still open
exit 0
```

The state ref gains one commit.

### E-WITHDRAW-03 — a ruled and an already withdrawn line refuse before any write

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with the three lines above, line 2 already withdrawn

```console
$ aco withdraw <item-id> --line 1
2> ERROR: line 1 is already ruled; a ruled line stays as it is
exit 2
$ aco withdraw <item-id> --line 2
2> ERROR: line 2 was withdrawn by its head
exit 2
```

The state ref's tip is unchanged after each refusal.

### E-WITHDRAW-04 — a refusal's own `--json` envelope

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with the three lines above, line 2 already withdrawn

```console
$ aco withdraw <item-id> --line 2 --json
2> ERROR: line 2 was withdrawn by its head
{"ok": false, "reason": "already_withdrawn", "message": "line 2 was withdrawn by its head"}
exit 2
```

### E-WITHDRAW-05 — the item's lock cannot be taken

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with an open option line 1, `XDG_STATE_HOME` naming a regular file

```console
$ aco withdraw <item-id> --line 1 --json
2> ERROR: cannot lock the item at <state>/aco/item-locks/<digest>: <detail>
{"ok": false, "reason": "unavailable", "message": "cannot lock the item at <state>/aco/item-locks/<digest>: <detail>"}
exit 2
```

### E-WITHDRAW-06 — the check finds the withdrawal not verified

Setup: bare-remote, `storage = "github"`, fake `gh`, item `#7` open with an open option line 2, the edit history unreadable after the write

```console
$ aco withdraw 7 --line 2 --json
2> ERROR: #7 body written, not verified (<cause>)
{"ok": false, "reason": "not_verified", "message": "#7 body written, not verified (<cause>)"}
exit 2
```

### E-WITHDRAW-07 — taking back a step, text and `--json`

Setup: bare-remote, `storage = "github"`, fake `gh`, item `#7` open, labelled `needs-operator`, waiting on `Decide.` with a `step` table

```console
$ aco withdraw 7 --step
WITHDRAWN #7 step
exit 0
$ aco withdraw 7 --step --json
{"ok": true, "reason": "withdrawn", "item": 7, "step": "Decide."}
exit 0
```

Forge requests of one call: read #7, write #7's body, remove the label `needs-operator` from #7. The stored block has no `wait` and no `[step]`; `now` and `next` are as they were.

### E-WITHDRAW-08 — an item without a step

Setup: bare-remote, `storage = "github"`, fake `gh`, item `#7` open with no `wait`

```console
$ aco withdraw 7 --step
2> ERROR: #7 waits on no step of the operator
exit 2
$ aco withdraw 7 --step --json
2> ERROR: #7 waits on no step of the operator
{"ok": false, "reason": "no_step", "message": "#7 waits on no step of the operator"}
exit 2
```

Forge requests of one call: read #7, no write.
