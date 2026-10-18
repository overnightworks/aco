# `aco adopt`

`aco adopt <n> --no-item <kind> [--whole REASON] [--agent NAME]` makes an open pull request a
lane: it checks that pull request `<n>`, which someone else opened (a dependency bot, a fixer),
can declare `No-Item: <kind>` (`deps`, `fix` or `docs`) and be claimed on its own head branch,
builds its worktree, claims it exclusively and appends the line to its body. This file owns the
checks it makes before anything is written, their order, the writes and their recovery. It never
restates the landing grammar (`specs/landing-grammar.spec.md`), `aco claim`'s checks
(`specs/claim.spec.md`, `specs/claim-record.spec.md`) or START-24's main-checkout rule
(`specs/start.spec.md`): it cites their IDs. A refusal prints `ERROR: <sentence>` on stderr, exit
`2`, as `specs/ref-store-cas.spec.md`'s preamble documents; `aco adopt` has no `--json` mode.
`<n>` is the positive pull request number, `<kind>` the `--no-item` value, `<branch>` its head
branch. `<repo>` is the pull request's `OWNER/REPO` path in ADOPT-03 and the main checkout's
directory in ADOPT-09.

## Behavior table

| state \ trigger | `aco adopt <n> --no-item <kind>` |
|---|---|
| no agent identity resolves, or it is no bounded line | OUT-05 |
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
| the remote's or the built head branch moved or is gone | ADOPT-10 |
| the claim's scope is too wide or too long | ADOPT-14 |
| run from a linked worktree whose git directory names no checkout | ADOPT-15 |
| every check passes | ADOPT-20 |
| the claim is refused after the build | ADOPT-21 |
| the claim's push has an unknown outcome | ADOPT-22 |
| the body changed before it is written | ADOPT-23 |
| the forge refuses the body write | ADOPT-24 |
| the body write has an unknown outcome | ADOPT-25 |
| this session's builder lane claim stands alone on the branch | ADOPT-26, ADOPT-31 |
| the body reads back unlike the body written | ADOPT-27 |
| the body cannot be read back | ADOPT-28 |
| the body cannot be read before it is written | ADOPT-33 |
| a claim lands on the branch after the checks | ADOPT-29 |
| the rerun's body carries more than one classification line | ADOPT-30 |
| another role's claim, or a second claim, stands on the branch | ADOPT-32 |
| a refusal sentence is long or carries display controls | ADOPT-19 |
| the adopted branch is re-pushed | ADOPT-34 |
| an adopted lane is released as abandoned | ADOPT-35 |

## Checks, in order

The first failing step wins; each reads only what it needs, so a refusal early in the
list reads nothing after it.

1. `--no-item` is one of `deps`, `fix` or `docs`, and one positive pull request number is given (ADOPT-08; the Never line on one pull request per call).
2. The agent identity is resolved from `--agent` or the environment, by the command dispatcher
   before the command starts (OUT-05), so before the main checkout, the storage pin and any
   forge read: none refuses `agent identity is required: pass --agent or set ACO_AGENT,
   GROK_SESSION_ID, or CLAUDE_CODE_SESSION_ID`, and one that is not a bounded non-empty line
   refuses `agent must be one bounded non-empty line`.
3. The main checkout is resolved (ADOPT-15), then its storage pin is read (ADOPT-01); a linked
   worktree's own copy of `.aco/board.toml` is never read.
4. The pull request and its item reference are read; the pull request is open (ADOPT-02) and its
   head branch is of this repository (ADOPT-03).
5. The claim state is read once; no claim but this session's own builder lane claim stands on the
   head branch (ADOPT-06, ADOPT-32). That claim, alone there, makes the run a resume (ADOPT-26). Steps
   1 to 4 read no claim state.
6. The body carries no classification line, except the resume's own (ADOPT-05, ADOPT-30); with the
   line added it reads `No-Item: <kind>` (ADOPT-11, ADOPT-12), the pull request targets the default
   branch (ADOPT-04), and it closes no item (ADOPT-07, LAND-17).
7. For `deps`, the configuration names `dependency_paths` (ADOPT-07, LAND-70). The file listing
   is read once, at the head the first read named, and is complete and consistent (ADOPT-07,
   LAND-73, LAND-75, LAND-76), names a file (ADOPT-16), and for `deps` every path is covered
   (ADOPT-07, LAND-71). A resume ends its checks here (ADOPT-31): it never builds, fetches,
   rescopes or runs steps 8 and 9.
