# Lane record

Every lane that releases its claim, landed or abandoned, leaves one record of how
it went: trailers on the release commit of `refs/aco/state`, so a later reader can
compare process experiments. This file owns those trailer keys and values, the
lane record file their routing figures are read from (LANREC-30..LANREC-46), the runs a lane
stores with its claim (LANREC-52..LANREC-70), the
`Routing:` line grammar they are read from where no file is given, and what a figure that
cannot be computed does. `specs/release.spec.md` owns the release itself,
`specs/land.spec.md` the landing, `specs/storage-pin.spec.md` the `production_paths` key
(PIN-54..PIN-56), and `specs/ref-store-cas.spec.md` the trailers every transition carries
(CAS-06). `<routing line>` is the one `Routing:` line of LANREC-16, read from the merge
commit's message (a landed lane) or the `--abandoned` reason (an abandoned one). `<file>` is
a lane record file, `<defect>` the first thing wrong with it, `<full>` the 40-digit sha its
last verdict judged and `<reviewed>` the `--head` value of `aco land`.

## Behavior table

| state \ trigger | landed lane (`--merged`) | abandoned lane (`--abandoned`) |
|---|---|---|
| a claim released | LANREC-01, LANREC-06 | LANREC-01, LANREC-06 |
| nothing left to release (REL-47) | LANREC-02 | — |
| the merge commit | LANREC-07 | — |
| wall time | LANREC-08 | LANREC-08 |
| production size | LANREC-09, LANREC-10, LANREC-25 | — |
| item size class | LANREC-28 | — |
| the routing line, without `--record` | LANREC-13..LANREC-15 | LANREC-13, LANREC-14 |
| the routing fields | LANREC-11, LANREC-12, LANREC-17..LANREC-20, LANREC-23, LANREC-24, LANREC-26, LANREC-27 | LANREC-11, LANREC-12, LANREC-17..LANREC-20, LANREC-23, LANREC-24, LANREC-26, LANREC-27 |
| `aco lane-record check <file>` | LANREC-30..LANREC-37, LANREC-45, LANREC-46, LANREC-48, LANREC-49 | LANREC-30..LANREC-37, LANREC-45, LANREC-46, LANREC-48, LANREC-49 |
| `--record <file>` | LANREC-31, LANREC-38..LANREC-40, LANREC-42..LANREC-46, LANREC-49, LANREC-50 | LANREC-31, LANREC-41..LANREC-43, LANREC-45, LANREC-46, LANREC-49, LANREC-50 |
| `aco lane-record begin <item> --run <run>` | LANREC-52..LANREC-54, LANREC-58..LANREC-60, LANREC-62..LANREC-65, LANREC-68..LANREC-70 | LANREC-52..LANREC-54, LANREC-58..LANREC-60, LANREC-62..LANREC-65, LANREC-68..LANREC-70 |
| `aco lane-record add <item> <file> --run <run>` | LANREC-31, LANREC-55..LANREC-60, LANREC-62, LANREC-63, LANREC-66, LANREC-68..LANREC-70 | LANREC-31, LANREC-55..LANREC-60, LANREC-62, LANREC-63, LANREC-66, LANREC-68..LANREC-70 |
| stored runs and a handover, a rescope, a release or a landing | LANREC-61, LANREC-67 | LANREC-61, LANREC-67 |
| a figure read back from a release commit | LANREC-51 | LANREC-51 |
| a figure that cannot be computed | LANREC-21 | LANREC-21 |
| a malformed `production_paths` | LANREC-22 | LANREC-22 |

## The record

