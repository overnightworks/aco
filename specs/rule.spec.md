# `aco rule`

`aco rule ITEM --line N --option X --via board|chat|default --card-hash HASH` or
`aco rule ITEM --line N --other TEXT --via board|chat --card-hash HASH`, or
`aco rule ITEM --line N --unclear [--note TEXT] --card-hash HASH`, moves one
proposed `[[expectation]]` line to ruled (or, with `--unclear`, sends an open
option line back to its head), transcribing the operator's own word (a head proposes by editing the body and withdraws with `aco withdraw`; this command decides); `--line` may repeat to rule several lines of one item in one body write, all or none. `--via` says how the
decision reached aco: `board` the operator clicked, `chat` a head transcribes
his word, `default` he left the card unanswered and its recommendation stands.
`--help` lists every flag here, `--unclear` included, each with a help line. A yes/no line cannot be ruled by this command. `--card-hash` names the card the decider saw (`specs/rulings.spec.md` RUL-14). This CLI invocation is the
one write path for a ruling (`board --serve`'s own
in-process `POST /rule` form is retired; `aco serve`'s decision board shells out to
this exact command instead, `specs/serve.spec.md` ABRD-78). This
file owns the ruling's own refusals -- an already-ruled
line, an out-of-range one -- the `RULED` line, its own `reason` vocabulary,
and the target refusals: a missing item, a pull-request target and a
malformed body.
`specs/output.spec.md` owns the `--json`
envelope itself (OUT-nn: key order, `ok`, `message`); this file names only
`rule`'s own `reason` values. `specs/storage-pin.spec.md`
owns the state-ref forge gate (PIN-04) `rule` shares with `brief`; this file cites it rather than restating it. `<n>` is the item's
own number, a printed `#<n>` its `storage = "github"` form and the item id
under `storage = "state-ref"` (PIN-30); `<k>` the 1-based line index `--line` names, the same index
`rulings` prints. `<m>` in a success line counts the open lines left, never a
withdrawn one.

## Behavior table

| state \ trigger | `aco rule ITEM --line N OUTCOME` | `--json` | `--note TEXT` |
|---|---|---|---|
| a still-open option line | RULE-01 | RULE-02 | — |
| a still-open option line with card fields | RULE-12 | RULE-12 | — |
| that line already ruled | RULE-04 | RULE-09 | — |
| `N` out of range | RULE-05 | RULE-09 | — |
| a still-open option line, `--option` | RULE-14 | RULE-14 | RULE-15 |
| a still-open option line, `--other` | RULE-20 | RULE-20 | RULE-15 |
| a still-open option line, `--unclear` | RULE-22, RULE-23 | RULE-22 | RULE-23 |
| that line already with its head, `--unclear` | RULE-24 | RULE-09 | — |
| a line with its head, `--option` or `--other` | RULE-25 | RULE-25 | — |
| a line with its head, `--via default` | RULE-27 | RULE-09 | — |
| `--note` blank beside `--unclear` | RULE-26 | RULE-09 | — |
| `--other` blank | RULE-21 | RULE-09 | — |
| a flag combination of `--option`, `--other`, `--unclear` the list under RULE-15 refuses | RULE-15 | RULE-09 | — |
| several still-open option lines, `--option` or `--other` | RULE-29, RULE-30, RULE-31 | RULE-32 | RULE-15 |
| several still-open option lines, `--unclear` | RULE-29, RULE-36, RULE-31 | RULE-32 | RULE-23, RULE-36 |
| one of several named lines refused | RULE-29 | RULE-09 | — |
| a line named twice | RULE-33 | RULE-09 | — |
| a misplaced `--option` or `--card-hash`, one `--line` included | RULE-34 | RULE-09 | — |
| a named line without its own `--option` or `--card-hash` | RULE-15 | RULE-09 | — |
| `--other`, `--note` or `--via` given twice | RULE-35 | RULE-09 | — |
| line `N` is a yes/no line, `--option`, `--other` or `--unclear` | RULE-16 | RULE-09 | — |
| its card changed since it was shown | RULE-17 | RULE-09 | — |
| line `N` was withdrawn by its head | RULE-37 | RULE-09 | — |
| `--option` names a letter not on the card | RULE-18 | RULE-09 | — |
| `--via default` names another letter than the recommended one | RULE-19 | RULE-09 | — |
| item does not exist | RULE-07 | RULE-09 | — |
| item is a pull request | RULE-08 | RULE-09 | — |
| item body malformed | RULE-28 | RULE-09 | — |
| `--repo` given, `storage = "state-ref"` | RULE-10 | RULE-09 | — |
| the body write itself fails | RULE-11 | RULE-11 | — |

