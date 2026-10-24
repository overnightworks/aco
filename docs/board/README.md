# Decision board: picture

[`mockup.html`](mockup.html) is the frozen picture owner of the `aco serve`
surface: the card (question, example, picture, yes, no, note, undo), the history
of decided lines, the "access missing" state, the filter bar and the phone
variant. It is a static page with sample data; it talks to no aco and stores
nothing, and loads only web fonts from the network.

The shipped 3a selection flow follows this picture's list-and-question layout:
desktop keeps both panes visible, while phones open the question and return to
the preserved selection with “Liste”. The question, example, picture, note,
answers and undo are available; the mockup's richer filters and comparison
views are not part of this flow.

A change to the board's surface starts here: change the mockup first, get the
operator's blessing, then build.
