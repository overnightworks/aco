# `aco check`

`aco check <n>`: one read that dispatches a bare number to one of three
answers, since GitHub gives issues and pull requests the same number space.
A pull request reads `specs/landing-grammar.spec.md`'s own classification,
closing, and parent grammar (LAND-04..LAND-28, LAND-70..LAND-77, LAND-79); this file cites those IDs
rather than restating them and owns only the command's own three-way
dispatch, its issue-mode read of an item's own body contract, and the
checkout it needs to run at all. `specs/output.spec.md` owns the `--json`
envelope itself (OUT-nn: key order, `ok`, `message`); this file names only
`check`'s own `reason` values. `specs/body-block.spec.md`
owns the exact `body malformed:`/`body incomplete:` sentences an issue's own
shape can carry (BODY-01..BODY-52); `specs/storage-pin.spec.md` owns the
`'<value>' is not an item reference` refusal for `<n>` itself (PIN-08), its
state-ref `<n> names no state-ref item` refusal past `aco-ffffff` (PIN-31), and
gates this command like any other resolving the item forge (PIN-04, PIN-05)
under `storage = "state-ref"`. `<n>` is the argument as given, an issue's
printed `#<n>` its `storage = "github"` form and the item id under
`storage = "state-ref"` (PIN-30), `<repository>` the checked repository's
own `owner/repo` path. A refusal that never even
reaches this command's own dispatch (no checkout, an absent or untracked
storage pin (PIN-01/PIN-32), an unreachable forge) prints `ERROR: <sentence>` on stderr and, with
`--json`, the envelope with `reason: "unavailable"`; exit `2` either way.
`aco check <sha>` (a trunk commit, not a bare number) is a fourth answer
this file owns like the other three: `specs/landing-grammar.spec.md` owns
the trailer grammar that mode reads and the sentences it refuses with
(LAND-03, LAND-48, LAND-57, LAND-58, LAND-60, LAND-68), this file its exits and its
`--json` envelope.
`aco check -` is a fifth, the one that reads no item at all: it checks a body
piped on stdin for defects before it reaches the forge, without ever reading a
live item. `specs/body-block.spec.md` owns every defect and `body ok`/`body
incomplete` sentence a checked block can carry (BODY-01..BODY-56) and this file
cites those IDs rather than restating them; `specs/storage-pin.spec.md` owns
the tracked-pin precondition it reads (PIN-01/PIN-32), and `[record]`'s own
storage-gated validity is `specs/body-block.spec.md`'s BODY-15/BODY-16. Its
`--json` envelope carries `defects` instead of a subject, and its `reason`
vocabulary is `valid`, `malformed`, `incomplete` and `unavailable`.

## Behavior table

| state \ trigger | `aco check <n>`, `<sha>` or `-` (text) | `aco check <n>`, `<sha>` or `-` with `--json` |
|---|---|---|
| `<n>` is a pull request | LAND-04..LAND-28, LAND-70..LAND-77, LAND-79 (cited) | CHECK-01 |
| `<n>` exists in neither number space | CHECK-02 | CHECK-03 |
| `<n>` is an issue, sound and unblocked | CHECK-04 | CHECK-05 |
| `<n>` is an issue, malformed body | CHECK-06 | CHECK-05 |
| `<n>` is an issue, incomplete body | CHECK-07 | CHECK-05 |
| `<n>` is an issue, blocked | CHECK-08, CHECK-09 | CHECK-05 |
| `<sha>` is a classified trunk commit | CHECK-12 | CHECK-14 |
| `<sha>` is a trunk commit the trailer grammar refuses | CHECK-13 | CHECK-14 |
| `<sha>` is off the walked first-parent trunk | CHECK-13 | CHECK-14 |
| `<sha>`, the canonical remote with no URL configured | CHECK-15 | CHECK-15 |
| no checkout, or another forge or store failure while reading | CHECK-10 | CHECK-10 |
| `--repo` given, `storage = "state-ref"`, `<n>` or `<sha>` | CHECK-11 | CHECK-11 |
| `-`, stdin is a valid, complete block | CHECK-17 (BODY-14) | CHECK-19 |
| `-`, stdin is malformed or incomplete | CHECK-18 (BODY-01..56) | CHECK-19 |
| `-`, stdin is not valid UTF-8 | CHECK-20 | CHECK-20 |
| `-`, `.aco/board.toml` absent, or present but untracked or ignored | CHECK-21 (PIN-32, PIN-01) | CHECK-21 |
| `-`, stdin is a socket, terminal, `/dev/null` or closed | CHECK-24 | CHECK-24 |
| `-`, outside a git checkout | CHECK-25 (CHECK-10) | CHECK-25 |
| `-`, `storage = "state-ref"` vs default `"github"` | CHECK-22 (BODY-15, BODY-16) | CHECK-22 |
| `-`, `--repo` given | CHECK-23 | CHECK-23 |
| `aco body`, the command this one replaced | CHECK-16 | CHECK-16 |

