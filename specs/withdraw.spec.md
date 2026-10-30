# `aco withdraw`

`aco withdraw ITEM --line N [--line N …] [--json]` takes back expectation
lines nobody has ruled: an open option line, or one the operator sent back to
its head. It is the head's own act on its own question; the operator's
decisions go through `aco rule` (`specs/rule.spec.md`). A withdrawn line keeps
its index and its `text` and gains `withdrawn_on`, the form
`specs/body-block.spec.md` owns (BODY-104..106); every reader leaves it off
the board and out of the open count. `--help` lists `--line` and `--json`,
each with a help line. This file owns the `WITHDRAWN` line, `withdraw`'s own
refusals and its `reason` vocabulary; `specs/output.spec.md` owns the
`--json` envelope itself (OUT-nn), and `specs/storage-pin.spec.md` the
state-ref forge gate (PIN-04). `<n>` is the item's own number, a printed
`#<n>` its `storage = "github"` form and the item id under
`storage = "state-ref"` (PIN-30); `<k>` the 1-based line index `--line` names,
the same index `rulings` prints; `<m>` in a success line counts the open lines
left, never a withdrawn one.

## Behavior table

| state \ trigger | `aco withdraw ITEM --line N` | `--json` |
|---|---|---|
| an open option line | WITHDRAW-01, WITHDRAW-02 | WITHDRAW-03 |
| an option line with its head | WITHDRAW-01, WITHDRAW-02 | WITHDRAW-03 |
| several named lines | WITHDRAW-04, WITHDRAW-05 | WITHDRAW-05 |
| `N` out of range | WITHDRAW-06 | WITHDRAW-14 |
| line `N` already withdrawn | WITHDRAW-07 | WITHDRAW-14 |
| line `N` ruled, an option line or a yes/no line | WITHDRAW-08 | WITHDRAW-14 |
| a line named twice | WITHDRAW-09 | WITHDRAW-14 |
| item does not exist, or is a pull request | WITHDRAW-10 | WITHDRAW-14 |
| item body malformed | WITHDRAW-11 | WITHDRAW-14 |
| `--repo` given, `storage = "state-ref"` | WITHDRAW-12 | WITHDRAW-14 |
| a forge failure, the body write included | WITHDRAW-13 | WITHDRAW-13 |

- [ ] [WITHDRAW-01] An open or returned option line makes `aco withdraw ITEM --line N` print `WITHDRAWN #<n> line <k>; <m> line(s) still open`, exit `0` (see E-WITHDRAW-01).
- [ ] [WITHDRAW-02] That line's entry becomes its `text` and today's UTC `withdrawn_on`, nothing else, at the same index; every other entry keeps its values (BODY-88, BODY-104).
- [ ] [WITHDRAW-03] `--json` on the same call prints the envelope with `reason: "withdrawn"`, then `"item": <n>, "index": <k>, "withdrawn_on": "<date>", "open": <m>` (see E-WITHDRAW-01).
- [ ] [WITHDRAW-04] `--line` may repeat: each named line is checked in the order written by WITHDRAW-06..08, and all are written in one body write with one UTC date, or none is.
- [ ] [WITHDRAW-05] Several lines print `WITHDRAWN #<n> lines <k>, …; <m> line(s) still open`; their `--json` carries `"lines": [{"index": <k>}, …]` in place of `index` (see E-WITHDRAW-02).
- [ ] [WITHDRAW-06] `--line N` outside the item's lines refuses `line <k> out of range: this item has <m> expectation line(s)`, exit `2`, before any write; `<m>` counts withdrawn lines.
- [ ] [WITHDRAW-07] A line already withdrawn refuses `line <k> was withdrawn by its head`, exit `2`, before any write, after WITHDRAW-06 (see E-WITHDRAW-03).
- [ ] [WITHDRAW-08] A ruled line, an option line or a yes/no line, refuses `line <k> is already ruled; a ruled line stays as it is`, exit `2`, before any write, after WITHDRAW-07 (see E-WITHDRAW-03).
- [ ] [WITHDRAW-09] A `--line` naming a line an earlier `--line` named refuses `line <k> is named twice`, exit `2`, before any forge call.
- [ ] [WITHDRAW-10] A missing item refuses `<label> does not exist`, a pull request `#<n> is a pull request, not an issue; withdraw needs an issue`, exit `2`, before any write.
- [ ] [WITHDRAW-11] A MALFORMED item body refuses `<label> <body defect sentence>; withdraw needs a valid aco block`, exit `2`, before any write; PIN-14/PIN-15's sentence replaces it under `state-ref`.
- [ ] [WITHDRAW-12] Under `storage = "state-ref"` it resolves the state-ref forge like `rule` (PIN-30's label); `--repo` there refuses the same as PIN-04.
- [ ] [WITHDRAW-13] A forge failure, the item read and the body write included, refuses `ERROR: <sentence>`, exit `2`, `--json` `reason: "unavailable"`; under `state-ref` a write since the read refuses with CAS-20.
- [ ] [WITHDRAW-14] `--json` on a refusal prints the envelope with the table's `reason` and the refusal sentence as `message`, exit `2` (see E-WITHDRAW-04).

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| WITHDRAW-07 (already withdrawn) | `already_withdrawn` |
| WITHDRAW-08 (ruled) | `already_ruled` |
| WITHDRAW-06 (out of range) | `line_out_of_range` |
| WITHDRAW-10 (missing item, pull request), WITHDRAW-11 (malformed body) | `invalid_item` |
| WITHDRAW-09 (a line named twice), WITHDRAW-12 (`--repo` under `storage = state-ref`), the parser's own refusals | `invalid_usage` |
| WITHDRAW-13 (a forge failure) | `unavailable` |

An already withdrawn line answers its own `reason`, so a head that re-runs
after an `unavailable` on `github`, where the write may have landed, tells
"done" from "stop, it is ruled".

## Never

- `aco withdraw` never withdraws a ruled line: every check runs on the body it read in the same call. On `github` an issue body has no compare-and-swap, so a ruling stored between that read and the write is overwritten, as for `aco rule`; under `state-ref` that write refuses (CAS-20).
- `aco withdraw` never writes a key beside `text` and `withdrawn_on`: a returned line's `returned_on` and `returned_note` leave with it; the forge's edit history keeps the note.
- `aco withdraw` never changes another expectation line's values or a byte outside the block; the block itself is rendered canonically (BODY-88), and under `state-ref` the record merge sets `updated_at` as for `rule`.
- `aco withdraw` never takes `--via` or `--card-hash`: it decides nothing for the operator.
- `aco withdraw` never checks who runs it: aco cannot tell a head from another session, and the forge's edit history is the record.
- `aco serve`'s decision board never calls `aco withdraw`.
- `aco withdraw` reaches the same checkout-less refusal `specs/check.spec.md` owns (CHECK-10) before it resolves the forge or the item.

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