- [ ] [LANREC-01] A release that releases a claim, `--merged` or `--abandoned`, under either storage, writes one record as trailers of its own release commit, after CAS-06's trailers.
- [ ] [LANREC-02] A release with nothing left to release (REL-47) writes no commit and so no record.
- [ ] [LANREC-03] The record is computed once, before the release commit is pushed: a push repeated after a lost race carries the same record.
- [ ] [LANREC-04] A trailer line is `<key>: <value>`. A figure that cannot be computed has no line: a missing line means unknown, and `0` is written only for a measured zero.
- [ ] [LANREC-05] A value is a validated token: an outcome, a sha, a model or effort name, a size class, a whole number or a tag. A finding, a reason or any other free text never reaches a trailer.
- [ ] [LANREC-06] `lane_outcome` is `landed` for `--merged` and `abandoned` for `--abandoned`; every record carries it.
- [ ] [LANREC-07] `lane_merge` is the 40-character sha of the merge commit the lane landed as: the forge's recorded one under `github` storage, the resolved trunk commit under `state-ref`. An abandoned lane has none.
- [ ] [LANREC-08] `lane_wall_seconds` is the whole seconds from the state-ref commit that added the claim (adopted: its adoption) to the merge commit's committer date, or the release commit's if abandoned.
- [ ] [LANREC-09] `lane_files`, `lane_added` and `lane_deleted` count the files and lines the merge commit changes against its first parent under `production_paths`, outside `dependency_paths`.
- [ ] [LANREC-10] A renamed file counts once, with only its changed lines; a binary file counts as one file, no lines. Without `production_paths`, with an unreadable diff or an abandoned lane, the three have no line.
- [ ] [LANREC-11] `lane_build`, `lane_fix`, `lane_review`, `lane_test`, `lane_gate` and `lane_land` hold the `<model>/<effort>` or `none` that stage names in the routing line, one trailer for each stage that parses.
- [ ] [LANREC-12] `lane_fix_rounds` holds the routing line's fix rounds, `lane_blocking` its count of blocking findings, `lane_experiment` its experiment tag; each has a line only when it parses.
- [ ] [LANREC-28] `lane_size` is `S`, `M` or `L`: the item's top-level `size` from the read the release already makes; an unsized item, an abandoned lane or a release without an issue has no line.
- [ ] [LANREC-29] A reader tells a lane's issue from its release commit's subject `release issue <n>`; a lane release and any other transition name none.

## The routing line

The routing line is the form below; `<model>` and `<effort>` name a stage's model and effort,
and the bracketed part comes from the third fix round on. The line `Experiment: <tag>.`
may stand anywhere after the stages and before `Blocking:`.

```text
Routing: build <model>/<effort>; fix <model>/<effort>|none; review <model>/<effort>; test <model>/<effort>|none; gate <model>/<effort>|none; land <model>/<effort>. Fix rounds: <n>[, hard: <why>]. Experiment: <tag>. Blocking: <finding> → <stage>; …|none
```

- [ ] [LANREC-13] A landed lane's routing line is read from its merge commit's message, never from the pull request's body, which stays editable after the merge (LAND-64).
- [ ] [LANREC-14] A message or reason with no `Routing:` line, or with more than one, records no routing figure; so does a merge made outside `aco land` that lost the line.
- [ ] [LANREC-15] An abandoned lane's routing line is read from its `--abandoned` reason, which the reason's bound (REL-02) already keeps to one line.
- [ ] [LANREC-16] The routing line is one line that starts `Routing: `; the stages `build`, `fix`, `review`, `test`, `gate` and `land` follow in that order, each as `<name> <model>/<effort>`, separated by `; `.
- [ ] [LANREC-17] `<model>` is lowercase letters, digits, `.` and `-`, `<effort>` lowercase letters, digits and `-`; `fix`, `test`, `gate` may be `none`. A stage that does not fit has no trailer; the others still do.
- [ ] [LANREC-18] `Fix rounds: <n>` takes `<n>` of one to three digits; any other value records no rounds. The text after `, hard:` is never read.
- [ ] [LANREC-19] `Blocking:` is `none` (count `0`) or findings split by `; `, each ending one `→ <stage>`. `<n>× <text> → <stage>`, `<n>` 1 to 999, counts `<n>`; any other finding one; `0×` or no arrow: unknown.
- [ ] [LANREC-20] `Experiment: <tag>` takes `<tag>` of lowercase letters, digits and `-`, one to 40 characters, as a sentence of its own; any other value records no tag.
- [ ] [LANREC-23] A doubled `Fix rounds:`, `Experiment:` or `Blocking:` sentence, `Blocking: none` plus more, or stages out of LANREC-16's order record that field as unknown; the others still read.
- [ ] [LANREC-24] The word after a finding's `→` is never checked against the six stages: `ci`, `head` and any other word count the finding, because the line's writer owns the destinations.
- [ ] [LANREC-25] `production_paths = []` is the key left unset: the three size figures have no line (LANREC-10), never a measured zero.
- [ ] [LANREC-26] Stages out of LANREC-16's order leave all six stage fields unknown, those standing in order included; `Fix rounds:`, `Blocking:` and `Experiment:` still record.
- [ ] [LANREC-27] A `×` counts only when a space follows it: `3×3 matrix → ci` is one finding.

