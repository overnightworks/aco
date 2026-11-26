# `aco stats`

`aco stats A B [--json]` compares two groups of lanes by the records their releases left on `refs/aco/state` (`specs/lane-record.spec.md`), so a process experiment shows its effect. It is read-only:
it writes nothing, asks no forge and keeps no cache. It reads this checkout's repository alone, no other repository on the machine. Lanes released before the record existed have none, and nothing backfills the
append-only state ref. `specs/output.spec.md` owns the `--json` envelope (OUT-nn).

## Behavior table

| state \ trigger | text | `--json` |
|---|---|---|
| two valid groups | STATS-01, STATS-06..STATS-10 | STATS-01, STATS-11 |
| a range group | STATS-02 | STATS-02 |
| a tag group | STATS-03 | STATS-03 |
| a lane in both groups, in neither, or a group with no lane | STATS-04 | STATS-04 |
| a group that is neither a range nor a tag | STATS-05, STATS-16, STATS-17 | STATS-05, STATS-16, STATS-17 |
| a commit that records no lane | STATS-12 | STATS-12 |
| the global `--repo` | STATS-13 | STATS-13 |
| a state ref that cannot be read | STATS-14 | STATS-14 |
| a checkout without a usable configuration, or none | STATS-18, STATS-19 | STATS-18, STATS-19 |
| `--help` | STATS-20 | — |
| a stage's choices | STATS-10, STATS-27 | STATS-21 |
| a group with a control character | STATS-22 | STATS-22 |
| no state ref, or none with a record | STATS-15 | STATS-15 |
| a risk class and its stage figures | STATS-23..STATS-25 | STATS-26 |

## Reading the lanes

- STATS-01: The command walks the first-parent history of the checkout's `refs/aco/state` once; every commit that records a lane (STATS-12) is one lane. It changes no ref, file or claim (see E-STATS-01).
- STATS-02: `FROM..TO` takes two `YYYY-MM-DD` days and selects the lanes whose release commit is dated from FROM to TO, both days inclusive, by UTC calendar day (see E-STATS-01).
- STATS-03: `tag:NAME` selects the lanes whose record states `lane_experiment: NAME`; NAME is 1 to 40 lowercase letters, digits and `-` (see E-STATS-01).
- STATS-04: A lane in neither group is ignored; a lane both select counts in both; a group no lane selects prints `lanes 0` and every figure with `n 0` and `unknown 0` (see E-STATS-02).
- STATS-12: A commit records a lane when it states exactly one `lane_outcome` of `landed` or `abandoned`; every other commit, and a lane released before the record existed, is no lane.
- STATS-15: A repository whose state ref does not exist, or holds no recorded lane, prints both groups with `lanes 0`, exit `0` (see E-STATS-02).

## The figures

- STATS-06: Text prints group A, then group B; each starts `<A|B> <group>: lanes <n> (landed <n>, abandoned <n>)`, `<group>` as the argument selected it (see E-STATS-01).
- STATS-07: Each group then prints the lines `  <figure>: median <m>, n <n>, unknown <u>` for `wall_seconds`, `fix_rounds`, `blocking`, `files`, `added` and `deleted`, in that order (see E-STATS-01).
- STATS-08: `n` counts the lanes that state the figure, `unknown` those that do not; a missing, repeated or malformed line is unknown (LANREC-04), and `files`, `added`, `deleted` are known only together.
- STATS-09: `<m>` is the median of the known values, the mean of the middle two for an even `n` (so it can end in `.5`), `unknown` with none (see E-STATS-01).
- STATS-10: Each group then prints `  <stage>: <choice> <count>, ..., unknown <u>` for `build`, `fix`, `review`, `test`, `gate`, `land`; choices by count descending, ties by name (see E-STATS-01).
- STATS-23: Each group then prints a block per risk class its lanes state, by name, then `(none)` for lanes with no risk; a block starts `  risk <class>: lanes <n> (landed <n>, abandoned <n>)` (see E-STATS-06).
- STATS-24: Each block then has, for `review`, `gate`, `ci`, `test`: `    fix_rounds_<stage>: total <t>, n <n>, unknown <u>`, then `    misses_<stage>: ...`; `<t>` sums the known values, `unknown` if `n` is 0.
- STATS-25: A risk class none of a group's lanes states has no block, so an empty group has none (see E-STATS-02); `(none)` is for a lane with no valid `lane_risk` (LANREC-51), never a tag (LANREC-20).

