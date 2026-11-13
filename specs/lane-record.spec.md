# Lane record

Every lane that releases its claim, landed or abandoned, leaves one record of how
it went: trailers on the release commit of `refs/aco/state`, so a later reader can
compare process experiments. This file owns those trailer keys and values, the
`Routing:` line grammar they are read from, and what a figure that cannot be computed
does. `specs/release.spec.md` owns the release itself, `specs/storage-pin.spec.md` the
`production_paths` key (PIN-54..PIN-56), and `specs/ref-store-cas.spec.md` the trailers
every transition carries (CAS-06). `<routing line>` is the one `Routing:` line of
LANREC-16, read from the merge commit's message (a landed lane) or the `--abandoned`
reason (an abandoned one).

## Behavior table

| state \ trigger | landed lane (`--merged`) | abandoned lane (`--abandoned`) |
|---|---|---|
| a claim released | LANREC-01, LANREC-06 | LANREC-01, LANREC-06 |
| nothing left to release (REL-47) | LANREC-02 | — |
| the merge commit | LANREC-07 | — |
| wall time | LANREC-08 | LANREC-08 |
| production size | LANREC-09, LANREC-10 | — |
| the routing line | LANREC-13..LANREC-15 | LANREC-13, LANREC-14 |
| the routing fields | LANREC-11, LANREC-12, LANREC-17..LANREC-20 | LANREC-11, LANREC-12, LANREC-17..LANREC-20 |
| a figure that cannot be computed | LANREC-21 | LANREC-21 |
| a malformed `production_paths` | LANREC-22 | LANREC-22 |

## The record

- [ ] [LANREC-01] A release that releases a claim, `--merged` or `--abandoned`, under either storage, writes one record as trailers of its own release commit, after CAS-06's trailers.
- [ ] [LANREC-02] A release with nothing left to release (REL-47) writes no commit and so no record.
- [ ] [LANREC-03] The record is computed once, before the release commit is pushed: a push repeated after a lost race carries the same record.
- [ ] [LANREC-04] A trailer line is `<key>: <value>`. A figure that cannot be computed has no line: a missing line means unknown, and `0` is written only for a measured zero.
- [ ] [LANREC-05] A value is a validated token: an outcome, a sha, a model or effort name, a whole number or a tag (LANREC-17..LANREC-20). A finding, a reason or any other free text never reaches a trailer.
- [ ] [LANREC-06] `lane_outcome` is `landed` for `--merged` and `abandoned` for `--abandoned`; every record carries it.
- [ ] [LANREC-07] `lane_merge` is the 40-character sha of the merge commit the lane landed as: the forge's recorded one under `github` storage, the resolved trunk commit under `state-ref`. An abandoned lane has none.
- [ ] [LANREC-08] `lane_wall_seconds` is the whole seconds from the commit that opened the claim (an adopted lane: its adoption) to the merge commit's committer date, or for an abandoned lane to the release.
- [ ] [LANREC-09] `lane_files`, `lane_added` and `lane_deleted` count the files and the added and deleted lines the merge commit changes against its first parent under `production_paths` and outside `dependency_paths`.
- [ ] [LANREC-10] A binary file counts as one file and no lines. Without `production_paths`, or when that diff cannot be read, the three have no line, and an abandoned lane has none.
- [ ] [LANREC-11] `lane_build`, `lane_fix`, `lane_review`, `lane_test`, `lane_gate` and `lane_land` hold the `<model>/<effort>` or `none` that stage names in the routing line, one trailer for each stage that parses.
- [ ] [LANREC-12] `lane_fix_rounds` holds the routing line's fix rounds, `lane_blocking` its count of blocking findings, `lane_experiment` its experiment tag; each has a line only when it parses.

## The routing line

The routing line is the form below; `<model>` and `<effort>` name a stage's model and effort,
and the bracketed part stays out from the third fix round on. The line `Experiment: <tag>.`
may stand anywhere after the stages.