## The lane record file

The lane record file is the JSON file a lane hands `aco land` or `aco release` with
`--record`: counts, model names, tags and shas, never a finding's text (LANREC-05). A file larger than 1048576 bytes `cannot be read` (LANREC-31).

- [ ] [LANREC-30] `aco lane-record check <file>` reads the file alone, writes nothing, needs no checkout, and prints `lane record <file> is valid`, exit `0`.
- [ ] [LANREC-31] A file that `check`, `land` or `release` cannot use refuses `lane record <file> is invalid: <defect>`, exit `2`: `cannot be read (<reason>)`, `not valid JSON`, LANREC-32..37, 46, 48, 49 (E-LANREC-03).
- [ ] [LANREC-32] The file is one JSON object of `version`, `stages`, `fix_rounds`, `blocking`, `verdicts` and the optional `risk`, `misses` and `experiment`; an extra key, a missing one or a key stated twice refuses.
- [ ] [LANREC-33] `version` is judged first: `1` passes; a whole number of up to 20 digits refuses `version <n> is unknown; this aco reads version 1`, any other `version must be the whole number 1`.
- [ ] [LANREC-34] `stages` names `build`, `fix`, `review`, `test`, `gate` and `land`, each `<model>/<effort>` as LANREC-17 reads it, or `none` for `fix`, `test` and `gate`; `land` is the model dispatched to land.
- [ ] [LANREC-35] `fix_rounds` and `blocking` each hold a whole number from `0` to `999` for each finding stage `review`, `gate`, `ci` and `test`; a finding a stand-in raised counts under `gate`.
- [ ] [LANREC-47] A fix round counts under the stage whose report raised the blocking findings it fixes; one fixing only folded follow-ups, under the stage that raised them, the first of `review`, `gate`, `ci`, `test`.
- [ ] [LANREC-36] `verdicts` lists each review and gate verdict, oldest first, as `stage` (`review` or `gate`), `verdict` (`approve` or `revise`) and the full commit `sha` it judged; the list may be empty.
- [ ] [LANREC-37] `risk` and `experiment`, each optional, are tags as LANREC-20 reads one; no value in the file holds whitespace, so a count, a sha or a tag is one word.
- [ ] [LANREC-48] `misses`, optional, holds a whole number from `0` to `999` for each finding stage: how many of its blocking findings the head contract's Misses rule counts, its exclusions applied by the writer.
- [ ] [LANREC-49] A stage's misses above its blocking refuses `misses.<stage> exceeds blocking.<stage>`, through LANREC-31 (E-LANREC-11).
- [ ] [LANREC-38] `aco land <n> --head <reviewed> --record <file>` refuses `the lane record's last verdict judged <full>, not the reviewed <reviewed>`, exit `2`, unless `<full>` starts with `<reviewed>`.
- [ ] [LANREC-39] A record that states no verdict refuses `the lane record states no review or gate verdict, so it judged no head to land`, exit `2`.
- [ ] [LANREC-40] LANREC-31 refuses at the argument parse; LANREC-38, LANREC-39 and LANREC-44 after the repository root and board.toml are read; all before any merge or write, on a rerun too (E-LANREC-04).
- [ ] [LANREC-41] `aco release --abandoned <reason> --record <file>` writes the file's record; `--record` with `--merged` refuses `--record applies to --abandoned only`, exit `2`; with neither, REL-01 (E-LANREC-05).
- [ ] [LANREC-42] With `--record`, LANREC-11 and LANREC-12 hold the file's figures, `lane_fix_rounds` and `lane_blocking` summed over the finding stages; no routing line is read (LANREC-13..LANREC-15).
- [ ] [LANREC-43] A file also writes `lane_risk`, then `lane_fix_rounds_<stage>` and `lane_blocking_<stage>` for `review`, `gate`, `ci` and `test`, each a whole number; an omitted `risk` has no line.
- [ ] [LANREC-44] `aco land` also refuses a last verdict of `revise`: `the lane record's last verdict is revise at <stage>, not approve`, exit `2`; `release --abandoned` takes any last verdict (E-LANREC-08).
- [ ] [LANREC-45] A refusal line holds 200 characters: a `<file>` that does not fit loses the front of its directory (`…/`) while the file name and `<defect>` stay whole, so only those two can pass 200 (E-LANREC-10).
- [ ] [LANREC-46] A file that starts with a UTF-8 byte order mark refuses the defect `begins with a UTF-8 byte order mark; save it without one` (E-LANREC-09).
- [ ] [LANREC-50] A file that states `misses` also writes `lane_misses_<stage>` for `review`, `gate`, `ci` and `test` after the `lane_blocking_<stage>` lines; a file without it, and a lane with no file, has none.
- [ ] [LANREC-51] A reader reads `lane_risk` and each `lane_fix_rounds_`, `lane_blocking_`, `lane_misses_` line by stage; a missing, repeated or malformed line, a count above `999` or a non-tag risk is unknown alone.

