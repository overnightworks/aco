"""The MCP server's tool writers as test doubles: each hands back what it was called with."""

import dataclasses
from collections.abc import Mapping

from aco import item_step


def echoing_answer_step(
    label: str, number: int, step: str, result: item_step.StepResult
) -> Mapping[str, object]:
    return {"repository": label, "item": number, "step": step, "result": dataclasses.asdict(result)}
