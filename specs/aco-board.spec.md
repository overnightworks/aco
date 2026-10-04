# `aco-board serve`

`aco-board serve` (issues #617, #620) shows a repository's open
expectation lines on a loopback page and writes each decision through the
installed `aco` command line, never through aco's own modules. This file
owns the board's decision rules: which outcomes it writes, when it refuses
a decision, how writes are ordered and stopped, and the note it may carry.
It cites the read shape `specs/rulings.spec.md` owns (RUL-10) and the write
`specs/rule.spec.md` owns (RULE-01, RULE-03) rather than restating them.
The board's HTTP shapes, headers, and token rules are not specified here
yet. `<n>` is an item number, `<k>` an expectation line's 1-based index.

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

## Writing a decision

- [ ] [ABRD-01] Deciding a shown open card with outcome `yes`, `no`, or `later` runs `aco rule <n> --line <k>` with `--yes`, `--no`, or `--later` and `--json` (see E-ABRD-01).
- [ ] [ABRD-02] A card whose title, text, question, example, picture, or recommended outcome changed since it was shown is refused `Diese Zeile hat sich geändert, bitte neu laden`, no `aco rule` run (see E-ABRD-02).
- [ ] [ABRD-03] The board runs one `aco rule` at a time; a decision arriving meanwhile waits. Decisions on distinct lines are both stored; on the same line, the later one answers `already_ruled` (RULE-04).
- [ ] [ABRD-04] Stopping the board waits for an `aco rule` already running; a decision still waiting for its turn or arriving after stopping began is refused `board is shutting down`, no `aco rule` run.
- [ ] [ABRD-05] A note is at most `280` characters after trimming, holds no NUL, and is valid UTF-8; any other note refuses the decision before any `aco` call; a blank note is no note.

## Reading the lines

- [ ] [ABRD-06] Every page load reads `aco rulings --json` afresh and shows each line whose `ruling` is `null` as a card, in aco's own order; the board keeps no copy.
- [ ] [ABRD-07] A line whose `default` or `ruling` is neither `null` nor `yes`/`no`/`later`, or whose `ruled_on` is neither `null` nor an ISO date, shows `aco rulings --json is unreadable: <detail>` instead of cards.

## Never

- The board never writes a decision for a line it did not just read as open with the same shown fields: ABRD-02 compares before every write.
- The board never runs two `aco rule` commands at once, and never starts one after stopping began (ABRD-03, ABRD-04).
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
