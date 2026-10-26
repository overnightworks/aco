# Decision board: picture

[`mockup.html`](mockup.html) is the frozen picture owner of the `aco serve`
surface: the target picture of the decision board (v4, blessed 26.10.2026, ruled
as #13 line 12). It is a static page with sample data from public repositories;
it is self-contained: it loads nothing from the network, talks to no aco and
stores nothing.

The shipped board shows an option line as the picture's read-only card: meta
line, question, PROBLEM, TODAY, OPTIONS A to D with name and effect, and
RECOMMENDATION, and a ruled one with its chosen letter. It still lacks the
per-option disclosure, picture enlargement, DECIDE with "Other / Unclear"
instead of "Später", Mitsprache, the agent list and group decisions. A yes/no
line keeps its card. What the board does today is in the "Browser decision flow"
of [`specs/serve.spec.md`](../../specs/serve.spec.md).

A change to the board's surface starts here: change the mockup first, get the
operator's blessing, then build.
