# Vision

aco lets several coding agents and the people who steer them work in one
repository without colliding, and without anyone having to keep the shared
state in their head.

## For whom, today

- The heads of the operator's fleet: Claude, Codex and Grok sessions, one per
  repository. They pull, claim, cut and land work items with it.
- Their helpers (builders, reviewers, landers), which work under a head's
  claim.
- The operator, who decides in chat. aco records his word on an item and
  shows which of his decisions are still open.

## What it holds

- Who holds which files right now, in one compare-and-swap git ref, so two
  lanes never build on the same paths unawares.
- Which item to pull next, and why another one is blocked or skipped.
- That a landing merges exactly the commit the reviewers saw, and what it
  freed.
- The work-item contract: one typed block per item that every agent reads the
  same way.

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
