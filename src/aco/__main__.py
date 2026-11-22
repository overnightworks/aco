"""`python -m aco`: `aco` that refuses to answer when it loaded a mix of two installs."""

from aco import installed_code

_FIRST_READ = installed_code.first_read()

from aco import cli  # noqa: E402 - the install is read before aco's own import graph loads

raise SystemExit(installed_code.checked(_FIRST_READ, cli.main))
