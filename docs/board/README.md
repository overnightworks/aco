# Decision board: picture

[`mockup.html`](mockup.html) is the frozen picture owner of the `aco serve`
surface: the target picture of the decision board (v4, blessed 26.10.2026, ruled
as #13 line 12). It is a static page with sample data from public repositories;
it is self-contained: it loads nothing from the network, talks to no aco and
stores nothing.

The shipped board shows an option line as the picture's card: meta line,
question, PROBLEM, TODAY, OPTIONS A to D with name and effect, RECOMMENDATION and
DECIDE with one pick per option. Every ruled line shows the picture's decided card:
Decided, How with the way and the date or `not recorded`, and Contract behind Show. A line decided with the operator's own answer reads `Other: „…“` under Decided and binds that answer alone. Each
option opens its RESULT, YOU NOTICE, COST, UNDO and CONTRACT. Every TODAY and
RESULT picture opens enlarged in a dialog, and on a phone TODAY is a framed
thumbnail with the enlarge mark. A pick on a `final` option first asks in a
confirm dialog. A pick shows the picture's strip with Undo for its 8-second
window, as a row above the card (placement ruled by the operator on 27.10.2026)
that stays in view while the card scrolls and, on a phone, above the list too.
The Decide row ends with "Other…" and "Unclear". "Other…" opens a panel for his own
answer, sent through `aco rule --other` with the same undo window as a pick. "Unclear" opens
a note panel, optional to fill, and sends the card to its head through `aco rule --unclear`
after the same window, under a grey "With head" strip; a card already with its head hides
"Unclear" and keeps its picks and "Other…". It still lacks Mitsprache, the agent list and group decisions. An open yes/no line keeps its card.
The list groups open and decided lines per project with the picture's Open,
With-head, Not-ready and Decided shapes (Decided shows the selected line's card in the
pane), and the page has the picture's header with Open and Decided and its
colour tokens. With-head is a line the operator sent back: muted, listed after
the open ones, its card says `with head`. On a phone an opened card stands edge to edge under a header whose ‹ Open or ‹ Decided returns to the list.
What the board does today is in the "Browser decision flow" of
[`specs/serve.spec.md`](../../specs/serve.spec.md).

A change to the board's surface starts here: change the mockup first, get the
operator's blessing, then build.
