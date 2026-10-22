# 0001 — Claim state without a ledger issue

Names in this record are those in use when it was decided; the package and command were later renamed to `agent-coordination` and `aco` (D7).

Status: accepted and implemented. The state ref shipped with 1.0.0 (07.09.2026); the ledger issue and its import code are gone.

Date: 05.09.2026. Baseline: `origin/main` = `2bcf3f3` (v0.9.0 plus a Sonar cleanup that changed no contract), tag `v0.9.0`.

Source: a two-round architecture concept and two independent counter-checks, both
returning REBUILD. This record harvests them. Where a counter-check contradicts the
concept, the counter-check's version stands, and it is written here as such.

## 1. Context: what the ledger issue costs today

`agent-claim` keeps every claim in one GitHub issue whose comments are the ledger.
Five costs are measured or read from the v0.9.0 source, not assumed.

| Problem | Evidence |
|---|---|
| A read of the whole ledger on every guarded write | `protect` re-reads the live ledger before each write tool call. Reported cost ~2.4 s per call (unverified, §6) |
| The same claim written in three places | The ledger comment owns it; an item projection comment (`upsert_projection` in `github.py`) and a generation label repeat it, and only `reconcile` repairs the drift |
| Acquisition is not atomic, only late-compensating | `_acquire_claim_with_observed` posts, then re-runs `blocking_claims`; the loser posts a compensating release. Three writes on the losing path. (The concept claimed both commands simply succeed; the round-1 counter-check corrected that — it is compensating, not unguarded) |
| Item contracts parsed by regex over prose in two languages | `board.py` compiles 28 patterns over `nichts`, `geregelt: ja\|NEIN`, `Eingefroren bis:`, `## Schnitt`, `**Scheibe n:**`, plus a markdown slice table with two malformed-input defect classes |
| No provider seam | `cli.py` shells out to `gh api` directly and both `cli.py` and `github.py` branch on the substring `"HTTP 404"`. A GitLab adapter has nowhere to attach |

## 2. Decision

**One state ref.** `refs/aco/state` (named by ruling) on one configured canonical
remote points at a
commit whose tree *is* the current state: `claims/<key>.toml`, `resources/<name>.toml`, a
schema `version`. The tree owns current state; the commit message owns the transition. A
released claim is simply absent from the new tree and readable at the parent commit — there
is no second history ref.

**Advanced by ordinary fast-forward pushes, not `--force-with-lease`.** Git documents that
an explicit matching lease *overrides* the normal fast-forward restriction, so a correct
lease can still replace history. A plain push to a custom ref already accepts fast-forwards
and rejects non-fast-forwards, which is exactly the serialization needed, without opening
the history-loss path. This corrects the concept, which specified a lease.

**Every transition is a commit that applies a typed intent to the observed state.** The
client fetches the ref, parses the tree, and calls a pure `apply(observed_state, intent)`;
the result is committed on the observed tip and pushed. A rejected push means the state
moved: re-read, re-apply *the original intent* to the new state, retry. The transitions are
claim, rescope, release (the landed `MergedRelease | AbandonedRelease` union, reused
verbatim), coordinator override, and stale takeover.

**Resource allocation happens inside the same commit as the claim that requests it.** This
is what makes repository-global integer uniqueness a consequence of the CAS rather than a
separate invariant: two lanes requesting the same resource serialize on the one ref, and the
loser re-applies its intent and gets the next integer. Both counter-checks agree this is the
only shape whose cross-key invariant does not rest on an unverified server capability.

**A typed fenced TOML block replaces regex prose in item bodies.** One `agent-claim` fenced
region parsed by `tomllib`. **Keys are protocol and are always English; values are the
operator's prose and are never parsed.** This retires the German markers, the slice table,
and both malformed-input defect classes. Step 4 draws that line concretely:
human projection (`now`/`next`/`done_when`), freeze, expectation `text`, and slice `title`
are the operator's own words; `version` and an expectation's `default`/`ruling` values are
protocol tokens. `next` keeps its non-parsed vocabulary (`keiner | keine | nichts | none |
-`, owned by `has_further_work`, plus `tbd | todo | unknown` concreteness) as the explicit
exception to "values are never parsed". The replacement was completed on 08.09.2026:
the regex reader is deleted, so the block is not one grammar among two but the only one.

**Blockers and parentage live on the forge's structured relations where the pinned storage
configuration says so.** Capabilities *validate* the pin; they never *choose* the owner. The
round-2 counter-check named runtime capability selection as an unresolved defect in the
concept: a forge plan change must never silently move a fact's owner without a migration.

