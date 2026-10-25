# Decision board: picture

[`mockup.html`](mockup.html) is the frozen picture owner of the `aco serve`
surface: the card (question, example, picture, yes, no, note, undo), the history
of decided lines, the "access missing" state, the filter bar and the phone
variant. It is a static page with sample data; it talks to no aco and stores
nothing, and loads only web fonts from the network.

The shipped 3a selection flow follows this picture's list-and-question layout:
desktop shows the first open question immediately, while phones start with
the short question list and open the selected question on tap. “Liste” returns
to the preserved selection. “Verlauf” separately shows decided lines from
open board items as read-only details; it is not an archive of closed issues.
The question, example, picture, note,
answers and undo are available; the mockup's richer filters and comparison
views are not part of this flow.

A change to the board's surface starts here: change the mockup first, get the
operator's blessing, then build.