## Ruling a line

- [ ] [RULE-01] A still-open option line makes `aco rule ITEM --line N` with `--option` or `--other` print `RULED #<n> line <k> <ruling>; <m> line(s) still open` on stdout, exit `0` (see E-RULE-01).
- [ ] [RULE-02] `--json` on the same call prints `specs/output.spec.md`'s envelope with `reason: "ruled"`, then `"item": <n>, "index": <k>, "ruling": "<ruling>", "ruled_on": "<date>", "open": <m>`.
- RULE-03 (retired 27.10.2026): the note on a yes/no ruling went with the yes/no outcome flags; `--note` now only goes with `--unclear` (RULE-23).
- [ ] [RULE-12] A ruling retains the card's `question`, `problem`, `picture`, `caption` unchanged, invents none, and adds only RULE-14's keys, plus `other` for `--other` (E-RULE-08).
- [ ] [RULE-14] `--option X` on an open option line prints RULE-01/RULE-02 with `X` as `<ruling>`; the line gains `ruling`, today's UTC `ruled_on`, `card_hash` and `via`, no other key changes (see E-RULE-10).
- [ ] [RULE-22] `--unclear` on an open option line prints `RETURNED #<n> line <k> to its head; <m> line(s) still open`, exit `0`; `--json` is `reason: "returned"` with `"item"`, `"index"`, `"returned_on"`, `"open"`.
- [ ] [RULE-23] `--unclear` adds today's UTC `returned_on` and, with `--note TEXT`, `returned_note` TEXT verbatim; no other key changes and the line stays open (see E-RULE-12).
- [ ] [RULE-25] `--option` or `--other` on a line with its head rules it as RULE-14 or RULE-20 and drops `returned_on` and `returned_note` (see E-RULE-12).
- [ ] [RULE-20] `--other TEXT` on an open option line prints RULE-01/RULE-02 with `other` as `<ruling>`; the line gains RULE-14's four keys with `ruling = "other"`, then `other`, TEXT verbatim (see E-RULE-11).
- [ ] [RULE-29] `--line` may repeat: each named line is checked in the order written by its own refusals, and all are written in one body write with one UTC date, or none is (see E-RULE-13).
- [ ] [RULE-30] With several `--line`, each `--option` and `--card-hash` belongs to the `--line` written just before it; with one `--line` they may stand anywhere (see E-RULE-13).
- [ ] [RULE-31] Several lines print, in the order written, `RULED #<n> lines <k> <ruling>, …; <m> line(s) still open` or `RETURNED #<n> lines <k>, … to its head; <m> line(s) still open`, exit `0` (see E-RULE-13).
- [ ] [RULE-32] Their `--json` carries `"lines": [{"index", "ruling"}, …]` in place of RULE-02's `index` and `ruling`, or `"lines": [{"index"}, …]` in place of RULE-22's `index` (see E-RULE-14).
- [ ] [RULE-36] `--via`, `--other` and `--note` are given once and apply to every named line; so does `--unclear` (see E-RULE-14).

## Refusals this command owns