## `--json`

- STATS-11: Success is `{"ok": true, "reason": "compared", "a": <group>, "b": <group>}`; a group has `group`, `lanes`, `outcomes`, `figures` (`median` `null` if unknown, `n`, `unknown`), `stages` and `risks`.
- STATS-26: `risks` lists the blocks as `{risk, lanes, outcomes, stages}`, `risk` `null` for `(none)`; `stages` maps a stage to `fix_rounds` and `misses`, each `{total, n, unknown}`, `total` `null` if unknown.
- STATS-27: A stage a lane states as `none` counts under `none` for that stage, `build` included, as `fix: none 1` does; `none` is no model and no count names one for it.

## Refusals

- STATS-05: A group that is neither form refuses `group <text> must be FROM..TO as YYYY-MM-DD days or tag:NAME`, exit `2`, `invalid_usage` (see E-STATS-03).
- STATS-16: A range with an impossible day refuses `group <text> holds an impossible day`, one that ends before it starts `group <text> ends before it starts`; exit `2`, `invalid_usage`.
- STATS-17: A tag that does not fit STATS-03 refuses `group <text> names no tag: a tag is 1 to 40 lowercase letters, digits or '-'`, exit `2`, `invalid_usage`.
- STATS-13: The global `--repo` refuses `aco stats reads this checkout's own state ref; --repo does not apply to it`, exit `2`; `--json` has `reason` `invalid_usage` (see E-STATS-04).
- STATS-14: A checkout that cannot read the state ref (no canonical remote, a failed fetch or `git log`) prints `ERROR: <sentence>` on stderr, exit `2`; `--json` has `reason` `unavailable` (see E-STATS-05).
- STATS-18: The shared configuration read refuses before any lane is read: no tracked `.aco/board.toml` with PIN-32's sentence, a malformed `production_paths` with PIN-55's or PIN-56's; exit `2`, `unavailable`.
- STATS-19: Run outside a git checkout, stats refuses with `<no-checkout sentence>` of `specs/check.spec.md`, which names the configuration it reads, never a body contract; exit `2`, `unavailable`.
- STATS-20: `aco stats --help` says that a day is a UTC calendar day and gives STATS-03's tag grammar.
- STATS-21: The order of a stage's `choices` in `--json` carries no meaning; only the text form is ordered (STATS-10).
- STATS-22: A refusal prints a group argument as Python's `repr` writes it (`'yesterday'`), so a newline in it prints escaped and the `ERROR:` line stays one line.

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| STATS-05, STATS-16, STATS-17 (a group) | `invalid_usage` |
| STATS-13 (`--repo`) | `invalid_usage` |
| STATS-14, STATS-18, STATS-19 (the state ref or the configuration cannot be read) | `unavailable` |

## Never

- `aco stats` never writes: no ref, file, claim, comment or trailer, and it asks no forge.
- It never guesses a figure: a lane that does not state one is counted `unknown`, never `0` (a stage total no lane states is `unknown`), and no figure is read from another source than the lane's own record.
- It never prints a cost or token figure: the record holds none (`specs/lane-record.spec.md`).
- It reads the `lane_*` lines of the commit messages itself, by key: they are underscore keys, which git's trailer tooling does not read (`specs/ref-store-cas.spec.md`, CAS-06).
- It never compares repositories: one run reads one checkout's state ref.

## Examples

