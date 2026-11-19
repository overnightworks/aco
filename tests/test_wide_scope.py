"""`wide_scope` behavior: the rule that refuses a claim whose scope is too wide."""

from aco import wide_scope


def test_wide_scope_trip_for_paths_directory_or_share_above_the_limits() -> None:
    three = ("a.py", "b.py", "c.py")
    four = (*three, "d.py")
    assert (
        wide_scope.wide_scope_trip(
            three, directories=(), covered_file_count=3, versioned_file_count=20
        )
        is None
    )
    assert (
        wide_scope.wide_scope_trip(
            four, directories=(), covered_file_count=4, versioned_file_count=20
        )
        is not None
    )
    assert (
        wide_scope.wide_scope_trip(
            ("docs",), directories=("docs",), covered_file_count=1, versioned_file_count=20
        )
        is not None
    )
    assert (
        wide_scope.wide_scope_trip(
            ("a.py",), directories=(), covered_file_count=1, versioned_file_count=4
        )
        is None
    )
    assert (
        wide_scope.wide_scope_trip(
            ("a.py", "b.py", "c.py"),
            directories=(),
            covered_file_count=3,
            versioned_file_count=wide_scope.WIDE_SCOPE_SHARE_FLOOR - 1,
        )
        is None
    ), "below the share floor, a share over a quarter still does not trip"
    assert (
        wide_scope.wide_scope_trip(
            ("a.py", "b.py", "c.py"),
            directories=(),
            covered_file_count=4,
            versioned_file_count=wide_scope.WIDE_SCOPE_SHARE_FLOOR,
        )
        is not None
    ), "at the share floor, a share over a quarter trips"
    assert (
        wide_scope.wide_scope_trip(
            ("a.py",), directories=(), covered_file_count=0, versioned_file_count=0
        )
        is None
    )


def test_wide_scope_trip_names_the_condition_in_the_rule_s_priority_order() -> None:
    """`wide_scope_trip(...) is not None` is the one rule owner -- a
    path-count trip outranks a directory trip that would also fire."""
    four = ("a.py", "b.py", "c.py", "d.py")
    assert wide_scope.wide_scope_trip(
        four, directories=("a.py",), covered_file_count=4, versioned_file_count=20
    ) == wide_scope.WideScopeTrip(wide_scope.WideScopeReason.PATH_COUNT, 4, ("a.py",), 4, 20)
    assert wide_scope.wide_scope_trip(
        ("docs",), directories=("docs",), covered_file_count=1, versioned_file_count=20
    ) == wide_scope.WideScopeTrip(wide_scope.WideScopeReason.DIRECTORY, 1, ("docs",), 1, 20)
    assert wide_scope.wide_scope_trip(
        ("a.py", "b.py", "c.py"),
        directories=(),
        covered_file_count=4,
        versioned_file_count=wide_scope.WIDE_SCOPE_SHARE_FLOOR,
    ) == wide_scope.WideScopeTrip(
        wide_scope.WideScopeReason.SHARE, 3, (), 4, wide_scope.WIDE_SCOPE_SHARE_FLOOR
    )
    assert (
        wide_scope.wide_scope_trip(
            ("a.py",), directories=(), covered_file_count=1, versioned_file_count=4
        )
        is None
    )