```text
Routing: build <model>/<effort>; fix <model>/<effort>|none; review <model>/<effort>; test <model>/<effort>|none; gate <model>/<effort>|none; land <model>/<effort>. Fix rounds: <n>[, hard: <why>]. Experiment: <tag>. Blocking: <finding> → <stage>; …|none
```

- [ ] [LANREC-13] A landed lane's routing line is read from its merge commit's message, never from the pull request's body, which stays editable after the merge (LAND-64).
- [ ] [LANREC-14] A message or reason with no `Routing:` line, or with more than one, records no routing figure; so does a merge made outside `aco land` that lost the line.
- [ ] [LANREC-15] An abandoned lane's routing line is read from its `--abandoned` reason, which the reason's bound (REL-02) already keeps to one line.
- [ ] [LANREC-16] The routing line is one line that starts `Routing: `; the stages `build`, `fix`, `review`, `test`, `gate` and `land` follow in that order, each as `<name> <model>/<effort>`, separated by `; `.
- [ ] [LANREC-17] `<model>` is lowercase letters, digits, `.` and `-`, `<effort>` lowercase letters, digits and `-`; `fix`, `test`, `gate` may be `none`. A stage that does not fit has no trailer; the others still do.
- [ ] [LANREC-18] `Fix rounds: <n>` takes `<n>` of one to three digits; any other value records no rounds. The text after `, hard:` is never read.
- [ ] [LANREC-19] `Blocking:` is `none`, which counts `0`, or findings separated by `; `, each ending `→ <stage>`, which count one each. A finding without exactly one `→ <stage>` makes the count unknown.
- [ ] [LANREC-20] `Experiment: <tag>` takes `<tag>` of lowercase letters, digits and `-`, one to 40 characters, as a sentence of its own; any other value records no tag.

## Failure

- [ ] [LANREC-21] A figure that cannot be computed (no or unparsable routing line, an unreadable merge commit, a failed diff or forge read) has no line and never refuses, delays or changes the output of the release.
- [ ] [LANREC-22] A `production_paths` that is malformed refuses when the configuration is read, like every key of it (PIN-55, PIN-56), before any release writes; the record never softens that refusal.

## Never

- The record is never written anywhere but the release commit of `refs/aco/state`; no file, comment or second ref holds it.
- A trailer never carries a finding, a reason, a `hard:` text, a title or a path.
- A missing figure is never written as `0`, and no figure is guessed from another source.
- A lane released before this record existed has none, and nothing backfills the append-only state ref.
- The record holds no cost or token figure: no source aco can read has one.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local bare repository
with `main` at one commit, a git identity, `origin/HEAD` and `ACO_AGENT` set to `Ada`;
`<sha>` is a full commit sha.

### E-LANREC-01 — a landed lane leaves its record

Setup: bare-remote, fake `gh`, `.aco/board.toml` naming `production_paths = ["src/"]`, issue `#42` claimed on `ada/issue-42`, pull request `#57` merged by `aco land`, its body `Routing: build sonnet-5.5/high; fix none; review opus-5.5/medium; test sonnet-5.5/medium; gate none; land haiku-5.5/low. Fix rounds: 0. Experiment: builder-sonnet. Blocking: none` and `Work-Item: #42`, changing `src/a.py` by 3 added lines

```console
$ git log -1 --format=%B refs/aco/state | grep '^lane_'
lane_outcome: landed
lane_merge: <sha>
lane_wall_seconds: 1840
lane_files: 1
lane_added: 3
lane_deleted: 0
lane_build: sonnet-5.5/high
lane_fix: none
lane_review: opus-5.5/medium
lane_test: sonnet-5.5/medium
lane_gate: none
lane_land: haiku-5.5/low
lane_fix_rounds: 0
lane_blocking: 0
lane_experiment: builder-sonnet
```

### E-LANREC-02 — an abandoned lane without a routing line

Setup: bare-remote, a linked worktree on `docs/tidy-readme`, its claim live

```console
$ aco release --abandoned "stopped for the day"
RELEASED lane docs/tidy-readme: <claim-id>
exit 0
$ git log -1 --format=%B refs/aco/state | grep '^lane_'
lane_outcome: abandoned
lane_wall_seconds: 95
```