- [ ] [RULE-04] `--line N` naming an already-ruled entry refuses `line <k> is already ruled; a changed ruling is a new line`, exit `2`, before any write (see E-RULE-03).
- [ ] [RULE-05] `--line N` outside the item's own expectation lines refuses `line <k> out of range: this item has <m> expectation line(s)`, exit `2`, before any write (see E-RULE-04); `<m>` counts withdrawn lines.
- RULE-06 (retired 27.10.2026): the refusal for a forge that cannot write the item body went with the forge capability table, which no adapter ever answered `UNSUPPORTED` for the body write (audit #331 finding 17).
- [ ] [RULE-07] An item no reference resolves refuses `#<n> does not exist`, exit `2`, before any write.
- [ ] [RULE-08] An item that is a pull request refuses `#<n> is a pull request, not an issue; rule needs an issue`, exit `2`, before any write.
- RULE-13 (retired 27.10.2026): the refusal of a yes/no outcome on an option line went with the yes/no outcome flags, which now fail as unrecognized arguments (exit `2`).
- [ ] [RULE-15] A flag combination below refuses its sentence, exit `2`, before any forge call, after RULE-33 and RULE-34 (see E-RULE-10, E-RULE-13):
  - with several `--line` and `--option` given, a named line without its own `--option` after it: `line <k> needs its own --option after it`
  - with several `--line`, a named line without its own `--card-hash` after it: `line <k> needs its own --card-hash after it`; the two count bullets are judged line by line in written order, `--option` before `--card-hash`, so line 2 without a hash refuses before line 3 without an option
  - `--option` without `--via` or `--card-hash`: `--option needs --via and --card-hash`
  - `--other` without `--via` or `--card-hash`: `--other needs --via and --card-hash`
  - `--note` with `--option`: `--note does not go with --option; keep the operator's word in the item's journal`
  - `--note` with `--other`: `--note does not go with --other; its text is the answer`
  - `--via default` with `--other`: `--via default keeps only the recommended option, not --other`
  - `--unclear` without `--card-hash`: `--unclear needs --card-hash`
  - `--via` with `--unclear`: `--via does not go with --unclear; nothing is decided`
- [ ] [RULE-16] `--option`, `--other` or `--unclear` naming a yes/no line refuses `line <k> is a yes/no line; <flag> rules only an option line`, `returns` for `--unclear`, exit `2`, after RULE-05, before RULE-04.
- [ ] [RULE-17] A `--card-hash` other than the card's current hash refuses `line <k> changed since its card was shown; show it again and rule what it shows now`, exit `2`, before any write, after RULE-04.
- [ ] [RULE-18] A letter not on the card refuses `line <k> has no option <X>; its options are <L>`, exit `2`, before any write, after RULE-17 (see E-RULE-10).
- [ ] [RULE-19] `--via default` with a letter other than the card's `recommended` refuses `--via default keeps only the recommended option <R>, not <X>`, exit `2`, before any write, after RULE-18.
- [ ] [RULE-21] A blank or all-whitespace `--other` refuses `--other needs a non-empty answer`, exit `2`, before any forge call, after RULE-15 (see E-RULE-11).
- [ ] [RULE-24] `--unclear` on a line already with its head refuses `line <k> is already with its head; it comes back once revised`, exit `2`, before any write, after RULE-04, before RULE-17.
- [ ] [RULE-26] A blank or all-whitespace `--note` beside `--unclear` refuses `a blank --note says nothing; leave it out`, exit `2`, before any forge call, after RULE-15 (see E-RULE-12).
- [ ] [RULE-27] `--via default` on a line with its head refuses `line <k> was answered Unclear; --via default records no answer`, exit `2`, before any write, after RULE-04, before RULE-17.
- [ ] [RULE-28] A MALFORMED item body refuses `#<n> <body defect sentence>; rule needs a valid aco block`, exit `2`, before any write; PIN-14/PIN-15's sentence replaces it under `state-ref` (see E-OUT-02).
- [ ] [RULE-09] `--json` on a refusal (RULE-04/05/07/08, 10, 15..19, 21, 24, 26..28, 33..35, 37) prints the envelope with the table's `reason` and the sentence as `message`, exit `2` (see E-RULE-05).
- [ ] [RULE-10] Under `storage = "state-ref"`, `aco rule` resolves the state-ref forge like `brief`; `--repo` there refuses the same as PIN-04 (see E-RULE-06).
- [ ] [RULE-33] A `--line` naming a line an earlier `--line` named refuses `line <k> is named twice`, exit `2`, before any forge call, after RULE-35 (see E-RULE-13).
- [ ] [RULE-34] A misplaced `--option` or `--card-hash` refuses its sentence below, exit `2`, before any forge call, after RULE-35; it and RULE-33 judge the flags in the order written (see E-RULE-13):
  - with several `--line`, one written before the first `--line`: `<flag> before the first --line belongs to no line`
  - a second one for the same line, with one `--line` too: `line <k> has a second <flag>`; `--line 2 --option A --option B` refuses `line 2 has a second --option`
- [ ] [RULE-35] A second `--other`, `--note` or `--via` refuses `<flag> is given twice; give it once`, exit `2`, with one `--line` too, before any forge call and any other refusal of this file (see E-RULE-13).
- [ ] [RULE-37] `--option`, `--other` or `--unclear` naming a withdrawn line refuses `line <k> was withdrawn by its head`, exit `2`, before any write, after RULE-05, before RULE-16 (see E-RULE-15).
- [ ] [RULE-11] A forge failure ruling the line -- the body write itself included -- refuses `ERROR: <sentence>`, exit `2`, `--json` `reason: "unavailable"` (see E-RULE-07).

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| RULE-04 (already ruled) | `already_ruled` |
| RULE-05 (out of range) | `line_out_of_range` |
| RULE-07 (missing item), RULE-08 (pull-request target), RULE-28 (malformed body) | `invalid_item` |
| RULE-10 (`--repo` under `storage = state-ref`, cites PIN-04), RULE-15 (a flag combination), RULE-16 (a yes/no line), RULE-21 (a blank answer), RULE-26 (a blank note), RULE-18 (a letter not on the card), RULE-19 (not the recommended letter), RULE-33 (a line named twice), RULE-34 (a misplaced `--option` or `--card-hash`), RULE-35 (a flag given twice) | `invalid_usage` |
| RULE-17 (the card changed), RULE-37 (the line was withdrawn) | `card_changed` |
| RULE-24 (already with its head), RULE-27 (`--via default` on such a line) | `with_head` |
| RULE-11 (the write itself fails) | `unavailable` |

## Never

- `aco rule` never accepts two kinds of outcome, or none: `--option`/`--other`/`--unclear` are one mutually exclusive, required group, and `--option`, `--other`, `--unclear`, `--via` and `--card-hash` appear in `--help` with a help line each.
- `aco rule --unclear` never stores `via` or `card_hash`: it decides nothing.
- `aco rule` never checks who typed `--via`: it records what the writer was told. By operator ruling it is a tripwire for cooperative agents; an agent of the operator's own user that types `--via board` is not stopped, and the forge's edit history is the record after the fact.
- `aco rule` never changes a ruled line's own `ruling`: RULE-04 refuses before any write reaches it.
- `aco rule` never rewrites a byte outside the ruled entries: the body's surrounding bytes stay exactly as written.
- `aco rule` reaches the same checkout-less refusal `specs/check.spec.md` owns (CHECK-10) before it ever resolves the forge or the item.
- `aco serve`'s own decision board (`specs/serve.spec.md` ABRD-78) is transport only: it shells out to this exact command, never a second write path of its own, so a line already ruled through it refuses the same RULE-04 sentence a direct `aco rule` would.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local
bare repository with `main` at one commit, a git identity, `origin/HEAD`,
and `ACO_AGENT` set to `Ada`; `<item-id>` is the state-ref id a session
itself minted, `<n>` that same item's own bare number, `<ruled-on>` the
runner's own today's date. Writing to a GitHub-pinned item instead needs a
fixed, deterministic fake `gh` (`specs/landing-grammar.spec.md`'s own
shape); these sessions use `storage = "state-ref"` instead, needing
neither.

### E-RULE-01 — ruling a still-open option line, text and `--json`

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with two open option lines, both recommending `A`; `<hash>` and `<hash-2>` are their `card_hash` values

```console
$ aco rule <item-id> --line 1 --option A --via chat --card-hash <hash>
RULED <item-id> line 1 A; 1 line(s) still open
exit 0
$ aco rule <item-id> --line 2 --other "Nur am Desktop." --via chat --card-hash <hash-2> --json
{"ok": true, "reason": "ruled", "item": <n>, "index": 2, "ruling": "other", "ruled_on": "<ruled-on>", "open": 0}
exit 0
```

### E-RULE-03 — an already-ruled line refuses before any write

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one already-ruled option line, `--line 1`

```console
$ aco rule <item-id> --line 1 --option A --via chat --card-hash <hash>
2> ERROR: line 1 is already ruled; a changed ruling is a new line
exit 2
```

### E-RULE-04 — an out-of-range line refuses before any write

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one open option line

```console
$ aco rule <item-id> --line 2 --option A --via chat --card-hash <hash>
2> ERROR: line 2 out of range: this item has 1 expectation line(s)
exit 2
```

### E-RULE-05 — a refusal's own `--json` envelope

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one already-ruled option line, `--line 1`

```console
$ aco rule <item-id> --line 1 --option A --via chat --card-hash <hash> --json
2> ERROR: line 1 is already ruled; a changed ruling is a new line
{"ok": false, "reason": "already_ruled", "message": "line 1 is already ruled; a changed ruling is a new line"}
exit 2
```

### E-RULE-06 — `--repo` under `storage = "state-ref"` refuses `invalid_usage`

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked

```console
$ aco rule <item-id> --line 1 --option A --via chat --card-hash <hash> --repo acme/items --json
2> ERROR: --repo is meaningless under storage = state-ref
{"ok": false, "reason": "invalid_usage", "message": "--repo is meaningless under storage = state-ref"}
exit 2
```

### E-RULE-07 — the body write itself fails

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one open option line, the forge failing the body write with `<detail>`

```console
$ aco rule <item-id> --line 1 --option A --via chat --card-hash <hash> --json
2> ERROR: <detail>
{"ok": false, "reason": "unavailable", "message": "<detail>"}
exit 2
```

### E-RULE-08 — card fields survive a ruling

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one open option line carrying `question`, `problem`, `picture` and `caption`

```console
$ aco rule <item-id> --line 1 --option A --via chat --card-hash <hash>
RULED <item-id> line 1 A; 0 line(s) still open
exit 0
```

The stored line retains `text`, `question`, `problem`, `picture` and `caption`
exactly; `ruling` is `A` and `ruled_on` is today's UTC date.

### E-RULE-10 — deciding an option line

Setup: bare-remote, fake `gh`, issue `#7` open, its line 1 a ruled yes/no line and its line 2 the open option line of `specs/body-block.spec.md` E-BODY-10, recommending `A`; `<hash>` is its `card_hash`, `sha256:f7f1db4c507733e34c58d64de61fd482ad3d308db7ce3bf14bc503179c26519d`, and `<stale>` any other

```console
$ aco rule 7 --line 2 --option A --via chat
2> ERROR: --option needs --via and --card-hash
exit 2
$ aco rule 7 --line 2 --option A --card-hash <hash>
2> ERROR: --option needs --via and --card-hash
exit 2
$ aco rule 7 --line 2 --option A --via chat --card-hash <hash> --note "Ja."
2> ERROR: --note does not go with --option; keep the operator's word in the item's journal
exit 2
$ aco rule 7 --line 1 --option A --via chat --card-hash <hash>
2> ERROR: line 1 is a yes/no line; --option rules only an option line
exit 2
$ aco rule 7 --line 2 --option A --via board --card-hash <stale> --json
2> ERROR: line 2 changed since its card was shown; show it again and rule what it shows now
{"ok": false, "reason": "card_changed", "message": "line 2 changed since its card was shown; show it again and rule what it shows now"}
exit 2
$ aco rule 7 --line 2 --option C --via chat --card-hash <hash>
2> ERROR: line 2 has no option C; its options are A, B
exit 2
$ aco rule 7 --line 2 --option B --via default --card-hash <hash>
2> ERROR: --via default keeps only the recommended option A, not B
exit 2
$ aco rule 7 --line 2 --option A --via chat --card-hash <hash>
RULED #7 line 2 A; 0 line(s) still open
exit 0
```

The body is unchanged after each refusal. After the last call line 2 carries
`ruling = "A"`, `ruled_on` today's UTC date, `card_hash = "<hash>"` and
`via = "chat"`, in that order after `text`; `aco check 7` prints `body ok`.

### E-RULE-11 — deciding an option line with the operator's own answer

Setup: E-RULE-10's setup; `<hash>` and `<stale>` as there

```console
$ aco rule 7 --line 2 --other "Nur am Desktop." --via chat
2> ERROR: --other needs --via and --card-hash
exit 2
$ aco rule 7 --line 2 --other "Nur am Desktop." --via chat --card-hash <hash> --note "Ja."
2> ERROR: --note does not go with --other; its text is the answer
exit 2
$ aco rule 7 --line 2 --other "Nur am Desktop." --via default --card-hash <hash>
2> ERROR: --via default keeps only the recommended option, not --other
exit 2
$ aco rule 7 --line 2 --other "  " --via chat --card-hash <hash>
2> ERROR: --other needs a non-empty answer
exit 2
$ aco rule 7 --line 1 --other "Nur am Desktop." --via chat --card-hash <hash>
2> ERROR: line 1 is a yes/no line; --other rules only an option line
exit 2
$ aco rule 7 --line 2 --other "Nur am Desktop." --via board --card-hash <stale> --json
2> ERROR: line 2 changed since its card was shown; show it again and rule what it shows now
{"ok": false, "reason": "card_changed", "message": "line 2 changed since its card was shown; show it again and rule what it shows now"}
exit 2
$ aco rule 7 --line 2 --other "Nur am Desktop." --via chat --card-hash <hash>
RULED #7 line 2 other; 0 line(s) still open
exit 0
$ aco rule 7 --line 2 --option A --via chat --card-hash <hash>
2> ERROR: line 2 is already ruled; a changed ruling is a new line
exit 2
```

The body is unchanged after each refusal. After the success line 2 carries
`ruling = "other"`, `ruled_on` today's UTC date, `card_hash = "<hash>"`,
`via = "chat"` and `other = "Nur am Desktop."`, in that order after `text`;
`aco check 7` prints `body ok`.

### E-RULE-12 — sending an option line back to its head

Setup: E-RULE-10's setup, and `<today>` the runner's own today's date; `<hash>` and `<stale>` as there

```console
$ aco rule 7 --line 2 --unclear
2> ERROR: --unclear needs --card-hash
exit 2
$ aco rule 7 --line 2 --unclear --card-hash <hash> --via chat
2> ERROR: --via does not go with --unclear; nothing is decided
exit 2
$ aco rule 7 --line 2 --unclear --card-hash <hash> --note "  "
2> ERROR: a blank --note says nothing; leave it out
exit 2
$ aco rule 7 --line 1 --unclear --card-hash <hash>
2> ERROR: line 1 is a yes/no line; --unclear returns only an option line
exit 2
$ aco rule 7 --line 2 --unclear --card-hash <stale> --json
2> ERROR: line 2 changed since its card was shown; show it again and rule what it shows now
{"ok": false, "reason": "card_changed", "message": "line 2 changed since its card was shown; show it again and rule what it shows now"}
exit 2
$ aco rule 7 --line 2 --unclear --note "Was kostet B?" --card-hash <hash>
RETURNED #7 line 2 to its head; 1 line(s) still open
exit 0
$ aco rule 7 --line 2 --unclear --card-hash <hash>
2> ERROR: line 2 is already with its head; it comes back once revised
exit 2
$ aco rule 7 --line 2 --option A --via default --card-hash <hash>
2> ERROR: line 2 was answered Unclear; --via default records no answer
exit 2
$ aco rule 7 --line 2 --option A --via chat --card-hash <hash>
RULED #7 line 2 A; 0 line(s) still open
exit 0
```

The body is unchanged after each refusal. After the success line 2 carries
`returned_on = <today>` and `returned_note = "Was kostet B?"` after `text`, and
`aco check 7` prints `body ok`; `aco rulings` reads it as with head
(`specs/rulings.spec.md` RUL-17, RUL-18). After the last call both keys are gone
and line 2 carries RULE-14's four keys.

### E-RULE-13 — ruling several lines in one write

Setup: bare-remote, fake `gh`, issue `#7` open, its line 1 a ruled yes/no line and its lines 2 and 3 open option lines like E-RULE-10's line 2, both recommending `A`, line 3's question changed so its card hash differs; `<hash-2>` and `<hash-3>` are their `card_hash` values as `aco rulings --json` prints them, and `<stale>` any other

```console
$ aco rule 7 --line 2 --card-hash <hash-2> --line 3 --option B --card-hash <hash-3> --option A --via chat
2> ERROR: line 3 has a second --option
exit 2
$ aco rule 7 --option A --line 2 --card-hash <hash-2> --line 3 --option B --card-hash <hash-3> --via chat
2> ERROR: --option before the first --line belongs to no line
exit 2
$ aco rule 7 --line 2 --option A --card-hash <hash-2> --line 2 --option B --card-hash <hash-2> --via chat
2> ERROR: line 2 is named twice
exit 2
$ aco rule 7 --line 2 --option A --card-hash <hash-2> --line 3 --card-hash <hash-3> --via chat
2> ERROR: line 3 needs its own --option after it
exit 2
$ aco rule 7 --line 2 --other "Nur am Desktop." --card-hash <hash-2> --line 3 --other "Nie." --card-hash <hash-3> --via chat
2> ERROR: --other is given twice; give it once
exit 2
$ aco rule 7 --line 2 --option A --via chat --option B --card-hash <hash-2>
2> ERROR: line 2 has a second --option
exit 2
$ aco rule 7 --line 2 --option A --card-hash <hash-2> --line 3 --option B --card-hash <stale> --via chat --json
2> ERROR: line 3 changed since its card was shown; show it again and rule what it shows now
{"ok": false, "reason": "card_changed", "message": "line 3 changed since its card was shown; show it again and rule what it shows now"}
exit 2
$ aco rule 7 --line 2 --option A --card-hash <hash-2> --line 3 --option B --card-hash <hash-3> --via chat
RULED #7 lines 2 A, 3 B; 0 line(s) still open
exit 0
```

The body is unchanged after each refusal, line 2 included. After the success lines 2 and 3 carry RULE-14's keys with their own letter and hash, one `ruled_on` and `via = "chat"`; `aco check 7` prints `body ok`.

### E-RULE-14 — several lines under one `--json` answer

Setup: E-RULE-13's, and `<today>` the runner's own today's date

```console
$ aco rule 7 --line 2 --card-hash <hash-2> --line 3 --card-hash <hash-3> --unclear --note "Was kostet B?" --json
{"ok": true, "reason": "returned", "item": 7, "lines": [{"index": 2}, {"index": 3}], "returned_on": "<today>", "open": 2}
exit 0
$ aco rule 7 --line 2 --card-hash <hash-2> --line 3 --card-hash <hash-3> --other "Nur am Desktop." --via chat --json
{"ok": true, "reason": "ruled", "item": 7, "lines": [{"index": 2, "ruling": "other"}, {"index": 3, "ruling": "other"}], "ruled_on": "<today>", "open": 0}
exit 0
```

Both lines carry the one text and lose `returned_on` and `returned_note` (RULE-25).

### E-RULE-15 — a withdrawn line refuses before any write

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with a ruled yes/no line 1, a withdrawn line 2 and an open option line 3

```console
$ aco rule <item-id> --line 2 --option A --via chat --card-hash <hash>
2> ERROR: line 2 was withdrawn by its head
exit 2
$ aco rule <item-id> --line 2 --unclear --card-hash <hash> --json
2> ERROR: line 2 was withdrawn by its head
{"ok": false, "reason": "card_changed", "message": "line 2 was withdrawn by its head"}
exit 2
$ aco rule <item-id> --line 3 --option A --via chat --card-hash <hash>
RULED <item-id> line 3 A; 0 line(s) still open
exit 0
```
