# Vision

aco is the agents' own tool, built by agents for agents. It lets many coding
agents work in parallel across many repositories without getting in each
other's way, and without any of them having to remember what the others do.
The person who steers them sees only the decisions that are theirs.

## For whom, today

- The agents that lead a repository: they pick, claim, split and finish work
  with it.
- The agents they delegate to (builders, reviewers, landers), working under
  their lead.
- The operator, who steers the fleet. He reads no session to stay informed:
  each question that is his reaches him as one decision card, with its
  options and a recommendation.

## What it can do

- It knows who works on which files right now, so no two agents change the
  same thing unawares.
- It names the next piece of work, and says why another one has to wait.
- It merges a change only in the exact state the reviewers saw, then says
  what that frees up.
- It keeps one contract per piece of work that every agent reads the same
  way, with the operator's open questions and his answers in it.
- It gathers the open questions of all repositories in one place for the
  operator to decide; an answer he gives in chat counts the same.

## What it deliberately is not

- Not a reading room. Status, transcripts and evidence stay with the agents;
  what reaches the operator is a decision.
- Not a code host or issue tracker. It uses the ones a repository already
  has and adds only what they cannot hold.
- Not a standing service: nothing has to run between sessions. Agents
  coordinate through the repository itself; a session that wants the
  operator's inbox starts its own reader for its own length.
- Not a project-management tool. A piece of work has a rough size and
  nothing more: no time tracking, statistics or reports.
- Not a decider. It records the operator's word and never rules in his place.