## `--json`'s own envelope

- [ ] [CHECK-01] `aco check <n> --json` against a pull request prints the envelope, `"kind": "pull_request", "number": <n>`, `reason`/`message` from the table below (see E-CHECK-01).
- [ ] [CHECK-05] `aco check <n> --json` against an issue prints the envelope, `"kind": "issue", "number": <n>`, `reason`/`message` below, `"blocked_by"` only with `reason: "blocked"` (see E-CHECK-05).
- [ ] [CHECK-19] `aco check - --json` prints the envelope, `reason` below and `"defects": [...]`, CHECK-18's ordered sentences, with no `kind`, `number` or `sha`; exit `0` on `valid`, else `2` (see E-CHECK-11).
- [ ] [CHECK-14] `aco check <sha> --json` prints the envelope, `"kind": "trunk_commit", "sha": "<sha>"`, `reason`/`message` below, never a `refused` key (see E-CHECK-08).

`reason`, by which outcome fired:

| outcome | `reason` | exit |
|---|---|---|
| pull request classified (LAND-04..LAND-28's own accepted case, LAND-79) | `valid` | `0` |
| pull request refused (LAND-04..LAND-28, LAND-70..LAND-77, LAND-79) | `invalid_classification` | `2` |
| `<n>` in neither number space (CHECK-02/03) | `missing` | `2` |
| issue valid, complete, unblocked (CHECK-04) | `valid` | `0` |
| issue malformed (CHECK-06) | `malformed` | `2` |
| issue structurally valid but unfilled (CHECK-07) | `incomplete` | `2` |
| issue with open `blocked_by` dependencies (CHECK-08) | `blocked` | `3` |
| trunk commit classified (CHECK-12) | `valid` | `0` |
| trunk trailer refused (CHECK-13) | `invalid_classification` | `2` |
| `<sha>` off the walked trunk (CHECK-13) | `not_on_trunk` | `2` |
| `<sha>`, the canonical remote with no URL configured (CHECK-15) | `unavailable` | `2` |
| no checkout, or another forge or store failure while reading (CHECK-10) | `unavailable` | `2` |
| `-`, stdin valid and complete (CHECK-17) | `valid` | `0` |
| `-`, stdin malformed (CHECK-18; BODY-01..56's own schema defect) | `malformed` | `2` |
| `-`, stdin structurally valid but unfilled (CHECK-18) | `incomplete` | `2` |
| `-`, stdin not UTF-8, the pin untrusted, stdin carries no body, or no checkout (CHECK-20, CHECK-21, CHECK-24, CHECK-25) | `unavailable` | `2` |
| `--repo` given, `storage = "state-ref"`, `<n>` or `<sha>` (CHECK-11) | `invalid_usage` | `2` |
| `<n>` past `aco-ffffff`, `storage = "state-ref"` (PIN-31) | `invalid_usage` | `2` |

## A number in neither space

- [ ] [CHECK-02] `<n>` matching no issue and no pull request prints `REFUSED: #<n> does not exist in <repository>` on stderr, exit `2`, naming no kind word (see E-CHECK-02).
- [ ] [CHECK-03] The same read with `--json` prints the envelope, `"reason": "missing", "kind": "missing", "number": <n>, "message": "does not exist in <repository>"`, exit `2`.

## Issue mode: a body's own contract

`<body defect sentence>` and `<sections>` are `specs/body-block.spec.md`'s
own text (BODY-01..BODY-50, BODY-12).

- [ ] [CHECK-04] `<n>` naming a valid, complete, unblocked issue prints `ISSUE #<n> body ok` on stdout, exit `0` (see E-CHECK-03).
- [ ] [CHECK-06] A malformed body prints `ISSUE #<n> <body defect sentence>` on stderr for its first defect, exit `2` (see E-CHECK-04).
- [ ] [CHECK-07] A structurally valid but unfilled body prints `ISSUE #<n> body incomplete: <sections>` on stderr, exit `2`.
- [ ] [CHECK-08] An issue with open `blocked_by` dependencies prints `ISSUE #<n> blocked by <label>, <label>` on stderr, exit `3`, local blockers first (see E-CHECK-05).
- [ ] [CHECK-09] Under `storage = "state-ref"`, a local blocker's own label is `specs/landing-grammar.spec.md`'s `<label>` (`aco-xxxxxx`); a foreign one stays `owner/repo#n` regardless of either pin.

## Trunk mode: a commit's own trailer

`<declaration>` and `<trunk defect sentence>` are
`specs/landing-grammar.spec.md`'s own text (LAND-48; LAND-03, LAND-57,
LAND-58, LAND-60, LAND-68).

- [ ] [CHECK-12] `<sha>` naming a trunk commit whose own trailer classifies prints `<sha> declares <declaration>` on stdout, exit `0` (see E-CHECK-08).
- [ ] [CHECK-13] A `<sha>` the trunk grammar refuses prints `REFUSED: <sha> <trunk defect sentence>` on stderr, exit `2`, and reads no forge at all (see E-CHECK-08).
- [ ] [CHECK-15] A canonical `<remote>` with no URL configured refuses `cannot determine the trunk: canonical remote '<remote>' is not configured`, exit `2`, never a local branch (see E-CHECK-09).

## No checkout, no read

`<no-checkout sentence>` is `this command reads the repository's body
contract from .aco/board.toml and needs a checkout (a shallow one
is enough): <git detail>`.

- [ ] [CHECK-10] `aco check <n>` outside a git checkout, or any other forge or store failure while reading, refuses `ERROR: <sentence>`, `--json` `reason: "unavailable"`, exit `2` (see E-CHECK-06).
- [ ] [CHECK-11] Under `storage = "state-ref"`, `--repo` with `<n>` or `<sha>` refuses the same sentence as `specs/storage-pin.spec.md`'s PIN-04, `--json` `reason: "invalid_usage"`, exit `2` (see E-CHECK-07).

## A body from stdin

Every sentence below is `specs/body-block.spec.md`'s own text; this file
owns only the CLI-level framing around it.

- [ ] [CHECK-16] `aco body` is an unknown command: the parser itself refuses it with the ordinary usage error, exit `2`, before anything runs; no alias of it exists (see E-CHECK-12).
- [ ] [CHECK-17] `aco check -` reading a valid, complete block from stdin prints and exits exactly as BODY-14 describes (see E-CHECK-10).
- [ ] [CHECK-18] `aco check -` prints every defect sentence on stderr, one per line, never truncated like `aco check <n>` (CHECK-06, CHECK-07); exit `2` (see E-CHECK-10).
- [ ] [CHECK-20] Stdin that is not valid UTF-8 refuses `stdin is not valid UTF-8: <reason>; pipe the body as UTF-8 text`, `--json` `reason: "unavailable"`, exit `2`, before any parse is attempted.
- [ ] [CHECK-21] `aco check -` refuses PIN-32's sentence on an absent `.aco/board.toml`, PIN-01's on a present but untracked or ignored one, `--json` `reason: "unavailable"`, before stdin is ever read.
- [ ] [CHECK-22] `aco check -` reads the storage pin for `[record]`'s validity: unknown under default `storage = "github"` (BODY-15), field-checked under `storage = "state-ref"` (BODY-16).
- [ ] [CHECK-23] `aco check -` never reads the global `--repo`: it neither uses nor refuses it, under either storage.
- [ ] [CHECK-24] A socket, terminal, `/dev/null` or closed stdin refuses `check - needs the body on stdin: aco check - < body.md`, `--json` `reason: "unavailable"`, exit `2`, unread, after CHECK-21's refusal.

  ```console
  $ aco check - < /dev/null
  2> ERROR: check - needs the body on stdin: aco check - < body.md
  exit 2
  ```
- [ ] [CHECK-25] `aco check -` outside a git checkout refuses CHECK-10's sentence, `--json` `reason: "unavailable"`, exit `2`, before stdin is read; the storage pin (CHECK-22) is the one repository fact it needs.

  ```console
  $ cd /tmp && printf 'x' | aco check -
  2> ERROR: this command reads the repository's body contract from .aco/board.toml and needs a checkout (a shallow one is enough): <git detail>
  exit 2
  ```

## Never

- `aco check -` never resolves a forge, fetches the state ref, or shells out to `gh`: its only input is stdin, and its only repository read is the storage pin CHECK-21/CHECK-22 name.
- `aco check -` never reads a file path, a live issue, or a dependency: a body is always piped in, never named by number (`specs/body-block.spec.md`'s own Never line).
- `aco check` never writes: no mode ever changes an item's body, and the pull-request mode's own claims read is a pure fetch of the already-observed state ref.
- The issue mode of `check` never fetches the state ref: only the pull-request mode reads the live claims LAND-15/LAND-16 need.
- Under `storage = "state-ref"`, `check <n>` never reaches the pull-request path: no number under that storage is ever reported as a landing, so every `<n>` resolves to ISSUE or MISSING.
- `check -` outcomes follow the same exit rule: `valid` is exit `0`; `malformed`, `incomplete`, and `unavailable` are all exit `2`.
- `check` never names its subject any other way than as `specs/landing-grammar.spec.md`'s `<label>` in every number mode and as the `<sha>` it was asked about in the trunk mode (CHECK-12, CHECK-13).
- `blocked` (CHECK-08) is the only outcome that exits `3`; every other refusal exits `2` (see the `reason`/exit table above), and no outcome exits `1` any more.
- The trunk mode never reads a forge: a commit's own trailer is local history, so `check <sha>` answers from the walked trunk alone.
- No mode of `check` ever prints a `refused` key: `specs/output.spec.md`'s envelope names every refusal by `reason` and `message` instead.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local
bare repository with `main` at one commit, a git identity, `origin/HEAD`,
and `ACO_AGENT` set to `Ada`; `<owner>/<repo>` is the runner's own
repository path. Every session that reaches this command's own dispatch
also needs `.aco/board.toml` present and tracked (PIN-01/PIN-32), since that read
comes before pull-request or issue mode ever run; the checkout-less
session (E-CHECK-06) is the one exception, since it never reaches the
dispatch at all. A session reading a pull request or an issue also names a
fixed, deterministic fake `gh` as a setup precondition (the shape
`specs/landing-grammar.spec.md` already uses); the checkout-less session
needs neither a fake `gh` nor a checkout at all.

### E-CHECK-01 — `--json` on an accepted and a refused pull request

The text form's own literal is LAND-04's own fact, already driven by
`specs/landing-grammar.spec.md`'s own E-LAND-02; this session drives only
CHECK-01, this file's own `reason` values inside `specs/output.spec.md`'s
envelope.

Setup: bare-remote, `.aco/board.toml` tracked, fake `gh`, pull request `#57` by `Ada`, body `Work-Item: #42\n\nCloses #42`, an active claim on issue `#42` matching its head branch

```console
$ aco check 57 --json
{"ok": true, "reason": "valid", "kind": "pull_request", "number": 57}
exit 0
```

Setup: bare-remote, `.aco/board.toml` tracked, fake `gh`, pull request `#57` by `Ada`, body `Tidy the README.` (no classification line)

```console
$ aco check 57 --json
{"ok": false, "reason": "invalid_classification", "kind": "pull_request", "number": 57, "message": "carries no `Work-Item:` or `No-Item:` line"}
exit 2
```

### E-CHECK-02 — a number in neither space

Setup: bare-remote, `.aco/board.toml` tracked, fake `gh`, no issue or pull request `#81` exists in this repository

```console
$ aco check 81
2> REFUSED: #81 does not exist in <owner>/<repo>
exit 2
$ aco check 81 --json
{"ok": false, "reason": "missing", "kind": "missing", "number": 81, "message": "does not exist in <owner>/<repo>"}
exit 2
```

### E-CHECK-03 — a sound, unblocked issue

Setup: bare-remote, `.aco/board.toml` tracked, fake `gh`, issue `#81` open, body a complete `aco` block, no open `blocked_by` dependencies

```console
$ aco check 81
ISSUE #81 body ok
exit 0
```

### E-CHECK-04 — a malformed issue body

The defect text itself is BODY-01's own fact; this session drives only
CHECK-06, this file's own `ISSUE #<n> ` wrapping around it.

Setup: bare-remote, `.aco/board.toml` tracked, fake `gh`, issue `#81` open, BODY-01's own defect (no `aco` fence)

```console
$ aco check 81
2> ISSUE #81 body malformed: aco: no aco block
exit 2
```

### E-CHECK-05 — an issue blocked by a local and a foreign item

Setup: bare-remote, `.aco/board.toml` tracked, fake `gh`, issue `#81` open with a complete body, open `blocked_by` dependencies on `#7` (same repository) and `other/repo#9`

```console
$ aco check 81
2> ISSUE #81 blocked by #7, other/repo#9
exit 3
$ aco check 81 --json
{"ok": false, "reason": "blocked", "kind": "issue", "number": 81, "blocked_by": ["#7", "other/repo#9"], "message": "blocked by #7, other/repo#9"}
exit 3
```

### E-CHECK-06 — no checkout, no read

Setup: a fresh repository outside any git checkout

```console
$ aco check 12
2> ERROR: this command reads the repository's body contract from .aco/board.toml and needs a checkout (a shallow one is enough): fatal: not a git repository (or any of the parent directories): .git
exit 2
```

### E-CHECK-07 — `--repo` under `storage = "state-ref"`

Setup: bare-remote, `.aco/board.toml` tracked with `storage = "state-ref"`

```console
$ aco --repo acme/items check 258 --json
2> ERROR: --repo is meaningless under storage = state-ref
{"ok": false, "reason": "invalid_usage", "message": "--repo is meaningless under storage = state-ref"}
exit 2
```

### E-CHECK-08 — a trunk commit, classified and refused

Setup: bare-remote, `.aco/board.toml` tracked, the trunk's newest commit carrying the trailer `No-Item: docs`, `<sha>` its own commit id

```console
$ aco check <sha>
<sha> declares No-Item: docs
exit 0
$ aco check <sha> --json
{"ok": true, "reason": "valid", "kind": "trunk_commit", "sha": "<sha>"}
exit 0
```

Setup: bare-remote, `.aco/board.toml` tracked, `<sha>` a commit id the first-parent trunk walk does not hold

```console
$ aco check <sha>
2> REFUSED: <sha> is not on the first-parent trunk
exit 2
$ aco check <sha> --json
{"ok": false, "reason": "not_on_trunk", "kind": "trunk_commit", "sha": "<sha>", "message": "is not on the first-parent trunk"}
exit 2
```

### E-CHECK-09 — a canonical remote with no URL configured

Setup: bare-remote added as `origin` only, `.aco/board.toml` tracked naming `canonical_remote = "hub"`, `<sha>` an unpushed local commit carrying `No-Item: docs`; the same holds when `hub` has only a URL-less line such as a global `prune = true`, and `refs/remotes/hub/*` left behind

```console
$ aco check <sha>
2> ERROR: cannot determine the trunk: canonical remote 'hub' is not configured
exit 2
$ aco check <sha> --json
2> ERROR: cannot determine the trunk: canonical remote 'hub' is not configured
{"ok": false, "reason": "unavailable", "message": "cannot determine the trunk: canonical remote 'hub' is not configured"}
exit 2
```

Setup: as above, but `hub` added as a remote that carries no branch yet

```console
$ aco check <sha>
<sha> declares No-Item: docs
exit 0
```

### E-CHECK-10 — `-`, ok and malformed

Setup: bare-remote, `.aco/board.toml` tracked naming no `storage` key

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Cut on 19.09.2026."
next = "Build it."
done_when = "It is built."
```
BODY
body ok
exit 0
$ aco check - <<'BODY'
```aco
version = 1
next = "X"
```
BODY
2> body malformed: now: now is required
2> body malformed: done_when: done_when is required
exit 2
````

### E-CHECK-11 — `-` with `--json`, and its `malformed`/`incomplete` reasons

Setup: bare-remote, `.aco/board.toml` tracked naming no `storage` key

````console
$ aco check - --json <<'BODY'
```aco
version = 1
now = "Cut on 19.09.2026."
next = "Build it."
done_when = "It is built."
```
BODY
{"ok": true, "reason": "valid", "defects": []}
exit 0
$ aco check - --json <<'BODY'
no block
BODY
{"ok": false, "reason": "malformed", "defects": ["body malformed: aco: no aco block"]}
exit 2
$ aco check - --json <<'BODY'
```aco
version = 1
now = ""
next = ""
done_when = ""
```
BODY
{"ok": false, "reason": "incomplete", "defects": ["body incomplete: Now, Next, Done when"]}
exit 2
````

### E-CHECK-12 — `aco body` is an unknown command

Setup: bare-remote

```console
$ aco body
2> usage: aco [-h] [--version] [--repo REPO]
2>            {bootstrap,reset,status,board,serve,rulings,next,start,claim,release,land,adopt,rescope,cut,ask,rule,check,brief,item}
2>            ...
2> aco: error: argument command: invalid choice: 'body' (choose from bootstrap, reset, status, board, serve, rulings, next, start, claim, release, land, adopt, rescope, cut, ask, rule, check, brief, item)
exit 2
```
