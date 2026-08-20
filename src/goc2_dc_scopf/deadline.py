from __future__ import annotations

import time
from dataclasses import dataclass


class RunDeadlineExceeded(TimeoutError):
    """Raised when a measured run has exhausted its registered wall-time budget."""

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = {} if details is None else details


@dataclass(frozen=True)
class RunDeadline:
    started: float
    limit_seconds: float | None

    @classmethod
    def start(cls, limit_seconds: float | None) -> RunDeadline:
        return cls(time.perf_counter(), limit_seconds)

    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started

    def remaining_seconds(self) -> float:
        if self.limit_seconds is None:
            return float("inf")
        return self.limit_seconds - self.elapsed_seconds()

    def check(self, stage: str, *, reserve_seconds: float = 0.0) -> None:
        if self.limit_seconds is None:
            return
        if self.remaining_seconds() <= reserve_seconds:
            raise RunDeadlineExceeded(
                f"Run deadline reached before {stage}: elapsed={self.elapsed_seconds():.3f}s, "
                f"limit={self.limit_seconds:.3f}s, reserve={reserve_seconds:.3f}s",
                details={
                    "stage": stage,
                    "elapsed_seconds": self.elapsed_seconds(),
                    "limit_seconds": self.limit_seconds,
                    "reserve_seconds": reserve_seconds,
                },
            )

    def solver_limit(self, stage: str, *, reserve_seconds: float) -> float | None:
        if self.limit_seconds is None:
            return None
        self.check(stage, reserve_seconds=reserve_seconds)
        return max(0.001, self.remaining_seconds() - reserve_seconds)
