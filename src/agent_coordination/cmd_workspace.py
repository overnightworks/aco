"""The `register`, `run`, `login` and `_run-at-login` commands (`specs/workspace.spec.md`)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import protocol, providers, terminal, workspace


def _workspace_config_path() -> Path:
    return workspace.default_config_path(os.environ)


def _register_workspace(parsed: argparse.Namespace) -> int:
    handoff = workspace.WorkspaceRegistration(
        parsed.project,
        parsed.path,
        parsed.session_id,
        parsed.agent,
        parsed.model,
        provider=providers.Provider(parsed.provider),
        live_pid=parsed.live_pid,
    )
    created = workspace.register_project(handoff, _workspace_config_path())
    status = "registered" if created else "already registered"
    print(f"{parsed.project}: {status}")
    return 0


def _run_workspace(parsed: argparse.Namespace) -> int:
    outcomes = workspace.run_projects(_workspace_config_path(), parsed.project)
    for outcome in outcomes:
        suffix = f": {outcome.detail}" if outcome.detail else ""
        print(f"{outcome.project}: {outcome.state}{suffix}")
    return (
        2
        if any(
            outcome.state in {workspace.RunState.FAILED, workspace.RunState.UNKNOWN}
            for outcome in outcomes
        )
        else 0
    )


def _login_summary(result: workspace.LoginRunResult) -> str:
    if result.attempt.failure is not None:
        return "Workspace recovery failed."
    outcomes = result.attempt.outcomes
    failed_states = {workspace.RunState.FAILED, workspace.RunState.UNKNOWN}
    failed = sum(state in failed_states for _, state in outcomes)
    already_live = sum(state is workspace.RunState.EXTERNAL for _, state in outcomes)
    recovered = len(outcomes) - failed - already_live
    summary = f"Workspace recovery completed for {recovered} project(s)."
    if already_live:
        summary += f" {already_live} project(s) already had live owners; no console was opened."
    if failed:
        summary += f" {failed} project(s) failed recovery."
    return summary


def _run_at_login() -> int:
    try:
        result = workspace.run_login_recovery(
            _workspace_config_path(), workspace.login_attempt_path(os.environ)
        )
    except workspace.WorkspaceError:
        terminal.notify_login_recovery("Workspace recovery could not record its attempt.")
        return 2
    terminal.notify_login_recovery(_login_summary(result))
    return result.exit_status


def _login_status() -> int:
    launcher = workspace.login_launcher_state(os.environ, Path(sys.executable))
    configuration = workspace.login_configuration_state(_workspace_config_path())
    print(f"launcher: {launcher}")
    print(f"configuration: {configuration}")
    try:
        attempt = workspace.load_login_attempt(workspace.login_attempt_path(os.environ))
    except FileNotFoundError:
        print("attempt: no login attempt recorded")
        return 0
    except workspace.WorkspaceError:
        print("attempt: malformed")
        return 2
    print(f"attempt: {attempt.attempt_id} {attempt.started_at} {attempt.state}")
    for project, outcome in attempt.outcomes:
        print(f"{project}: {outcome}")
    if attempt.failure is not None:
        print(f"workspace: {attempt.failure}")
    if attempt.completed_at is not None:
        print(f"completed: {attempt.completed_at}")
    return 0


def _login_operation(parsed: argparse.Namespace) -> int:
    if parsed.repo is not None:
        raise protocol.ClaimError("--repo is meaningless for login recovery operations")
    if parsed.login_command == "enable":
        changed = workspace.enable_login(_workspace_config_path(), os.environ, Path(sys.executable))
        print("login launcher enabled" if changed else "login launcher already enabled")
        return 0
    if parsed.login_command == "disable":
        changed = workspace.disable_login(os.environ)
        print("login launcher disabled" if changed else "login launcher already disabled")
        return 0
    return _login_status()


def run(parsed: argparse.Namespace) -> int:
    if parsed.command == "_run-at-login":
        return _run_at_login()
    if parsed.command == "login":
        return _login_operation(parsed)
    if parsed.repo is not None:
        raise protocol.ClaimError("--repo is meaningless for workspace operations")
    return _register_workspace(parsed) if parsed.command == "register" else _run_workspace(parsed)