`Setup: recorded` is a fresh work repository whose `origin` is a local bare repository with `main` at one commit, a git identity and a bootstrapped state ref. Its release commits record four lanes. Lane 1, dated
2026-11-02, landed: wall time 1800 s, 2 files, 40 lines added, 5 deleted, build `sonnet-5.5/high`, fix `none`, review `opus-5.5/medium`, land `haiku-5.5/low`, 1 fix round, 2 blocking findings, experiment `builder-sonnet`.
Lane 2, dated 2026-11-03 at 23:59:59 UTC, landed: 3000 s, 4 files, 100 added, 20 deleted, build `sonnet-5.5/high`, review `opus-5.5/medium`, 2 fix rounds, experiment `builder-sonnet`, no blocking line. Lane 3, dated
2026-11-09, landed: 1200 s, build `opus-5.5/high`, 0 fix rounds, 0 blocking findings, experiment `builder-opus`, no size lines. Lane 4, dated 2026-11-10, abandoned: 60 s.

### E-STATS-01 — a range against a tag

Setup: recorded

```console
$ aco stats 2026-11-01..2026-11-07 tag:builder-opus
A 2026-11-01..2026-11-07: lanes 2 (landed 2, abandoned 0)
  wall_seconds: median 2400, n 2, unknown 0
  fix_rounds: median 1.5, n 2, unknown 0
  blocking: median 2, n 1, unknown 1
  files: median 3, n 2, unknown 0
  added: median 70, n 2, unknown 0
  deleted: median 12.5, n 2, unknown 0
  build: sonnet-5.5/high 2, unknown 0
  fix: none 1, unknown 1
  review: opus-5.5/medium 2, unknown 0
  test: unknown 2
  gate: unknown 2
  land: haiku-5.5/low 1, unknown 1
  risk (none): lanes 2 (landed 2, abandoned 0)
    fix_rounds_review: total unknown, n 0, unknown 2
    misses_review: total unknown, n 0, unknown 2
    fix_rounds_gate: total unknown, n 0, unknown 2
    misses_gate: total unknown, n 0, unknown 2
    fix_rounds_ci: total unknown, n 0, unknown 2
    misses_ci: total unknown, n 0, unknown 2
    fix_rounds_test: total unknown, n 0, unknown 2
    misses_test: total unknown, n 0, unknown 2
B tag:builder-opus: lanes 1 (landed 1, abandoned 0)
  wall_seconds: median 1200, n 1, unknown 0
  fix_rounds: median 0, n 1, unknown 0
  blocking: median 0, n 1, unknown 0
  files: median unknown, n 0, unknown 1
  added: median unknown, n 0, unknown 1
  deleted: median unknown, n 0, unknown 1
  build: opus-5.5/high 1, unknown 0
  fix: unknown 1
  review: unknown 1
  test: unknown 1
  gate: unknown 1
  land: unknown 1
  risk (none): lanes 1 (landed 1, abandoned 0)
    fix_rounds_review: total unknown, n 0, unknown 1
    misses_review: total unknown, n 0, unknown 1
    fix_rounds_gate: total unknown, n 0, unknown 1
    misses_gate: total unknown, n 0, unknown 1
    fix_rounds_ci: total unknown, n 0, unknown 1
    misses_ci: total unknown, n 0, unknown 1
    fix_rounds_test: total unknown, n 0, unknown 1
    misses_test: total unknown, n 0, unknown 1
exit 0
$ aco stats 2026-11-01..2026-11-07 tag:builder-opus --json
{"ok": true, "reason": "compared", "a": {"group": "2026-11-01..2026-11-07", "lanes": 2, "outcomes": {"landed": 2, "abandoned": 0}, "figures": {"wall_seconds": {"median": 2400, "n": 2, "unknown": 0}, "fix_rounds": {"median": 1.5, "n": 2, "unknown": 0}, "blocking": {"median": 2, "n": 1, "unknown": 1}, "files": {"median": 3, "n": 2, "unknown": 0}, "added": {"median": 70, "n": 2, "unknown": 0}, "deleted": {"median": 12.5, "n": 2, "unknown": 0}}, "stages": {"build": {"choices": {"sonnet-5.5/high": 2}, "unknown": 0}, "fix": {"choices": {"none": 1}, "unknown": 1}, "review": {"choices": {"opus-5.5/medium": 2}, "unknown": 0}, "test": {"choices": {}, "unknown": 2}, "gate": {"choices": {}, "unknown": 2}, "land": {"choices": {"haiku-5.5/low": 1}, "unknown": 1}}, "risks": [{"risk": null, "lanes": 2, "outcomes": {"landed": 2, "abandoned": 0}, "stages": {"review": {"fix_rounds": {"total": null, "n": 0, "unknown": 2}, "misses": {"total": null, "n": 0, "unknown": 2}}, "gate": {"fix_rounds": {"total": null, "n": 0, "unknown": 2}, "misses": {"total": null, "n": 0, "unknown": 2}}, "ci": {"fix_rounds": {"total": null, "n": 0, "unknown": 2}, "misses": {"total": null, "n": 0, "unknown": 2}}, "test": {"fix_rounds": {"total": null, "n": 0, "unknown": 2}, "misses": {"total": null, "n": 0, "unknown": 2}}}}]}, "b": {"group": "tag:builder-opus", "lanes": 1, "outcomes": {"landed": 1, "abandoned": 0}, "figures": {"wall_seconds": {"median": 1200, "n": 1, "unknown": 0}, "fix_rounds": {"median": 0, "n": 1, "unknown": 0}, "blocking": {"median": 0, "n": 1, "unknown": 0}, "files": {"median": null, "n": 0, "unknown": 1}, "added": {"median": null, "n": 0, "unknown": 1}, "deleted": {"median": null, "n": 0, "unknown": 1}}, "stages": {"build": {"choices": {"opus-5.5/high": 1}, "unknown": 0}, "fix": {"choices": {}, "unknown": 1}, "review": {"choices": {}, "unknown": 1}, "test": {"choices": {}, "unknown": 1}, "gate": {"choices": {}, "unknown": 1}, "land": {"choices": {}, "unknown": 1}}, "risks": [{"risk": null, "lanes": 1, "outcomes": {"landed": 1, "abandoned": 0}, "stages": {"review": {"fix_rounds": {"total": null, "n": 0, "unknown": 1}, "misses": {"total": null, "n": 0, "unknown": 1}}, "gate": {"fix_rounds": {"total": null, "n": 0, "unknown": 1}, "misses": {"total": null, "n": 0, "unknown": 1}}, "ci": {"fix_rounds": {"total": null, "n": 0, "unknown": 1}, "misses": {"total": null, "n": 0, "unknown": 1}}, "test": {"fix_rounds": {"total": null, "n": 0, "unknown": 1}, "misses": {"total": null, "n": 0, "unknown": 1}}}}]}}
exit 0
```