LANREC-47 and the writer's part of LANREC-48 (Misses and its exclusions) bind the lane writer: `aco` cannot check them, so their proof is `plugins/atelier/lane/record.js` in overnightworks/marketplace, and the figures stay unknown until it writes them.

## Stored runs

A lane may run its stages in more than one workflow run. `aco lane-record begin` marks a run and `aco lane-record add` stores its record, both under the claim's id: the claim's runs file `runs/<claim-id>.json` of `refs/aco/state` (CAS-27, CAS-28), one file per live claim that has runs, which no command but these reads. `<run>` is a run id, `<tip>` a full 40-digit commit sha, `<label>` the item as its storage names it (`#42`, `aco-xxxxxx`) and `<stage>` one of `build`, `review`, `fix`, `test`, `gate`. Nothing reads the stored runs yet.

- [ ] [LANREC-52] `aco lane-record begin <item> --run <run> [--start-tip <tip>] [--agent NAME] [--json]` adds a begun entry and prints `BEGAN run <run> of <label>` (E-LANREC-12).
- [ ] [LANREC-63] Only the claim's holder may begin or add: another session refuses `only the holder may begin a run of <label> (holder='…', this session='…')`, `add a run to` for an add (E-LANREC-13).
- [ ] [LANREC-68] A begin or an add for an unclaimed item refuses with the sentence of REL-09.
- [ ] [LANREC-53] The same run id and start tip prints `ALREADY BEGUN run <run> of <label>` and changes nothing; another start tip refuses `run <run> of <label> was begun with start tip <tip>, not <tip>`.
- [ ] [LANREC-64] A begin of a run already added refuses `run <run> of <label> was added already; it cannot be begun again`, exit `2`.
- [ ] [LANREC-54] An entry stores whether it follows, judged once at its begin: the first entry when it has no start tip, a later one when the newest stored entry's end tip is its start tip or an ancestor of it.
- [ ] [LANREC-65] A start tip or end tip git cannot read, a first entry with a start tip and an earlier entry without an end tip do not follow.
- [ ] [LANREC-55] `aco lane-record add <item> <file> --run <run> --end-tip <tip> --ran <stage>... [--agent NAME] [--json]` stores the file's record on that run and prints `ADDED run <run> to <label>: <n> stored`.
- [ ] [LANREC-66] An add judges the file as `aco lane-record check` does (LANREC-31); a `--ran` stage whose slot in the file is `none` refuses `the record's stage <stage> is none, which --ran contradicts`.
- [ ] [LANREC-56] The same entry again prints `ALREADY ADDED run <run> to <label>: <n> stored` and changes nothing; another entry under an added run id refuses `run <run> of <label> has another entry stored already`.
- [ ] [LANREC-57] An add for a run that was not begun refuses `run <run> of <label> was not begun; run aco lane-record begin first`, exit `2` (E-LANREC-14).
- [ ] [LANREC-58] A `<run>` is 1 to 128 characters of the claim id's grammar, a `<tip>` 40 lowercase hexadecimal digits, `--ran` given once and naming one or more of the five stages, each once; a breach is a usage refusal.
- [ ] [LANREC-59] A write that finds the stored runs changed since the command read them refuses `the stored runs of <label> were written since this command read them; run the same command again`.
- [ ] [LANREC-60] A begin and an add each land one compare-and-swap commit, `lane-record issue <n>`, with CAS-06's trailers (intent `lane_record`), then `run: <run>`, and no `lane_` trailer: `aco stats` counts no lane.
- [ ] [LANREC-69] With `--json` the successes report `begun`, `already_begun`, `added` or `already_added`; LANREC-57, LANREC-63..68 and LANREC-70 `precondition_failed`, LANREC-59 and LANREC-62 `unavailable`.
- [ ] [LANREC-70] A begin or an add without `--agent` and without an agent identity in the environment refuses as every writing command does, before it reads anything.
- [ ] [LANREC-61] Stored runs survive `aco handover` (the new holder may begin and add, the previous holder's add refuses as a non-holder's) and `aco rescope`.
- [ ] [LANREC-67] A release and a landing remove the claim's runs file in the release's own commit; a re-claimed item starts empty.
- [ ] [LANREC-62] A stored runs file that is not exactly the stored shape refuses `the stored runs of <label> cannot be used: <defect>` and writes nothing.

