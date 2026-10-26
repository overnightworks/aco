# Decision board: picture

[`mockup.html`](mockup.html) is the frozen picture owner of the `aco serve`
surface: the target picture of the decision board (v4, blessed 26.10.2026, ruled
as #13 line 12). It is a static page with sample data from public repositories;
it talks to no aco and stores nothing, and loads only web fonts from the network.

The shipped board does not have the picture's decision card yet: a structured
card with PROBLEM, TODAY, OPTIONS, RECOMMENDATION and DECIDE, the options A to D
with "Other / Unclear" instead of "Später", Mitsprache, the agent list and group
decisions. What the board does today is in the "Browser decision flow" of
[`specs/serve.spec.md`](../../specs/serve.spec.md).

A change to the board's surface starts here: change the mockup first, get the
operator's blessing, then build.