### E-STATS-02 — a group no lane selects

Setup: recorded

```console
$ aco stats 2026-11-04..2026-11-08 tag:unused
A 2026-11-04..2026-11-08: lanes 0 (landed 0, abandoned 0)
  wall_seconds: median unknown, n 0, unknown 0
  fix_rounds: median unknown, n 0, unknown 0
  blocking: median unknown, n 0, unknown 0
  files: median unknown, n 0, unknown 0
  added: median unknown, n 0, unknown 0
  deleted: median unknown, n 0, unknown 0
  build: unknown 0
  fix: unknown 0
  review: unknown 0
  test: unknown 0
  gate: unknown 0
  land: unknown 0
B tag:unused: lanes 0 (landed 0, abandoned 0)
  wall_seconds: median unknown, n 0, unknown 0
  fix_rounds: median unknown, n 0, unknown 0
  blocking: median unknown, n 0, unknown 0
  files: median unknown, n 0, unknown 0
  added: median unknown, n 0, unknown 0
  deleted: median unknown, n 0, unknown 0
  build: unknown 0
  fix: unknown 0
  review: unknown 0
  test: unknown 0
  gate: unknown 0
  land: unknown 0
exit 0
```

### E-STATS-03 — a group that is neither

Setup: recorded

```console
$ aco stats yesterday tag:builder-opus --json
2> ERROR: group 'yesterday' must be FROM..TO as YYYY-MM-DD days or tag:NAME
{"ok": false, "reason": "invalid_usage", "message": "group 'yesterday' must be FROM..TO as YYYY-MM-DD days or tag:NAME"}
exit 2
```