The runs file is `{"version": 1, "runs": [...]}` in begin order; an entry holds the run id, its start tip or `null`, whether it follows and, once added, its end tip, the stages that ran and the record exactly as the file stated it. A run that worked without a begin is invisible, and commits made by hand between two runs belong to no run's figures.

## Failure

- [ ] [LANREC-21] A figure that cannot be computed (no or unparsable routing line, an unreadable merge commit, a failed diff or forge read) has no line and never refuses, delays or changes the output of the release.
- [ ] [LANREC-22] A `production_paths` that is malformed refuses when the configuration is read, like every key of it (PIN-55, PIN-56), before any release writes; the record never softens that refusal.

## Never

- The record is never stored anywhere but the release commit of `refs/aco/state`; no file, comment or second ref holds it. Each run's entry is stored only under its claim's id in the state tree, until the release that removes the claim. A lane record file is read once, at `land`, `release` or `add`; `add` stores its validated record as the run's entry, never the file.
- A trailer never carries a finding, a reason, a `hard:` text, a title or a path.
- A missing figure is never written as `0`, and no figure is guessed from another source.
- A lane released before this record existed has none, and nothing backfills the append-only state ref.
- The record holds no cost or token figure: no source aco can read has one.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local bare repository
with `main` at one commit, a git identity, `origin/HEAD` and `ACO_AGENT` set to `Ada`;
`<sha>` is a full commit sha.

### E-LANREC-01 — a landed lane leaves its record

Setup: bare-remote, fake `gh`, `.aco/board.toml` naming `production_paths = ["src/"]`, issue `#42`, whose body declares `size: M`, claimed on `ada/issue-42`, pull request `#57` merged by `aco land`, its body `Routing: build sonnet-5.5/high; fix none; review opus-5.5/medium; test sonnet-5.5/medium; gate none; land haiku-5.5/low. Fix rounds: 0. Experiment: builder-sonnet. Blocking: none` and `Work-Item: #42`, changing `src/a.py` by 3 added lines

```console
$ git log -1 --format=%B refs/aco/state | grep '^lane_'
lane_outcome: landed
lane_merge: <sha>
lane_wall_seconds: 1840
lane_files: 1
lane_added: 3
lane_deleted: 0
lane_size: M
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

### E-LANREC-03 — a lane record file with an unknown version

Setup: a file `lane-record.json` stating `"version": 2`, no checkout

```console
$ aco lane-record check lane-record.json
ERROR: lane record lane-record.json is invalid: version 2 is unknown; this aco reads version 1
exit 2
```

### E-LANREC-04 — a landing whose record judged another head

Setup: bare-remote, fake `gh`, pull request `#57` open with every check green, its head `<head>`, a file `lane-record.json` whose last verdict judged `<full>`

```console
$ aco land 57 --head <head> --record lane-record.json
ERROR: the lane record's last verdict judged <full>, not the reviewed <head>
exit 2
```

Nothing is merged, deleted or written; the claim stands.

### E-LANREC-05 — an abandoned lane leaves the file's record

Setup: bare-remote, a linked worktree on `docs/tidy-readme`, its claim live, a file `lane-record.json` with `build sonnet-5.5/high`, `fix none`, `review opus-5.5/medium`, `test sonnet-5.5/medium`, `gate none`, `land haiku-5.5/low`, fix rounds `1`, `0`, `2`, `0` and blocking counts `3`, `0`, `1`, `0` and misses `0`, `0`, `1`, `0` for `review`, `gate`, `ci`, `test`, risk `routine` and experiment `builder-sonnet`

