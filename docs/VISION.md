# Vision

aco lets several coding agents and the people who steer them work in one
repository without colliding, and without anyone having to keep the shared
state in their head.

## For whom, today

- The heads of the operator's fleet: Claude, Codex and Grok sessions, one per
  repository. They pull, claim, cut and land work items with it.
- Their helpers (builders, reviewers, landers), which work under a head's
  claim.
- The operator, who decides in chat and sees which of his decisions are
  still open.

## What it does

- It knows who holds which files right now, in one compare-and-swap git ref,
  so no two lanes build on the same paths unawares.
- It names the next item to pull, and says why another one is blocked or
  skipped.
- It lands exactly the commit the reviewers saw, then reports what the
  landing freed.
- It keeps one typed contract per work item that every agent reads the same
  way, and records each of the operator's decisions in it.

## What it deliberately is not

- Not a forge. Git, `gh` and GitHub own commits, branches, pull requests and
  issue text; aco reads them and adds only what they cannot hold.
- Not a service. Coordination needs only git and the forge: no lease
  server, no daemon, no provider configuration. The board is a local page.
- Not a project-management tool. An item has a rough size and nothing
  more: no time tracking, statistics or reports.
- Not a decider. It records the operator's word; it never rules in his
  place.
- Not a growing surface. The board stays as it is, and decisions happen in
  chat.