**Addendum (16.09.2026).** `cut` writes `Parent: #<container>` as the first prose
line of every fresh child body. It is a recovery marker, not a parentage source: only `cut`'s
own orphan adoption reads it back, so a repeat `cut` after a failed relation write can finish
the same relation instead of creating a second child. No reader derives parentage from the
body; the sub-issue relation stays the only owner.

**A provider port with a capability enum `UNSUPPORTED | READ_ONLY | READ_WRITE`,** replacing
the concept's `Support(read, write)` pair, which could represent the illegal
`read=False, write=True`. The adapter owns every fallback so no caller branches on a
capability. Forge failures are typed (`ForgeUnsupported`, `ForgePermissionDenied`,
`ForgeNotFound`, `ForgeTransient`, `ForgeMalformedResponse`) instead of substring-matched.

**Configuration stays in `.agent-claim/board.toml`,** extended only with settings that have a
caller today: the pinned body contract (`body_contract`) and `canonical_remote`
(default `origin`) naming the remote `refs/aco/state` lives on — every store and
import refusal is worded in its terms. No separate state-storage-strategy key was ever added;
the ref and its tree shape are the only storage decision, and both are named above. Renaming
the file is rejected — it would cost a migration to buy a better name.

## 3. Rejected alternatives

| Alternative | The sentence that killed it |
|---|---|
| Per-item claim comments | The comment API exposes no conditional write anywhere the design would use, so two agents can both post and neither loses — and issueless lanes have no issue to hold a comment |
| Assignee as the lock | It is additive on GitHub and last-writer-replacement on GitLab Free, has no CAS on either, and names a forge account rather than the agent and session that holds the claim |
| Projects v2 fields | No demonstrated CAS, an extra item-synchronization step, GraphQL coupling, and no GitLab Free equivalent (the concept's original reason — a missing token scope — is not architectural, since a scope can be granted) |
| Per-key refs plus a resources ref | A resource-holding claim would have its hold in `claims/<key>` and its integer in `resources`, two owners that can disagree, and making them one transition needs `git push --atomic` across refs, whose support on both SaaS hosts is unverified |

## 4–5. Acceptance criteria and migration order

The round-2 counter-check listed eleven acceptance criteria and a six-step migration order. The state-ref cut, the forge port with typed errors, the typed body block and the GitHub custom-ref probe (§6) are implemented. The GitLab state-transport preflight (criterion 7) and the optional receipt (step 6, D1) are decided but not implemented, and no open item carries them; D1 stands.

## 6. Measured facts

Judged as the counter-checks judged them. "Reported live" means the concept author ran it on 05.09.2026 against `overnightworks/agent-claim` and neither counter-check could reproduce it (both lost network access to `api.github.com`). The GitHub custom-ref probe was re-run live by the head on 05.09.2026 and is marked verified below; the org-plan and issue-type probes remain unverified.

| Fact | Standing | Source |
|---|---|---|
| GitHub accepts pushes to `refs/agent-claim/*`; create-if-absent, fast-forward update, non-fast-forward rejection, concurrent rejection (two parallel pushes of different children from two clones → exactly one winner, the other "cannot lock ref"), a stale-lease create rejected, and delete all behave as required; the REST endpoint `git/refs/agent-claim` returns 200 while the ref is present and 404 after deletion; the ref is invisible in the normal GitHub UI | Verified 05.09.2026 | Head's live re-run, 05.09.2026, `overnightworks/agent-claim`, namespace `refs/agent-claim/probe-1788623638` (deleted afterwards) |
| Push to a custom ref: plain push is fast-forward-only; a matching lease still permits a non-fast-forward replacement | Verified (documentation) | `git push` documentation; the reason §2 rejects the lease |
| Two racers on one expected OID: at most one lands; the loser re-reads and retries | Verified in a throwaway bare repo; "exactly one" corrected to "at most one" (permissions, hooks or transport can fail every racer) | Concept local experiment; round-1 counter-check |
| Custom-ref create-if-absent 1.9 s, fast-forward update 1.9 s, `ls-remote` 1.4 s, single-ref fetch 1.4 s, delete 1.9 s; today's gate ~2.4 s per write | Verified 05.09.2026; environment-specific and not to be projected onto other repositories | Head's live re-run, 05.09.2026 |
| `overnightworks` plan free, repository public; org issue types are `Task, Bug, Feature` with no `Container` | Reported live, unverified; token scopes never evidenced | Concept probes, 05.09.2026 |
| GitHub issue dependencies are available on Free; sub-issues allow 100 direct children and 8 nesting levels | Verified (documentation) | GitHub docs |
| GitHub rulesets and branch protection target branches and tags only, never `refs/agent-claim/*` | Verified (documentation) | GitHub docs. Accepted: the threat model is cooperating clients |
| GitHub supports organization-owned custom issue types | Verified (documentation) | GitHub issue-type API |
| `refs/agent-claim/*` is pushable on GitLab | **Unverified** — the Branches API proves only `refs/heads` creation, and Gitaly's note about other namespaces certifies neither GitLab.com nor every installation | Round-2 counter-check |
| GitLab Free: one assignee (replacing, not union); `blocks` is paid; child items exist; configurable work-item types are paid | Verified (documentation) | GitLab docs |
| The landed release union `MergedRelease \| AbandonedRelease` | Verified from `eb384b1` | `protocol.py` |
| v0.9.0 reads only `priority_labels` and `idea_label` from `board.toml` and silently ignores every other key | Verified from `eb384b1` | `board.py` — the reason criterion 8 needs a tombstone, not a pin |

## 7. Operator rulings, 05.09.2026

Recorded verbatim.

- The ledger issue goes away; the 03.09.2026 ruling on [the ledger issue] is overturned.
- GitLab must be possible later without a rewrite.
- Typed contracts.
- Per-repository configuration only for settings with a caller.
- The decision criterion for every open point is the cleanest long-term solution with one
  owner per fact.
- Rescope and resource allocation are preserved.
- Roles stay open.
- Read-only commands never write.
- No metrics without a caller.
- The threat model is cooperating clients.
- Upstream push rights are mandatory for claimants.

### Decided by that criterion

| # | Decision | Reasoning (counter-check) |
|---|---|---|
| D1 | A receipt comment, written after a successful state change and never read back as truth. No assignee projection | The assignee is a racing copy: an old release removes its claim, a successor claims and assigns, then the old release clears the assignee — and only `status`/`board` could repair it, which read-only commands may not do. It also shows a forge account, not the agent. Exactly-once is not available; the contract is "attempt after a successful transition; a receipt failure never changes the successful state result" |
| D2 | The write gate authorizes only against live state. No positive caching | A cached commit authorizes writes that live state denies after a release, takeover or scope reduction, and after a clock rollback or a future-dated stamp the window is not even bounded by its nominal length. Only negative decisions may be cached |
| D3 | Item kind is the native issue type, including an organization-level `Container` type on GitHub. Ruled 05.09.2026: the organization type `Container` (id 859945696) now exists next to Task, Bug, Feature; the container items carry it | It is the clean one-owner mechanism. GitLab Free cannot create a custom `Container` type, so its adapter maps item kind read-only there |
| D4 | Wide-scope thresholds are protocol constants, not configuration | No caller for repository-specific thresholds, and configuration would let two fleets in one repository disagree on what "too wide" means |
| D5 | The migration machinery is deleted in the first release after every supported repository is proven migrated and old clients are fenced | Release distance does not decide safety; the proof does. A fixed "next release" is right only if that proof already exists |
| D6 | One reviewed AI session per repository performs the body/relation hand migration; the typed reader and the real CLI validate its result; GitHub's edit history is the undo. Does not repeal D1 or step 6, which concern later state-transition receipts | A migration command or module would be machinery with one caller and one run per repository — the hand-reviewed edit plus the existing typed reader already proves it without adding that surface |
| D7 | The package renames to `agent-coordination` and the command to `aco`, one name each with no alias kept for the old ones. Ruled 06.09.2026; timing amended 07.09.2026 (H1): the rename lands in slice F, after the state-ref cut (step 5) and its one-time ledger import, not in the same release as the cut — the import checklist still runs `agent-claim bootstrap --ledger N` from a 1.0-but-not-yet-renamed build, since renaming the console script the import itself depends on would break the checklist mid-migration. That import ran on 07.09.2026 and `--ledger` was deleted with the rest of the import code, so slice F now renames a `bootstrap` that only creates the state ref. Implemented 07.09.2026: the distribution is `agent-coordination` and its one console script is `aco` | Command, package, and storage model already break together at the rename release, so carrying an alias forward would promise a continuity that release does not otherwise offer; H1 separates "the storage model breaks" (step 5) from "the name breaks" (slice F) so the import has one fixed tool name to run under, not a moving target |
| D8 | `pr-check` becomes `check <number>`, taking its number positionally: against a pull request it reports the landing classification `pr-check` performs today; against an issue it reports the body contract, missing sections, blockers, and legacy body, in the same release as D7. Ruled 06.09.2026 | An agent asks one question of a number — what stands between it and its next step — and GitHub answers what kind it is on the payload the adapter already fetches; the rename release teaches the port to carry that one field instead of adding a second lookup or a second command |
