"""The per-repository read of the decisions waiting on the operator.

The rows `aco rulings` prints, on the items a member of the repository wrote
and no other: in a public repository a stranger can open an item that carries
a card, and a card reaches the operator's decision surface only from a writer
of the repository.
"""

from collections.abc import Iterable

from . import body, rulings, workboard


def rows(issues: Iterable[workboard.Issue], *, storage: body.Storage) -> tuple[rulings.Row, ...]:
    """`rulings.rows` over the members' items among `issues`."""
    members = (issue for issue in issues if issue.author_is_member)
    return rulings.rows(members, storage=storage)
