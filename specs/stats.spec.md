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
| no state ref, or none with a record | STATS-15 | STATS-15 |

## Reading the lanes

- [ ] [STATS-01] The command walks the first-parent history of the checkout's `refs/aco/state` once; every commit that records a lane (STATS-12) is one lane. It changes no ref, file or claim (see E-STATS-01).
- [ ] [STATS-02] `FROM..TO` takes two `YYYY-MM-DD` days and selects the lanes whose release commit is dated from FROM to TO, both days inclusive, by UTC calendar day (see E-STATS-01).
- [ ] [STATS-03] `tag:NAME` selects the lanes whose record states `lane_experiment: NAME`; NAME is 1 to 40 lowercase letters, digits and `-` (see E-STATS-01).
- [ ] [STATS-04] A lane in neither group is ignored; a lane both select counts in both; a group no lane selects prints `lanes 0` and every figure with `n 0` and `unknown 0` (see E-STATS-02).
- [ ] [STATS-12] A commit records a lane when it states exactly one `lane_outcome` of `landed` or `abandoned`; every other commit, and a lane released before the record existed, is no lane.
- [ ] [STATS-15] A repository whose state ref does not exist, or holds no recorded lane, prints both groups with `lanes 0`, exit `0` (see E-STATS-02).

## The figures

- [ ] [STATS-06] Text prints group A, then group B; each starts `<A|B> <group>: lanes <n> (landed <n>, abandoned <n>)`, `<group>` as the argument selected it (see E-STATS-01).
- [ ] [STATS-07] Each group then prints the lines `  <figure>: median <m>, n <n>, unknown <u>` for `wall_seconds`, `fix_rounds`, `blocking`, `files`, `added`, `deleted` and `cost`, in that order (see E-STATS-01).
- [ ] [STATS-08] `n` counts the lanes that state the figure, `unknown` those that do not; a missing, repeated or malformed line is unknown (LANREC-04), and `files`, `added`, `deleted` are known only together.
- [ ] [STATS-09] `<m>` is the median of the known values, the mean of the middle two for an even `n` (so it can end in `.5`), `unknown` with none. `cost` is always `median unknown, n 0` (see E-STATS-01).
- [ ] [STATS-10] Each group ends with `  <stage>: <choice> <count>, ..., unknown <u>` for `build`, `fix`, `review`, `test`, `gate`, `land`; choices by count descending, ties by name (see E-STATS-01).

## `--json`

- [ ] [STATS-11] Success is `{"ok": true, "reason": "compared", "a": <group>, "b": <group>}`; a group has `group`, `lanes`, `outcomes`, `figures` (`median` `null` if unknown, `n`, `unknown`) and `stages`.

## Refusals

- [ ] [STATS-05] A group that is neither form refuses `group '<text>' must be FROM..TO as YYYY-MM-DD days or tag:NAME`, exit `2`, `invalid_usage` (see E-STATS-03).
- [ ] [STATS-16] A range with an impossible day refuses `group '<text>' holds an impossible day`, one that ends before it starts `group '<text>' ends before it starts`; exit `2`, `invalid_usage`.
- [ ] [STATS-17] A tag that does not fit STATS-03 refuses `group '<text>' names no tag: a tag is 1 to 40 lowercase letters, digits or '-'`, exit `2`, `invalid_usage`.
- [ ] [STATS-13] The global `--repo` refuses `aco stats reads this checkout's own state ref; --repo does not apply to it`, exit `2`; `--json` has `reason` `invalid_usage` (see E-STATS-04).
- [ ] [STATS-14] A checkout that cannot read the state ref (no canonical remote, a failed fetch or `git log`) prints `ERROR: <sentence>` on stderr, exit `2`; `--json` has `reason` `unavailable` (see E-STATS-05).

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| STATS-05, STATS-16, STATS-17 (a group) | `invalid_usage` |
| STATS-13 (`--repo`) | `invalid_usage` |
| STATS-14 (the state ref cannot be read) | `unavailable` |

## Never

- `aco stats` never writes: no ref, file, claim, comment or trailer, and it asks no forge.
- It never guesses a figure: a lane that does not state one is counted `unknown`, never `0`, and no figure is read from another source than the lane's own record.
- It never prints a cost or token figure: the record holds none (`specs/lane-record.spec.md`), so `cost` is unknown for every lane.
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
  cost: median unknown, n 0, unknown 2
  build: sonnet-5.5/high 2, unknown 0
  fix: none 1, unknown 1
  review: opus-5.5/medium 2, unknown 0
  test: unknown 2
  gate: unknown 2
  land: haiku-5.5/low 1, unknown 1
B tag:builder-opus: lanes 1 (landed 1, abandoned 0)
  wall_seconds: median 1200, n 1, unknown 0
  fix_rounds: median 0, n 1, unknown 0
  blocking: median 0, n 1, unknown 0
  files: median unknown, n 0, unknown 1
  added: median unknown, n 0, unknown 1
  deleted: median unknown, n 0, unknown 1
  cost: median unknown, n 0, unknown 1
  build: opus-5.5/high 1, unknown 0
  fix: unknown 1
  review: unknown 1
  test: unknown 1
  gate: unknown 1
  land: unknown 1
exit 0
$ aco stats 2026-11-01..2026-11-07 tag:builder-opus --json
{"ok": true, "reason": "compared", "a": {"group": "2026-11-01..2026-11-07", "lanes": 2, "outcomes": {"landed": 2, "abandoned": 0}, "figures": {"wall_seconds": {"median": 2400, "n": 2, "unknown": 0}, "fix_rounds": {"median": 1.5, "n": 2, "unknown": 0}, "blocking": {"median": 2, "n": 1, "unknown": 1}, "files": {"median": 3, "n": 2, "unknown": 0}, "added": {"median": 70, "n": 2, "unknown": 0}, "deleted": {"median": 12.5, "n": 2, "unknown": 0}, "cost": {"median": null, "n": 0, "unknown": 2}}, "stages": {"build": {"choices": {"sonnet-5.5/high": 2}, "unknown": 0}, "fix": {"choices": {"none": 1}, "unknown": 1}, "review": {"choices": {"opus-5.5/medium": 2}, "unknown": 0}, "test": {"choices": {}, "unknown": 2}, "gate": {"choices": {}, "unknown": 2}, "land": {"choices": {"haiku-5.5/low": 1}, "unknown": 1}}}, "b": {"group": "tag:builder-opus", "lanes": 1, "outcomes": {"landed": 1, "abandoned": 0}, "figures": {"wall_seconds": {"median": 1200, "n": 1, "unknown": 0}, "fix_rounds": {"median": 0, "n": 1, "unknown": 0}, "blocking": {"median": 0, "n": 1, "unknown": 0}, "files": {"median": null, "n": 0, "unknown": 1}, "added": {"median": null, "n": 0, "unknown": 1}, "deleted": {"median": null, "n": 0, "unknown": 1}, "cost": {"median": null, "n": 0, "unknown": 1}}, "stages": {"build": {"choices": {"opus-5.5/high": 1}, "unknown": 0}, "fix": {"choices": {}, "unknown": 1}, "review": {"choices": {}, "unknown": 1}, "test": {"choices": {}, "unknown": 1}, "gate": {"choices": {}, "unknown": 1}, "land": {"choices": {}, "unknown": 1}}}}
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
  cost: median unknown, n 0, unknown 0
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
  cost: median unknown, n 0, unknown 0
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
