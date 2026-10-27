# `aco rule`

`aco rule ITEM --line N (--yes|--no|--later) [--note TEXT]`, or for an option
line `aco rule ITEM --line N --option X --via board|chat|default --card-hash HASH` or
`aco rule ITEM --line N --other TEXT --via board|chat --card-hash HASH`:
moves one proposed `[[expectation]]` line to ruled, transcribing the operator's own
word (`aco ask` proposes; this command decides). `--via` says how the
decision reached aco: `board` the operator clicked, `chat` a head transcribes
his word, `default` he left the card unanswered and its recommendation stands.
`--card-hash` names the card the decider saw (`specs/rulings.spec.md` RUL-14). This CLI invocation is the
one write path for a ruling (`board --serve`'s own
in-process `POST /rule` form is retired; `aco serve`'s decision board shells out to
this exact command instead, `specs/serve.spec.md` ABRD-01). This
file owns the ruling's own refusals -- an already-ruled
line, an out-of-range one -- the `RULED` line, its own `reason` vocabulary,
and every refusal `aco ask` shares only by substituting `command` ("rule"
where ask's own reads "ask"): a missing item, a pull-request target, a
forge that cannot write the body. `specs/output.spec.md` owns the `--json`
envelope itself (OUT-nn: key order, `ok`, `message`); this file names only
`rule`'s own `reason` values. `specs/ask.spec.md` owns the
malformed-body-target refusal the two commands share verbatim (ASK-05);
this file cites it rather than restating it. `specs/storage-pin.spec.md`
owns the state-ref forge gate (PIN-04) `rule` shares with `ask` and
`brief`; this file cites it rather than restating it. `<n>` is the item's
own number, a printed `#<n>` its `storage = "github"` form and the item id
under `storage = "state-ref"` (PIN-30); `<k>` the 1-based line index `--line` names, the same index
`aco ask`'s own `ASKED` line and `rulings` print.

## Behavior table

| state \ trigger | `aco rule ITEM --line N OUTCOME` | `--json` | `--note TEXT` |
|---|---|---|---|
| a still-open line | RULE-01 | RULE-02 | RULE-03 |
| a still-open line with optional card fields | RULE-12 | RULE-12 | RULE-12 |
| that line already ruled | RULE-04 | RULE-09 | — |
| `N` out of range | RULE-05 | RULE-09 | — |
| line `N` is an option line, open or ruled | RULE-13 | RULE-09 | — |
| a still-open option line, `--option` | RULE-14 | RULE-14 | RULE-15 |
| a still-open option line, `--other` | RULE-20 | RULE-20 | RULE-15 |
| `--other` blank | RULE-21 | RULE-09 | — |
| `--option` or `--other` without `--via` or `--card-hash`, or they without either | RULE-15 | RULE-09 | — |
| line `N` is a yes/no line, `--option` or `--other` | RULE-16 | RULE-09 | — |
| its card changed since it was shown | RULE-17 | RULE-09 | — |
| `--option` names a letter not on the card | RULE-18 | RULE-09 | — |
| `--via default` names another letter than the recommended one | RULE-19 | RULE-09 | — |
| this forge cannot write the body | RULE-06 | RULE-09 | — |
| item does not exist | RULE-07 | RULE-09 | — |
| item is a pull request | RULE-08 | RULE-09 | — |
| item body malformed | ASK-05 (cited) | RULE-09 | — |
| `--repo` given, `storage = "state-ref"` | RULE-10 | RULE-09 | — |
| the body write itself fails | RULE-11 | RULE-11 | — |

## Ruling a line

- [ ] [RULE-01] A still-open line makes `aco rule ITEM --line N` with `--yes`/`--no`/`--later` print `RULED #<n> line <k> <ruling>; <m> line(s) still open` on stdout, exit `0` (see E-RULE-01).
- [ ] [RULE-02] `--json` on the same call prints `specs/output.spec.md`'s envelope with `reason: "ruled"`, then `"item": <n>, "index": <k>, "ruling": "<ruling>", "ruled_on": "<date>", "open": <m>`.
- [ ] [RULE-03] `--note TEXT` appends ` Anmerkung: TEXT` to the ruled line's own `text`, never a separate field (see E-RULE-02).
- [ ] [RULE-12] Every outcome, with or without a note, retains present `question`, `example`, `picture` unchanged, invents none, and removes `default` for `ruling` and today's UTC `ruled_on` (E-RULE-08).
- [ ] [RULE-14] `--option X` on an open option line prints RULE-01/RULE-02 with `X` as `<ruling>`; the line gains `ruling`, today's UTC `ruled_on`, `card_hash` and `via`, no other key changes (see E-RULE-10).
- [ ] [RULE-20] `--other TEXT` on an open option line prints RULE-01/RULE-02 with `other` as `<ruling>`; the line gains RULE-14's four keys with `ruling = "other"`, then `other`, TEXT verbatim (see E-RULE-11).

## Refusals this command owns

`aco ask`'s equivalent of RULE-06/RULE-08 substitutes `ask` for `rule` in
the same sentence; RULE-07's sentence is identical for both commands.

- [ ] [RULE-04] `--line N` naming an already-ruled entry refuses `line <k> is already ruled; a changed ruling is a new line`, exit `2`, before any write (see E-RULE-03).
- [ ] [RULE-05] `--line N` outside the item's own expectation lines refuses `line <k> out of range: this item has <m> expectation line(s)`, exit `2`, before any write (see E-RULE-04).
- [ ] [RULE-06] A forge whose `update_item_body` capability is not `READ_WRITE` refuses `this forge cannot update_item_body; rule by hand`, exit `2`, before any write.
- [ ] [RULE-07] An item no reference resolves refuses `#<n> does not exist`, exit `2`, before any write.
- [ ] [RULE-08] An item that is a pull request refuses `#<n> is a pull request, not an issue; rule needs an issue`, exit `2`, before any write.
- [ ] [RULE-13] `--line N` naming an option line refuses `line <k> is an option line; --yes, --no and --later rule only a yes/no line`, exit `2`, before any write, after RULE-05, before RULE-04 (see E-RULE-09).
- [ ] [RULE-15] A flag combination below refuses its sentence, exit `2`, before any forge call (see E-RULE-10):
  - `--option` without `--via` or `--card-hash`: `--option needs --via and --card-hash`
  - `--other` without `--via` or `--card-hash`: `--other needs --via and --card-hash`
  - `--via` or `--card-hash` without `--option` or `--other`: `--via and --card-hash go only with --option or --other`
  - `--note` with `--option`: `--note does not go with --option; keep the operator's word in the item's journal`
  - `--note` with `--other`: `--note does not go with --other; its text is the answer`
  - `--via default` with `--other`: `--via default keeps only the recommended option, not --other`
- [ ] [RULE-16] `--option` or `--other` naming a yes/no line refuses `line <k> is a yes/no line; <flag> rules only an option line`, `<flag>` the one given, exit `2`, before any write, after RULE-05, before RULE-04.
- [ ] [RULE-17] A `--card-hash` other than the card's current hash refuses `line <k> changed since its card was shown; show it again and rule what it shows now`, exit `2`, before any write, after RULE-04.
- [ ] [RULE-18] A letter not on the card refuses `line <k> has no option <X>; its options are <L>`, exit `2`, before any write, after RULE-17 (see E-RULE-10).
- [ ] [RULE-19] `--via default` with a letter other than the card's `recommended` refuses `--via default keeps only the recommended option <R>, not <X>`, exit `2`, before any write, after RULE-18.
- [ ] [RULE-21] A blank or all-whitespace `--other` refuses `--other needs a non-empty answer`, exit `2`, before any forge call, after RULE-15 (see E-RULE-11).
- [ ] [RULE-09] `--json` on a dispatched refusal (RULE-04..08, RULE-10, RULE-13, RULE-15..19, RULE-21, ASK-05) prints the envelope with the table's `reason` and the sentence as `message`, exit `2` (see E-RULE-05).
- [ ] [RULE-10] Under `storage = "state-ref"`, `aco rule` resolves the state-ref forge like `aco ask`; `--repo` there refuses the same as PIN-04 (see E-RULE-06).
- [ ] [RULE-11] A forge failure ruling the line -- the body write itself included -- refuses `ERROR: <sentence>`, exit `2`, `--json` `reason: "unavailable"` (see E-RULE-07).

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| RULE-04 (already ruled) | `already_ruled` |
| RULE-05 (out of range) | `line_out_of_range` |
| RULE-07 (missing item), RULE-08 (pull-request target), ASK-05 (malformed body, cited) | `invalid_item` |
| RULE-10 (`--repo` under `storage = state-ref`, cites PIN-04), RULE-13 (an option line), RULE-15 (a flag combination), RULE-16 (a yes/no line), RULE-21 (a blank answer), RULE-18 (a letter not on the card), RULE-19 (not the recommended letter) | `invalid_usage` |
| RULE-17 (the card changed) | `card_changed` |
| RULE-06 (forge cannot write), RULE-11 (the write itself fails) | `unavailable` |

## Never

- `aco rule` never accepts two outcome flags, or none: `--yes`/`--no`/`--later`/`--option`/`--other` are one mutually exclusive, required group, and `--option` and `--other` stay out of `--help` and the usage line.
- `aco rule` never checks who typed `--via`: it records what the writer was told. By operator ruling it is a tripwire for cooperative agents; an agent of the operator's own user that types `--via board` is not stopped, and the forge's edit history is the record after the fact.
- `aco rule` never changes a ruled line's own `ruling`: RULE-04 refuses before any write reaches it.
- `aco rule` never rewrites a byte outside the ruled entry: the body's surrounding bytes stay exactly as written.
- `aco rule` reaches the same checkout-less refusal `specs/check.spec.md` owns (CHECK-10) before it ever resolves the forge or the item.
- `aco serve`'s own decision board (`specs/serve.spec.md` ABRD-01) is transport only: it shells out to this exact command, never a second write path of its own, so a line already ruled through it refuses the same RULE-04 sentence a direct `aco rule` would.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local
bare repository with `main` at one commit, a git identity, `origin/HEAD`,
and `ACO_AGENT` set to `Ada`; `<item-id>` is the state-ref id a session
itself minted, `<n>` that same item's own bare number, `<ruled-on>` the
runner's own today's date. Writing to a GitHub-pinned item instead needs a
fixed, deterministic fake `gh` (`specs/landing-grammar.spec.md`'s own
shape); these sessions use `storage = "state-ref"` instead, needing
neither.

### E-RULE-01 — ruling a still-open line, text and `--json`

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with two proposed lines (`aco ask <item-id> --text "Ship it?"`, `aco ask <item-id> --text "Ship it too?"`)

```console
$ aco rule <item-id> --line 1 --yes
RULED <item-id> line 1 yes; 1 line(s) still open
exit 0
$ aco rule <item-id> --line 2 --later --json
{"ok": true, "reason": "ruled", "item": <n>, "index": 2, "ruling": "later", "ruled_on": "<ruled-on>", "open": 0}
exit 0
```

### E-RULE-02 — a note appended to the ruled line

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one proposed line, text `Ship it?`

```console
$ aco rule <item-id> --line 1 --yes --note "Ja, sofort."
RULED <item-id> line 1 yes; 0 line(s) still open
exit 0
```

### E-RULE-03 — an already-ruled line refuses before any write

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one already-ruled line, `--line 1`

```console
$ aco rule <item-id> --line 1 --no
2> ERROR: line 1 is already ruled; a changed ruling is a new line
exit 2
```

### E-RULE-04 — an out-of-range line refuses before any write

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one proposed line

```console
$ aco rule <item-id> --line 2 --yes
2> ERROR: line 2 out of range: this item has 1 expectation line(s)
exit 2
```

### E-RULE-05 — a refusal's own `--json` envelope

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one already-ruled line, `--line 1`

```console
$ aco rule <item-id> --line 1 --no --json
2> ERROR: line 1 is already ruled; a changed ruling is a new line
{"ok": false, "reason": "already_ruled", "message": "line 1 is already ruled; a changed ruling is a new line"}
exit 2
```

### E-RULE-06 — `--repo` under `storage = "state-ref"` refuses `invalid_usage`

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked

```console
$ aco rule <item-id> --line 1 --yes --repo acme/items --json
2> ERROR: --repo is meaningless under storage = state-ref
{"ok": false, "reason": "invalid_usage", "message": "--repo is meaningless under storage = state-ref"}
exit 2
```

### E-RULE-07 — the body write itself fails

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one still-open line, the forge failing the body write with `<detail>`

```console
$ aco rule <item-id> --line 1 --yes --json
2> ERROR: <detail>
{"ok": false, "reason": "unavailable", "message": "<detail>"}
exit 2
```

### E-RULE-08 — card fields survive a ruling

Setup: bare-remote, bootstrapped, `storage = "state-ref"` tracked, `<item-id>` open with one proposed line containing `text`, `default`, `question`, `example`, and `picture`.

```console
$ aco rule <item-id> --line 1 --yes
RULED <item-id> line 1 yes; 0 line(s) still open
exit 0
```

The stored line retains `text`, `question`, `example`, and `picture` exactly;
`default` is absent, `ruling` is `yes`, and `ruled_on` is today's UTC date.
With `--note`, only `text` gains the RULE-03 suffix. Absent card fields stay absent.

### E-RULE-09 — an option line refuses a yes/no outcome before any write

Setup: bare-remote, fake `gh`, issue `#7` open, its line 1 a yes/no line and its line 2 the option line of `specs/body-block.spec.md` E-BODY-10, open or ruled

```console
$ aco rule 7 --line 2 --yes
2> ERROR: line 2 is an option line; --yes, --no and --later rule only a yes/no line
exit 2
$ aco rule 7 --line 2 --later --json
2> ERROR: line 2 is an option line; --yes, --no and --later rule only a yes/no line
{"ok": false, "reason": "invalid_usage", "message": "line 2 is an option line; --yes, --no and --later rule only a yes/no line"}
exit 2
$ aco rule 7 --line 3 --no
2> ERROR: line 3 out of range: this item has 2 expectation line(s)
exit 2
```

The body is unchanged after each call.

### E-RULE-10 — deciding an option line

Setup: bare-remote, fake `gh`, issue `#7` open, its line 1 an open yes/no line and its line 2 the open option line of `specs/body-block.spec.md` E-BODY-10, recommending `A`; `<hash>` is its `card_hash`, `sha256:f7f1db4c507733e34c58d64de61fd482ad3d308db7ce3bf14bc503179c26519d`, and `<stale>` any other

```console
$ aco rule 7 --line 2 --option A --via chat
2> ERROR: --option needs --via and --card-hash
exit 2
$ aco rule 7 --line 1 --yes --via chat
2> ERROR: --via and --card-hash go only with --option or --other
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
RULED #7 line 2 A; 1 line(s) still open
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
RULED #7 line 2 other; 1 line(s) still open
exit 0
$ aco rule 7 --line 2 --option A --via chat --card-hash <hash>
2> ERROR: line 2 is already ruled; a changed ruling is a new line
exit 2
```

The body is unchanged after each refusal. After the success line 2 carries
`ruling = "other"`, `ruled_on` today's UTC date, `card_hash = "<hash>"`,
`via = "chat"` and `other = "Nur am Desktop."`, in that order after `text`;
`aco check 7` prints `body ok`.
