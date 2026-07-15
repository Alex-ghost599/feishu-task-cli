from __future__ import annotations

from dataclasses import dataclass

from feishu_task_cli.artifacts.base import JsonValueNoFloat
from feishu_task_cli.artifacts.state import state_differences


@dataclass(frozen=True)
class ReconciliationResult:
    mismatches: tuple[str, ...]
    omitted_fields: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return not self.mismatches and not self.omitted_fields


def reconcile(
    requested: dict[str, JsonValueNoFloat], observed: dict[str, JsonValueNoFloat]
) -> ReconciliationResult:
    mismatches, omitted = state_differences(requested, observed)
    return ReconciliationResult(mismatches=mismatches, omitted_fields=omitted)