```console
$ aco release --abandoned "stopped for the day" --record lane-record.json
RELEASED lane docs/tidy-readme: <claim-id>
exit 0
$ git log -1 --format=%B refs/aco/state | grep '^lane_'
lane_outcome: abandoned
lane_wall_seconds: 95
lane_build: sonnet-5.5/high
lane_fix: none
lane_review: opus-5.5/medium
lane_test: sonnet-5.5/medium
lane_gate: none
lane_land: haiku-5.5/low
lane_fix_rounds: 3
lane_blocking: 4
lane_experiment: builder-sonnet
lane_risk: routine
lane_fix_rounds_review: 1
lane_fix_rounds_gate: 0
lane_fix_rounds_ci: 2
lane_fix_rounds_test: 0
lane_blocking_review: 3
lane_blocking_gate: 0
lane_blocking_ci: 1
lane_blocking_test: 0
lane_misses_review: 0
lane_misses_gate: 0
lane_misses_ci: 1
lane_misses_test: 0
```

### E-LANREC-06 — a record for a landing is not taken by release

Setup: bare-remote, a linked worktree on `docs/tidy-readme`, its claim live, a valid file `lane-record.json`

```console
$ aco release --merged 57 --record lane-record.json
ERROR: --record applies to --abandoned only
exit 2
```

### E-LANREC-07 — a landing whose record states no verdict

Setup: bare-remote, fake `gh`, pull request `#57` open with every check green, a valid file `lane-record.json` stating `"verdicts": []`

```console
$ aco land 57 --head <head> --record lane-record.json
ERROR: the lane record states no review or gate verdict, so it judged no head to land
exit 2
```

### E-LANREC-08 — a landing whose record ends in a revise verdict

Setup: bare-remote, fake `gh`, pull request `#57` open with every check green, a valid file `lane-record.json` whose last verdict is `revise` at `gate` on `<full>`

```console
$ aco land 57 --head <head> --record lane-record.json
ERROR: the lane record's last verdict is revise at gate, not approve
exit 2
```

Nothing is merged, deleted or written; the claim stands.

### E-LANREC-09 — a lane record file that starts with a byte order mark

Setup: a file `lane-record.json` whose first three bytes are a UTF-8 byte order mark, no checkout

```console
$ aco lane-record check lane-record.json
ERROR: lane record lane-record.json is invalid: begins with a UTF-8 byte order mark; save it without one
exit 2
```

### E-LANREC-10 — a lane record file in a deep directory

Setup: a file `lane-record.json` stating `"version": 2`, in a directory path longer than a refusal line, no checkout

```console
$ aco lane-record check /long/…/directory/lane-record.json
ERROR: lane record …/directory/lane-record.json is invalid: version 2 is unknown; this aco reads version 1
exit 2
```

### E-LANREC-11 — a record whose misses exceed its blocking findings

Setup: a file `lane-record.json` stating `"blocking": {"review": 3, "gate": 0, "ci": 1, "test": 0}` and `"misses": {"review": 0, "gate": 0, "ci": 2, "test": 0}`, no checkout

```console
$ aco lane-record check lane-record.json
ERROR: lane record lane-record.json is invalid: misses.ci exceeds blocking.ci
exit 2
```

### E-LANREC-12 — a run is begun and added twice

Setup: bare-remote, issue `#42` claimed by `Ada`, a valid file `lane-record.json` stating `build sonnet-5.5/high` and `review opus-5.5/medium`, `ACO_AGENT` set to `Ada`

```console
$ aco lane-record begin 42 --run run-1
BEGAN run run-1 of #42
exit 0
$ aco lane-record add 42 lane-record.json --run run-1 --end-tip <sha> --ran build review
ADDED run run-1 to #42: 1 stored
exit 0
$ aco lane-record begin 42 --run run-2 --start-tip <sha>
BEGAN run run-2 of #42
exit 0
$ aco lane-record add 42 lane-record.json --run run-2 --end-tip <sha> --ran build review
ADDED run run-2 to #42: 2 stored
exit 0
$ git log -1 --format=%B refs/aco/state | head -1
lane-record issue 42
```

### E-LANREC-13 — a session that does not hold the claim stores no run

Setup: bare-remote, issue `#42` claimed by `Ada`, `ACO_AGENT` set to `Bea`

```console
$ aco lane-record begin 42 --run run-1
ERROR: only the holder may begin a run of #42 (holder='Ada', this session='Bea')
exit 2
```

### E-LANREC-14 — an add without a begin

Setup: bare-remote, issue `#42` claimed by `Ada`, a valid file `lane-record.json`, `ACO_AGENT` set to `Ada`

```console
$ aco lane-record add 42 lane-record.json --run run-1 --end-tip <sha> --ran build
ERROR: run run-1 of #42 was not begun; run aco lane-record begin first
exit 2
```
