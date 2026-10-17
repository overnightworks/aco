# `aco adopt`

`aco adopt <n> --no-item <kind> [--whole REASON] [--agent NAME]` is the command that
will make an open pull request a lane: it checks that pull request `<n>`, which someone
else opened (a dependency bot, a fixer), can declare `No-Item: <kind>` (`deps`, `fix` or
`docs`) and be claimed on its own head branch. This file owns the checks it makes before
anything is written, their order, and their refusals. It never restates the landing grammar
(`specs/landing-grammar.spec.md`), `aco claim`'s checks (`specs/claim.spec.md`,
`specs/claim-record.spec.md`) or START-24's main-checkout rule (`specs/start.spec.md`): it
cites their IDs. This aco builds no adoption yet: a pull request that passes every check is
refused too (ADOPT-18), so no run of `aco adopt` writes a worktree, a branch, a claim or a
body. A refusal prints `ERROR: <sentence>` on stderr, exit `2`, as
`specs/ref-store-cas.spec.md`'s preamble documents; `aco adopt` has no `--json` mode.
`<n>` is the positive pull request number, `<kind>` the `--no-item` value, `<branch>` its head
branch. `<repo>` is the pull request's `OWNER/REPO` path in ADOPT-03 and the main checkout's
directory in ADOPT-09.

## Behavior table

| state \ trigger | `aco adopt <n> --no-item <kind>` |
|---|---|
| `storage = "state-ref"` | ADOPT-01 |
| the pull request is not open | ADOPT-02 |
| the head branch lives in another repository | ADOPT-03 |
| the pull request targets another branch than the default | ADOPT-04 |
| the body already carries a classification line | ADOPT-05 |
| a live claim stands on the head branch | ADOPT-06 |
| the body or the file listing breaks the landing grammar | ADOPT-07 |
| the file listing names no file | ADOPT-16 |
| `--no-item` is not `deps`, `fix` or `docs`, or is missing | ADOPT-08 |
| the body would not read `No-Item: <kind>` with the line added | ADOPT-11 |
| the composed body | ADOPT-12 |
| the head branch name is unsafe | ADOPT-17 |
| a path stands at the lane's worktree path | ADOPT-09 |
| a local branch has the head branch's name | ADOPT-13 |
| the remote's head branch moved or is gone | ADOPT-10 |
| the claim's scope is too wide or too long | ADOPT-14 |
| run from a linked worktree whose git directory names no checkout | ADOPT-15 |
| every check passes | ADOPT-18 |
| a refusal sentence is long or carries display controls | ADOPT-19 |

## Checks, in order

The first failing step wins; each reads only what it needs, so a refusal early in the
list reads nothing after it.

1. `--no-item` is one of `deps`, `fix` or `docs`, and one positive pull request number is given (ADOPT-08; the Never line on one pull request per call).
2. The main checkout is resolved (ADOPT-15), then its storage pin is read (ADOPT-01); a linked
   worktree's own copy of `.aco/board.toml` is never read.
3. The pull request and its item reference are read; the pull request is open (ADOPT-02) and its
   head branch is of this repository (ADOPT-03).
4. The claim state is read once; no claim stands on the head branch (ADOPT-06). Steps 1 to 3 read
   no claim state.
5. The body carries no classification line (ADOPT-05); with the line added it reads
   `No-Item: <kind>` (ADOPT-11, ADOPT-12), the pull request targets the default branch (ADOPT-04),
   and it closes no item (ADOPT-07, LAND-17).
6. For `deps`, the configuration names `dependency_paths` (ADOPT-07, LAND-70). The file listing
   is read once, at the head the first read named, and is complete and consistent (ADOPT-07,
   LAND-73, LAND-75, LAND-76), names a file (ADOPT-16), and for `deps` every path is covered
   (ADOPT-07, LAND-71).
7. The head branch name is safe (ADOPT-17); nothing stands at `<repo>-worktrees/pr-<n>` (ADOPT-09);
   no local branch has its name (ADOPT-13); the remote still has the head branch, and its fetched tip
   is the head the checks read (ADOPT-10).
8. The claim `adopt` would make passes `claim`'s check phase for the listing's path set
   (ADOPT-14).
9. Every check passed (ADOPT-18).

## Refusals before any write