8. The head branch name is safe (ADOPT-17); nothing stands at `<repo>-worktrees/pr-<n>` (ADOPT-09);
   no local branch has its name (ADOPT-13); the remote still has the head branch, and its fetched tip
   is the head the checks read (ADOPT-10).
9. The claim `adopt` would make passes `claim`'s check phase for the listing's path set
   (ADOPT-14), where it is exclusive on its branch (CLAIM-71).
10. The worktree is built on the head branch from the fetched tip, and its HEAD is the head
   the checks read (ADOPT-10); the claim is written for the listing's path set (ADOPT-21,
   ADOPT-22, ADOPT-29).
11. The body is read again (ADOPT-33) and judged once more on that copy (ADOPT-23), written (ADOPT-24,
   ADOPT-25), read back (ADOPT-27, ADOPT-28), and the declaration printed (ADOPT-20).

## Checks, refusals and writes

- [ ] [ADOPT-01] Under `storage = "state-ref"` it refuses `aco adopt is a github command; storage = state-ref has no pull requests to adopt`, exit `2`, before any forge read.
- [ ] [ADOPT-02] A pull request that is not open, closed or merged alike, refuses `pull request #<n> is not open; it cannot be adopted`, exit `2`.
- [ ] [ADOPT-03] A head branch of another repository refuses `pull request #<n> proposes a branch of <repo>; cross-repository pull requests are not classified` (LAND-12), exit `2`.
- [ ] [ADOPT-04] A pull request not targeting the default branch refuses `pull request #<n> targets '<branch>', not the default branch '<default>'` (LAND-13), exit `2`.
- [ ] [ADOPT-05] A live classification line, valid or malformed, refuses `pull request #<n> already carries <line>; adopt never changes a classification line`, exit `2`, unless it is the line ADOPT-26 keeps.
- [ ] [ADOPT-06] A live claim on the head branch, issue or lane, refuses `lane '<branch>' is claimed by <agent> (<role>) on <subject> branch <branch>`, exit `2`, unless ADOPT-26 resumes.
- [ ] [ADOPT-07] LAND-17 and LAND-73..76 apply to every kind, LAND-70..71 to `deps`, on the body adopt would write and at the head its first read named: a defect refuses `pull request #<n> <sentence>`, exit `2`.
- [ ] [ADOPT-08] A `--no-item` other than `deps`, `fix` or `docs`, or none, or an `<n>` that is no positive integer, is a parser refusal: argparse's usage block and sentence on stderr, exit `2` (OUT's parser shape).
- [ ] [ADOPT-09] With no claim on the branch, a path at `<repo>-worktrees/pr-<n>` refuses `<path> already exists; remove it, then adopt pull request #<n> again`, exit `2`.
- [ ] [ADOPT-10] A fetched or built head other than the pull request's head, or a head branch the remote no longer has, refuses `pull request #<n> moved while adopt read it; run adopt again`, exit `2`.
- [ ] [ADOPT-11] A body that would not read `No-Item: <kind>` once the line is added refuses `pull request #<n> body would not read No-Item: <kind> with the line added: <defect>`, exit `2`.
- [ ] [ADOPT-12] The written body is the body last read, byte for byte, then a newline or blank line as needed, then `No-Item: <kind>`; title, labels, base, branch and commits never change.
- [ ] [ADOPT-13] With no claim on the branch, a local branch `<branch>` refuses `branch '<branch>' already exists here; remove it, then adopt pull request #<n> again`, exit `2`.
- [ ] [ADOPT-14] The claim scope is the listing's path set (LAND-74); `--whole REASON` reaches CLM-18's width gate, and an overlap is CLAIM-31's note, never a refusal.
- [ ] [ADOPT-15] Run in a linked worktree whose git directory names no checkout, it refuses START-24's sentence ending `run adopt from the main checkout`, exit `2`.
- [ ] [ADOPT-16] A pull request whose listing names no file refuses `pull request #<n> changes no file; there is nothing to adopt`, exit `2`.
- [ ] [ADOPT-17] A head branch name the claim store refuses as unsafe refuses `pull request #<n> head branch '<branch>' is no safe branch name`, exit `2`, before any write.
- [ ] [ADOPT-19] Every refusal from adopt's own checks is one line of at most 200 characters with `ERROR: `, foreign text (agent names, paths) shown with display controls escaped, a longer one cut to end in `…`.
- ADOPT-18 (retired 18.10.2026, issue #173): "passes every adoption check; this aco does not build adoptions yet" no longer exists; a pull request that passes every check is adopted (ADOPT-20).
- [ ] [ADOPT-20] `aco adopt <n> --no-item <kind>` on an open same-repository pull request nobody claims prints E-ADOPT-01's lines, exit `0`; the lane claim names this session's agent as builder.
- [ ] [ADOPT-21] A claim refused after the build drops both: `removed worktree <path> and branch '<branch>' this adopt created`, exit `2`; START-21 and START-23 hold with `adopt`.
- [ ] [ADOPT-22] A claim push of unknown outcome keeps both: `the claim's push was sent, its outcome unknown; worktree <path> and branch '<branch>' kept; run adopt again to resume it`, exit `2`.
- [ ] [ADOPT-23] Right before writing, adopt reads the body again and composes from that copy; ADOPT-05, ADOPT-07 or ADOPT-11 then refuses with the claim kept, exit `2`.
- [ ] [ADOPT-24] A body write the forge refused prints `pull request #<n> body not written (<error>); the claim stands; run adopt again, or release it`, exit `2`.
- [ ] [ADOPT-25] A body write of unknown outcome prints `pull request #<n> body write sent, outcome unknown (<error>); the claim stands; run adopt again`, exit `2`.
- [ ] [ADOPT-26] A rerun by this session's agent as builder, holding the branch's live lane claim with no other claim there, builds and claims nothing: it adds a missing line or keeps a present one, exit `0`.
- [ ] [ADOPT-27] A body read back unlike the body written prints `pull request #<n> body changed after adopt wrote it; the claim stands; run adopt again`, exit `2`.
- [ ] [ADOPT-28] A failed read-back prints `pull request #<n> body written, but reading it back failed (<error>); the claim stands; run adopt again`, exit `2`.
- [ ] [ADOPT-29] ADOPT-06 holds at the claim write itself (CLAIM-71): a claim landing on the branch after adopt's checks refuses it there, then ADOPT-21 drops the build; the body stays unwritten.
- [ ] [ADOPT-30] On ADOPT-26's rerun a body with more than one live classification line refuses `pull request #<n> <the parser's defect>; adopt never changes a classification line`, exit `2`.
- [ ] [ADOPT-31] ADOPT-26's rerun judges ADOPT-02..07 and ADOPT-16 again on the body it would leave, at the head it read; it never builds, fetches, rescopes or checks ADOPT-09, ADOPT-10, ADOPT-13 or ADOPT-17.
- [ ] [ADOPT-32] A same-agent lane claim under another role, or any claim beside the holder's on the branch, is no such rerun: ADOPT-06 refuses, naming that claim, and nothing is written.
- [ ] [ADOPT-33] A failed re-read before the write prints `pull request #<n> body could not be read before writing (<error>); the claim stands; run adopt again`, exit `2`.
- [ ] [ADOPT-34] A re-push of an adopted branch ends no claim: `aco land --head` demands the new head (LANDCMD-31) and releases the lane like any lane (REL-57); the holder's rerun restores a lost line (ADOPT-26).
- [ ] [ADOPT-35] `aco release --branch <branch> --abandoned` frees an adopted lane and keeps worktree, branch and `No-Item:` line (REL-33); then `aco land` refuses (LAND-16) and `aco adopt` refuses (ADOPT-05).

## Never

- A refusal before the build never creates a worktree or branch, makes a claim transition or writes a body. Its fetches may still move local bookkeeping: the state ref's local anchor and lineage stamp, and `refs/remotes/<remote>/<branch>` of the head branch and the default branch, never a local branch.
- `aco adopt` never pushes to the pull request's branch, and never touches the pull request's title, labels, base, branch or commits. This keeps the pull request's code; it does not certify the code safe.
- `aco adopt` never reads an author list: a bot's pull request and a person's are judged alike, by their body, branch, claims and file listing.
- `aco adopt` never changes a line of the body it last read; it only appends one.
- `aco adopt` never takes a claim another holder or an issue holds, and never resumes a claim under another role or beside another holder (ADOPT-32).
- `aco adopt` never rescopes, rebuilds or fetches again on a resume (ADOPT-31).
- `aco adopt` never adopts more than one pull request per call.
- `aco adopt` never reads a linked worktree's own `.aco/board.toml`: every check judges the main checkout's.
- `aco adopt` never gains a `--json` mode (`specs/output.spec.md`): a refusal is `ERROR: <sentence>` on stderr and the parser's own usage block, exit `2`.
- Accepted residuals: GitHub's body write has no compare-and-swap, so an edit landing between ADOPT-23's read and the write can be lost, and ADOPT-27 sees edits after the write only. After a re-push the local branch stays at the old head until the adopter updates the worktree (ADOPT-34). After an abandonment (`aco release --abandoned`) the line stays, so ADOPT-05 refuses re-adoption until it is removed by hand (ADOPT-35). An ordinary issue claim may still land on an adopted branch (CLAIM-10); the holder's rerun then refuses ADOPT-06 until one claim is released. A force-push back to the exact head adopt first read, while it lists the files, is not detected.

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

### E-ADOPT-01 -- a pull request nobody claims is adopted

Setup: bare-remote, bootstrapped, fake `gh`, pull request `#45` open from `dependabot/uv/x` with the body `Bump x`, its tip on the remote, listing `uv.lock` and `pyproject.toml`, both named by `dependency_paths`, issue `#9` claiming `pyproject.toml` on another branch

```console
$ aco adopt 45 --no-item deps
worktree: /work/agent-coordination-worktrees/pr-45
branch: dependabot/uv/x
CLAIMED lane dependabot/uv/x: <claim-id>
2 of 6 versioned files (33%); overlaps issue #9 on pyproject.toml
PR #45 by app/dependabot declares No-Item: deps
exit 0
```

### E-ADOPT-02 -- the holder's rerun completes an interrupted adoption

Setup: E-ADOPT-01 after the body write failed, so the claim stands and the body lacks the line

```console
$ aco adopt 45 --no-item deps
CLAIMED lane dependabot/uv/x: <claim-id>
PR #45 by app/dependabot declares No-Item: deps
exit 0
```

### E-ADOPT-21 -- a claim refused after the build removes the pair

Setup: E-ADOPT-01 with issue `#42` claiming `dependabot/uv/x` after adopt's checks

```console
$ aco adopt 45 --no-item deps
worktree: /work/agent-coordination-worktrees/pr-45
branch: dependabot/uv/x
2> ERROR: lane 'dependabot/uv/x' is claimed by Bob (builder) on issue #42 branch dependabot/uv/x
2> removed worktree /work/agent-coordination-worktrees/pr-45 and branch 'dependabot/uv/x' this adopt created
exit 2
```

### E-ADOPT-24 -- the forge refuses the body write

Setup: E-ADOPT-01 with the forge answering HTTP 403 to the body write

```console
$ aco adopt 45 --no-item deps
worktree: /work/agent-coordination-worktrees/pr-45
branch: dependabot/uv/x
CLAIMED lane dependabot/uv/x: <claim-id>
2 of 6 versioned files (33%); overlaps no other open claims
2> ERROR: pull request #45 body not written (HTTP 403); the claim stands; run adopt again, or release it
exit 2
```

### E-ADOPT-27 -- a body read back unlike the one written

Setup: E-ADOPT-01 with the bot rewriting the body before adopt reads it back

```console
$ aco adopt 45 --no-item deps
worktree: /work/agent-coordination-worktrees/pr-45
branch: dependabot/uv/x
CLAIMED lane dependabot/uv/x: <claim-id>
2 of 6 versioned files (33%); overlaps no other open claims
2> ERROR: pull request #45 body changed after adopt wrote it; the claim stands; run adopt again
exit 2
```

### E-ADOPT-32 -- another claim beside the holder's is no resume

Setup: E-ADOPT-01 adopted, then issue `#9` claiming `dependabot/uv/x`

```console
$ aco adopt 45 --no-item deps
2> ERROR: lane 'dependabot/uv/x' is claimed by Bob (builder) on issue #9 branch dependabot/uv/x
exit 2
```
