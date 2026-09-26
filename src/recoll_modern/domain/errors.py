"""Application errors that can be rendered consistently at transport boundaries."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AppError(Exception):
    """A stable, safe error contract for expected application failures."""

    code: str
    message: str
    status: int
    details: Mapping[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message
