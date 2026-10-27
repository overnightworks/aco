# `aco board`

`aco board` projects the open work board read-only, `--json` the one
output mode (the operator-facing page is in `aco serve`,
`specs/serve.spec.md`); a bare `aco board` naming no `--json` refuses
instead (BOARD-44). This file owns `--json`'s own
shape -- its keys -- and the one forge-resolution precondition `aco
next`/`aco rulings` share with it before either ever reads an issue (`##
The shared forge precondition`, cited rather than restated by
`specs/next.spec.md`/`specs/rulings.spec.md`). It never restates a fact
another file already owns: `specs/landing-grammar.spec.md` owns the
Landungen pairing rule (LAND-41..54); the absent- and untracked-pin
refusals are `specs/storage-pin.spec.md`'s (PIN-01/PIN-32);
`specs/output.spec.md` owns the `--json` envelope itself (OUT-nn: key
order, `ok`, `message`) that wraps BOARD-11's own top-level keys. `board`'s
own ranking, scoring, and per-item field semantics (`score`,
`priority_bucket`, `age_days`, ...) are pre-existing, untouched behaviour
this lane does not re-derive into criteria; each item's own
`actionable`/`actionable_reason` fields are the one pair this file grades,
since `next`'s own SKIPPED list (`specs/next.spec.md`) reuses that exact
reason text.

## Behavior table

| state \ trigger | `aco board` (no `--json`) | `--json` |
|---|---|---|
| any state, before any other read | BOARD-44 | — |
| unsupported canonical-remote host | — | BOARD-02, BOARD-43 |
| canonical remote with no URL configured | — | BOARD-53, BOARD-43 |
| `.aco/board.toml` absent | — | PIN-32 (cited) |
| `.aco/board.toml` present but untracked or ignored | — | PIN-01 (cited) |
| `--repo` under `storage = "state-ref"` | — | BOARD-42, BOARD-43 |
| the Landungen view's own rows | — | BOARD-12 |
| an item with no recognized `kind` | — | BOARD-08 |
| a state-ref item the store cannot read | — | BOARD-54 |
| an uncut `[[slice]]` row | — | BOARD-14 |
| a completed run | — | BOARD-11, BOARD-13 |
| `--json`'s success/refusal envelope | — | BOARD-11, BOARD-43 (OUT-nn cited) |
| an item with a `size`, measured or not | — | BOARD-26, BOARD-27, BOARD-31 |
| a claim commit whose `item:` trailer is no ASCII number of at most 18 digits | — | BOARD-56 |
| an item carries the idea label | — | BOARD-57 |
| a container whose child-count summary disagrees with its sub-issue list | — | BOARD-58 |

## No `--json`

- BOARD-15, BOARD-16, BOARD-17, BOARD-18, BOARD-19, BOARD-20, BOARD-21, BOARD-22, BOARD-23, BOARD-28, BOARD-32, BOARD-33, BOARD-34, BOARD-35, BOARD-36, BOARD-37, BOARD-38, BOARD-39, BOARD-40, BOARD-41, BOARD-45, BOARD-46, BOARD-47, BOARD-48, BOARD-49, BOARD-50, BOARD-51, BOARD-52 (retired 04.10.2026): `--html`'s static page and `--serve`'s loopback server -- the page itself, its token subsystem, and its request/response wire contract -- no longer exist; `aco serve` (`specs/serve.spec.md`) is the one decision board now, reading its own rulings through `aco rulings --json` and writing through `aco rule` instead of this command's `--json`.

- BOARD-55 (retired 23.10.2026): the `--serve` refusal pointing at `aco-board serve` went with the flag itself; `aco board --serve` is now an unknown argument like any other.

- [ ] [BOARD-44] `aco board` naming no `--json` refuses `aco board requires --json`, exit `2`, before any forge, pin, or repository read (see E-BOARD-16).


## The shared forge precondition

`aco next` and `aco rulings` reach this exact check the same way `board`
does, before either reads a single issue -- cited there, not restated.

- [ ] [BOARD-02] A canonical remote whose host is not GitHub refuses `ERROR: no forge adapter for host <host>`, exit `2`, before any GitHub read is made (see E-BOARD-01).
- [ ] [BOARD-53] A canonical `<remote>` with no URL configured refuses `cannot determine the trunk: canonical remote '<remote>' is not configured`, exit `2` (see E-BOARD-20).
- [ ] [BOARD-01] `board` reaches the same absent- or untracked-`.aco/board.toml` refusal `specs/storage-pin.spec.md` owns (PIN-01/PIN-32), exit `2`, before the host check above ever runs.
- [ ] [BOARD-42] Under `storage = "state-ref"`, `board`/`next`/`rulings` resolve the state-ref forge like `item show`/`edit`/`close`; `--repo` there refuses the same as those (PIN-04, PIN-05).

- BOARD-03, BOARD-04, BOARD-05, BOARD-06, BOARD-07, BOARD-09, BOARD-10, BOARD-24, BOARD-25, BOARD-29, BOARD-30 (retired 20.09.2026): the fixed-width text table (`board.render`) they described no longer exists; `--json`'s own item fields, `landings` array, `uncut` array, and `measurements` object (BOARD-11..14, BOARD-26, BOARD-27, BOARD-31) carried the equivalent facts, `--html`'s own sections (retired in turn, 04.10.2026) alongside them while that page still existed.

## `--json`

