# `aco handover`

`aco handover ITEM --from AGENT --reason TEXT [--agent AGENT] [--json]` makes the
acting session the holder of the live claim on an item that `AGENT` holds. A head
started by the operator's restart order takes over its dead predecessor's claim this
way, so it lands, releases and rescopes as the holder without an override and without
naming the predecessor as itself. The takeover is one claim transition plus one record
on the item. `--help` lists `--from`, `--reason`, `--agent` and `--json`, each with a
help line. This file owns the `HANDED OVER` line, `handover`'s own refusals and its
`reason` vocabulary; `specs/claim-record.spec.md` owns the claim (CLAIM-75 the acting
agent), `specs/body-block.spec.md` the `handover` table (BODY-114..BODY-117),
`specs/output.spec.md` the `--json` envelope itself (OUT-01) and
`specs/storage-pin.spec.md` the state-ref forge gate (PIN-04). `<label>` is the item as
its storage names it: `#<n>` under `storage = "github"`, the item id under
`storage = "state-ref"` (PIN-30). A claim on a lane has no item and no handover.

## Behavior table

| state \ trigger | `aco handover ITEM --from AGENT --reason TEXT` | `--json` |
|---|---|---|
| `AGENT` holds the item's claim | HANDOVER-01..HANDOVER-05, HANDOVER-15 | HANDOVER-12 |
| the takeover already stands | HANDOVER-10 | HANDOVER-12 |
| `AGENT` is not the holder, or this session already holds it | HANDOVER-06, HANDOVER-07 | HANDOVER-13 |
| the item has no live claim | HANDOVER-08 | HANDOVER-13 |
| `--reason` blank, over one line or too long | HANDOVER-09 | HANDOVER-13 |
| the claim write fails after the record | HANDOVER-11 | HANDOVER-13 |
| `--repo` given, `storage = "state-ref"` | HANDOVER-14 | HANDOVER-13 |