- [ ] [ADOPT-01] Under `storage = "state-ref"` it refuses `aco adopt is a github command; storage = state-ref has no pull requests to adopt`, exit `2`, before any forge read.
- [ ] [ADOPT-02] A pull request that is not open, closed or merged alike, refuses `pull request #<n> is not open; it cannot be adopted`, exit `2`.
- [ ] [ADOPT-03] A head branch of another repository refuses `pull request #<n> proposes a branch of <repo>; cross-repository pull requests are not classified` (LAND-12), exit `2`.
- [ ] [ADOPT-04] A pull request not targeting the default branch refuses `pull request #<n> targets '<branch>', not the default branch '<default>'` (LAND-13), exit `2`.
- [ ] [ADOPT-05] A live classification line, valid or malformed, refuses `pull request #<n> already carries <line>; adopt never changes a classification line`, exit `2`.
- [ ] [ADOPT-06] A live claim on the head branch, issue or lane, refuses `lane '<branch>' is claimed by <agent> (<role>) on <subject> branch <branch>`, exit `2`.
- [ ] [ADOPT-07] LAND-17 and LAND-73..76 apply to every kind, LAND-70..71 to `deps`, on the body adopt would write and at the head its first read named: a defect refuses `pull request #<n> <sentence>`, exit `2`.
- [ ] [ADOPT-08] A `--no-item` other than `deps`, `fix` or `docs`, or none, or an `<n>` that is no positive integer, is a parser refusal: argparse's usage block and sentence on stderr, exit `2` (OUT's parser shape).
- [ ] [ADOPT-09] With no claim on the branch, a path at `<repo>-worktrees/pr-<n>` refuses `<path> already exists; remove it, then adopt pull request #<n> again`, exit `2`.
- [ ] [ADOPT-10] A fetched head tip other than the pull request's head, or a head branch the remote no longer has, refuses `pull request #<n> moved while adopt read it; run adopt again`, exit `2`.
- [ ] [ADOPT-11] A body that would not read `No-Item: <kind>` once the line is added refuses `pull request #<n> body would not read No-Item: <kind> with the line added: <defect>`, exit `2`.
- [ ] [ADOPT-12] The written body is the body last read, byte for byte, then a newline or blank line as needed, then `No-Item: <kind>`; title, labels, base, branch and commits never change.
- [ ] [ADOPT-13] With no claim on the branch, a local branch `<branch>` refuses `branch '<branch>' already exists here; remove it, then adopt pull request #<n> again`, exit `2`.
- [ ] [ADOPT-14] The claim scope is the listing's path set (LAND-74); `--whole REASON` reaches CLM-18's width gate, and an overlap is CLAIM-31's note, never a refusal.
- [ ] [ADOPT-15] Run in a linked worktree whose git directory names no checkout, it refuses START-24's sentence ending `run adopt from the main checkout`, exit `2`.
- [ ] [ADOPT-16] A pull request whose listing names no file refuses `pull request #<n> changes no file; there is nothing to adopt`, exit `2`.
- [ ] [ADOPT-17] A head branch name the claim store refuses as unsafe refuses `pull request #<n> head branch '<branch>' is no safe branch name`, exit `2`, before any write.
- [ ] [ADOPT-18] When every check passes, adopt refuses `pull request #<n> passes every adoption check; this aco does not build adoptions yet`, exit `2`: no worktree or branch, no claim transition, no body write.
- [ ] [ADOPT-19] Every refusal is one line of at most 200 characters with `ERROR: `, foreign text (agent names, paths) shown with display controls escaped, a longer sentence cut to end in `…`.

## Never

- A refusal before the build never creates a worktree or branch, makes a claim transition or writes a body. Its fetches may still move local bookkeeping: the state ref's local anchor and lineage stamp, and `refs/remotes/<remote>/<branch>` of the head branch and the default branch, never a local branch.
- `aco adopt` never reads an author list: a bot's pull request and a person's are judged alike, by their body, branch, claims and file listing.
- `aco adopt` never adopts more than one pull request per call.
- `aco adopt` never reads a linked worktree's own `.aco/board.toml`: every check judges the main checkout's.
- `aco adopt` never gains a `--json` mode (`specs/output.spec.md`): a refusal is `ERROR: <sentence>` on stderr and the parser's own usage block, exit `2`.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local bare repository with
`main` at one commit, a git identity, `origin/HEAD`, and `ACO_AGENT` set to `Ada`, with a
`github` storage pin and a fixed, deterministic fake `gh`.

### E-ADOPT-05 -- a pull request that already declares a work item refuses

Setup: bare-remote, bootstrapped, fake `gh`, pull request `#45` open from `dependabot/uv/x` with `Work-Item: #5` in its body

```console
$ aco adopt 45 --no-item deps
2> ERROR: pull request #45 already carries Work-Item: #5; adopt never changes a classification line
exit 2
```

### E-ADOPT-18 -- a pull request passing every check is still refused

Setup: bare-remote, bootstrapped, fake `gh`, pull request `#45` open from `dependabot/uv/x`, its tip fetched, listing `uv.lock` and `pyproject.toml`, both named by `dependency_paths`

```console
$ aco adopt 45 --no-item deps
2> ERROR: pull request #45 passes every adoption check; this aco does not build adoptions yet
exit 2
```