### E-STATS-04 — `--repo`

Setup: recorded

```console
$ aco --repo acme/here stats 2026-11-01..2026-11-07 tag:builder-opus --json
2> ERROR: aco stats reads this checkout's own state ref; --repo does not apply to it
{"ok": false, "reason": "invalid_usage", "message": "aco stats reads this checkout's own state ref; --repo does not apply to it"}
exit 2
```

### E-STATS-05 — no canonical remote

Setup: recorded, `git remote remove origin`

```console
$ aco stats 2026-11-01..2026-11-07 tag:builder-opus
2> ERROR: cannot determine the trunk: canonical remote 'origin' is not configured
exit 2
```

### E-STATS-06 — risk blocks

Setup: recorded, three more release commits. Lane 5, dated 2026-12-01, landed, 100 s, risk `material`, fix rounds `2`, `0`, `1`, `0` and misses `0`, `0`, `1`, `0` for `review`, `gate`, `ci`, `test`. Lane 6, dated 2026-12-02, abandoned, 50 s, risk `normal`, fix rounds `1`, `0`, `0`, `0`, no misses lines. Lane 7, dated 2026-12-03, landed, 70 s, no risk line

```console
$ aco stats 2026-12-01..2026-12-31 tag:unused
A 2026-12-01..2026-12-31: lanes 3 (landed 2, abandoned 1)
  wall_seconds: median 70, n 3, unknown 0
  fix_rounds: median unknown, n 0, unknown 3
  blocking: median unknown, n 0, unknown 3
  files: median unknown, n 0, unknown 3
  added: median unknown, n 0, unknown 3
  deleted: median unknown, n 0, unknown 3
  build: unknown 3
  fix: unknown 3
  review: unknown 3
  test: unknown 3
  gate: unknown 3
  land: unknown 3
  risk material: lanes 1 (landed 1, abandoned 0)
    fix_rounds_review: total 2, n 1, unknown 0
    misses_review: total 0, n 1, unknown 0
    fix_rounds_gate: total 0, n 1, unknown 0
    misses_gate: total 0, n 1, unknown 0
    fix_rounds_ci: total 1, n 1, unknown 0
    misses_ci: total 1, n 1, unknown 0
    fix_rounds_test: total 0, n 1, unknown 0
    misses_test: total 0, n 1, unknown 0
  risk normal: lanes 1 (landed 0, abandoned 1)
    fix_rounds_review: total 1, n 1, unknown 0
    misses_review: total unknown, n 0, unknown 1
    fix_rounds_gate: total 0, n 1, unknown 0
    misses_gate: total unknown, n 0, unknown 1
    fix_rounds_ci: total 0, n 1, unknown 0
    misses_ci: total unknown, n 0, unknown 1
    fix_rounds_test: total 0, n 1, unknown 0
    misses_test: total unknown, n 0, unknown 1
  risk (none): lanes 1 (landed 1, abandoned 0)
    fix_rounds_review: total unknown, n 0, unknown 1
    misses_review: total unknown, n 0, unknown 1
    fix_rounds_gate: total unknown, n 0, unknown 1
    misses_gate: total unknown, n 0, unknown 1
    fix_rounds_ci: total unknown, n 0, unknown 1
    misses_ci: total unknown, n 0, unknown 1
    fix_rounds_test: total unknown, n 0, unknown 1
    misses_test: total unknown, n 0, unknown 1
B tag:unused: lanes 0 (landed 0, abandoned 0)
  wall_seconds: median unknown, n 0, unknown 0
  fix_rounds: median unknown, n 0, unknown 0
  blocking: median unknown, n 0, unknown 0
  files: median unknown, n 0, unknown 0
  added: median unknown, n 0, unknown 0
  deleted: median unknown, n 0, unknown 0
  build: unknown 0
  fix: unknown 0
  review: unknown 0
  test: unknown 0
  gate: unknown 0
  land: unknown 0
exit 0
```