- [ ] [HANDOVER-01] `aco handover ITEM --from AGENT --reason TEXT` makes the acting session, by CLAIM-75, the holder of the item's live claim, prints `HANDED OVER <label>: <from> -> <to>`, exit `0` (see E-HANDOVER-01).
- [ ] [HANDOVER-02] Only the holder changes: the claim's role, id, branch, scope, resource and opened commit stay, and the claim is one state-ref commit away from the one before.
- [ ] [HANDOVER-03] That commit carries the trailers `intent: handover`, then `from: <agent>`, `to: <agent>` and `reason: <text>`, so the state ref's history keeps every takeover.
- [ ] [HANDOVER-04] The item's `aco` block gains `handover = { from, to, reason, on }`, `on` today's UTC date, written before the claim moves and replacing an earlier one (see E-HANDOVER-01).
- [ ] [HANDOVER-05] The new holder then lands, releases and rescopes the claim with no override and no `--agent` of the predecessor; the predecessor's next write refuses as a non-holder (see E-HANDOVER-02).
- [ ] [HANDOVER-15] The claim's stored runs (LANREC-52) stay with the claim: the new holder begins and adds runs, and the previous holder's add refuses as a non-holder's (LANREC-61).
- [ ] [HANDOVER-06] A `--from` that is not the holder refuses `<label> is held by '<holder>', not by '<from>'; pass the holder as --from`, exit `2`, before any write (see E-HANDOVER-03).
- [ ] [HANDOVER-07] A session that already holds the claim, with no recorded takeover of the same `--from` and `--reason`, refuses `this session already holds <label>`, exit `2`, before any write.
- [ ] [HANDOVER-08] An item with no live claim refuses `issue <label> has no active build claim` (REL-09), exit `2`, before any write (see E-HANDOVER-03).
- [ ] [HANDOVER-09] A `--reason` that is blank, spans more than one line or exceeds 512 characters refuses `reason must be one bounded non-empty line`, exit `2`, before any read of the item.
- [ ] [HANDOVER-10] A repeat of a standing takeover (the acting session holds the claim, the item records the same `--from` and `--reason`) prints `ALREADY HANDED OVER <label>: <from> -> <to>`, exit `0`, writing nothing.
- [ ] [HANDOVER-11] A claim write that fails after the record refuses `<label> records the handover, but the claim was not handed over: <detail>; run the same command again`, exit `2`; the same command finishes it.
- [ ] [HANDOVER-12] `--json` on a success prints the envelope with `reason: "handed_over"`, or `"already_handed_over"` for HANDOVER-10, then `"item": <n>, "from": "<agent>", "to": "<agent>"` (see E-HANDOVER-01).
- [ ] [HANDOVER-13] `--json` on a refusal prints the envelope with the table's `reason` and the refusal sentence as `message`, exit `2`.
- [ ] [HANDOVER-14] Under `storage = "state-ref"` it resolves the state-ref forge like `rule` (PIN-30's label); `--repo` there refuses the same as PIN-04.

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| (the successes) | `handed_over`, `already_handed_over` |
| HANDOVER-06, HANDOVER-07, HANDOVER-08 | `precondition_failed` |
| a missing item, a pull request or a malformed body, as `rule` | `invalid_item` |
| HANDOVER-09, HANDOVER-14, the parser's own refusals | `invalid_usage` |
| HANDOVER-11, a forge failure | `unavailable` |

## Never

- `aco handover` never checks that the predecessor is gone: aco cannot tell a live session from a dead one, so `--reason` carries the authority, normally the operator's restart order quoted in the successor's first message, and the record on the item is the audit.
- A predecessor that is still alive finds its next `land`, `release` or `rescope` refused as a non-holder (HANDOVER-05); aco takes nothing from it by force.
- `aco handover` never makes the acting session claim another agent's identity: `--agent` names the acting session, never the predecessor, and the predecessor's name appears only as `--from`.
- `aco handover` never changes a claim's role, scope, branch or id, and never moves a claim between items.
- `aco handover` never takes a lane claim: it names an item.
- `aco handover` never keeps an earlier handover in the item: the block holds the latest, and the state ref's history holds every one (HANDOVER-03).

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local bare
repository with `main` at one commit, a git identity and `origin/HEAD`; the acting
session's `ACO_AGENT` is `Ada`, the predecessor is `Claude af547fd1`, and `<today>` is
the runner's own UTC date.

### E-HANDOVER-01 — a successor takes the claim over, text and `--json`

Setup: bare-remote, bootstrapped, issue `#42` open with a valid `aco` block and a live claim held by `Claude af547fd1`, role `builder`

```console
$ aco handover 42 --from 'Claude af547fd1' --reason 'restart order of the operator'
HANDED OVER #42: Claude af547fd1 -> Ada
exit 0
$ aco handover 42 --from 'Claude af547fd1' --reason 'restart order of the operator' --json
{"ok": true, "reason": "already_handed_over", "item": 42, "from": "Claude af547fd1", "to": "Ada"}
exit 0
```

The claim on `#42` is held by `Ada` as `builder`, with its branch and scope as before, and
the issue body's block ends with
`handover = { from = "Claude af547fd1", to = "Ada", reason = "restart order of the operator", on = <today> }`.

### E-HANDOVER-02 — the new holder lands without an override

Setup: E-HANDOVER-01's, pull request `#57` open, mergeable, every check green, its head branch the claim's branch

```console
$ aco land 57 --head <sha>
2> ERROR: only the original claimant may release; take the claim over with `aco handover 42 --from 'Claude af547fd1' --reason <text>`, or use an explicit coordinator override (holder='Claude af547fd1 (builder)', this session='Ada (builder)')
exit 2
$ aco handover 42 --from 'Claude af547fd1' --reason 'restart order of the operator'
HANDED OVER #42: Claude af547fd1 -> Ada
exit 0
$ aco land 57 --head <sha>
RELEASED issue #42: <claim-id>
freed: none
next: none
merged: <sha>
exit 0
```

The first `land` changed nothing; the second released the claim.

### E-HANDOVER-03 — a wrong holder and an unclaimed item refuse before any write

Setup: E-HANDOVER-01's, and issue `#43` open with no claim

```console
$ aco handover 42 --from 'Someone Else' --reason 'restart order of the operator'
2> ERROR: #42 is held by 'Claude af547fd1', not by 'Someone Else'; pass the holder as --from
exit 2
$ aco handover 43 --from 'Claude af547fd1' --reason 'restart order of the operator'
2> ERROR: issue #43 has no active build claim
exit 2
```

The state ref's tip and both issue bodies are unchanged after each refusal.

### E-HANDOVER-04 — a repeat after a failed claim write finishes the takeover

Setup: E-HANDOVER-01's, the first call's claim write failing after the record was written

```console
$ aco handover 42 --from 'Claude af547fd1' --reason 'restart order of the operator'
2> ERROR: #42 records the handover, but the claim was not handed over: <detail>; run the same command again
exit 2
$ aco handover 42 --from 'Claude af547fd1' --reason 'restart order of the operator'
HANDED OVER #42: Claude af547fd1 -> Ada
exit 0
```

The issue body is written once; the record keeps the first call's `on`.