- [ ] [BOARD-11] `board --json` wraps OUT-nn (`reason: "projected"`) around `items`, `ready_now`, `stale`, `recovery`, `landings`, `uncut`, `requests`, `measurements` only, never `repository` (E-BOARD-04).
- [ ] [BOARD-43] `--json` on a dispatched refusal (BOARD-02, BOARD-42, BOARD-53) prints that envelope with the sentence as `message` and `reason` below, exit `2` (see E-BOARD-15).
- [ ] [BOARD-08] An item the forge reports no `kind` for, or a non-`container` `kind`, carries `"container": null` even with child counts of its own: never guessed at (see E-BOARD-03).
- [ ] [BOARD-54] A state-ref item PIN-14/PIN-15 refuses is listed, open, with BODY-50's reason and its read defect, e.g. `body malformed: record: no [record] table`; every other item reads as before (NEXT-36).

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| PIN-04 (`--repo` under `storage = state-ref`) | `invalid_usage` |
| BOARD-02 (no forge adapter for host), BOARD-53 (canonical remote with no URL configured), PIN-05 (no resolvable default branch) | `unavailable` |
- [ ] [BOARD-12] Each `landings` row carries `{"item", "committed_at", "sha", "pull_request"}`, exactly one of `sha`/`pull_request` non-`null` (LAND-54).
- [ ] [BOARD-13] Each item's `open_blockers` is split into a same-repository `int` list plus a sibling `foreign_blockers` list of `"<repository>#<n>"` strings, never one mixed list.
- [ ] [BOARD-14] An `uncut` row's own `scope` key is present, canonical and non-empty only when that row carries a `scope` of its own; a scopeless row's object carries no `scope` key at all, never `"scope": null`.
- [ ] [BOARD-26] Each item object carries `size` (`"S"`/`"M"`/`"L"`/`null`) and `estimate` (`null`, or the fields below) alongside its other fields.

  ```
  {"size": "M", "estimate": {"item": "aco-000001", "size": "M", "median_hours": 5, "n": 4, "weak": false}}
  {"size": null, "estimate": null}
  ```
- [ ] [BOARD-27] The top-level `measurements` object carries exactly `{"classes", "unfinished", "unparsed", "since", "as_of"}` (see E-BOARD-04).
- [ ] [BOARD-31] Each `classes` entry carries `{"stats": {"size", "n", "median_hours", "p80_hours", "weak"}, "first_event_at", "last_event_at"}`; `since` is `null` only with no lane event read.
- [ ] [BOARD-56] A claim commit on the state ref whose `item:` trailer is no ASCII number of at most 18 digits reads like a lane's: left out of the measurements, not counted in `unparsed`; `board` and `next` exit `0`.
- [ ] [BOARD-57] An item labelled `idea_label` carries `"idea": true` in `--json`, `"actionable": false` and `"actionable_reason": "idea"`, whatever its body, `body malformed` included (NEXT-43).
- [ ] [BOARD-58] A container whose summary counts a child takes its `container` closed and total counts and open children from its sub-issue list; a summary that disagrees refuses nothing, exit `0`.

## Never

- `board`'s `--json` never carries a `read_state` key on any item, and never a bare `null` in place of an absent `foreign_blockers`/`uncut` `scope` entry.
- `aco board` never regains an `--html`/`--serve` output mode of its own: `aco serve` (`specs/serve.spec.md`) is the one decision board going forward.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local
bare repository with `main` at one commit, a git identity, `origin/HEAD`, a
tracked `.aco/board.toml`, and `ACO_AGENT` set to `Ada`. A session
that reads GitHub issues also names a fixed, deterministic fake `gh` as a
setup precondition (the shape `specs/landing-grammar.spec.md` already
uses).

### E-BOARD-01 — an unsupported canonical remote refuses before any read

Setup: bare-remote, `origin` repointed at `file:///srv/git/agent-coordination.git`

```console
$ aco board --json
2> ERROR: no forge adapter for host file
{"ok": false, "reason": "unavailable", "message": "no forge adapter for host file"}
exit 2
```

### E-BOARD-20 — a canonical remote with no URL configured

Setup: bare-remote added as `origin` only, `.aco/board.toml` tracked naming `canonical_remote = "hub"`; the same holds when `hub` has only a URL-less line such as a local `remote.hub.fetch`, and `refs/remotes/hub/*` left behind

```console
$ aco board --json
2> ERROR: cannot determine the trunk: canonical remote 'hub' is not configured
{"ok": false, "reason": "unavailable", "message": "cannot determine the trunk: canonical remote 'hub' is not configured"}
exit 2
```

### E-BOARD-03 — a kindless container's own `--json` item carries `"container": null`

Setup: bare-remote, fake `gh`, issue `#20` open with `children_closed`/
`children_total` set on the forge but no recognized `kind`

```console
$ aco board --json
{"ok": true, "reason": "projected", "items": [{"number": 20, "kind": null, "container": null, ...}], ...}
exit 0
```

### E-BOARD-04 — `--json`'s top-level keys, no `repository`

Setup: bare-remote, fake `gh`, one open issue `#10`

```console
$ aco board --json
{"ok": true, "reason": "projected", "items": [...], "ready_now": [...], "stale": [], "recovery": [], "landings": [], "uncut": [], "requests": 3, "measurements": {"classes": [], "unfinished": 0, "unparsed": 0, "since": null, "as_of": "<date>"}}
exit 0
```

### E-BOARD-15 — `--json` refusal envelope, `--repo` under `storage = state-ref`

Setup: bare-remote, `storage = "state-ref"` tracked

```console
$ aco --repo acme/items board --json
2> ERROR: --repo is meaningless under storage = state-ref
{"ok": false, "reason": "invalid_usage", "message": "--repo is meaningless under storage = state-ref"}
exit 2
```

### E-BOARD-16 — `aco board` naming no `--json` refuses before any read

Setup: none -- a directory outside any git repository

```console
$ aco board
2> ERROR: aco board requires --json
exit 2
```
