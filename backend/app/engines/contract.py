"""Public contract for bundled and installed Fireline engine adapters."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from ..models import Landscape, Scenario, SimulationResult


@dataclass(frozen=True)
class EngineDescriptor:
    id: str
    display_name: str
    profiles: tuple[str, ...]
    default_profile: str
    weather_modes: tuple[str, ...]
    runner: str
    compute_class: str
    limitations: tuple[str, ...]
    profile_weather: dict[str, tuple[str, ...]] = field(default_factory=dict)
    supports_multiple_ignitions: bool = False
    supports_delayed_ignitions: bool = False
    execution_pool: str = "thread"
    concurrency_key: str = "local-process"

    def payload(self, available: bool, message: str) -> dict:
        return {**asdict(self), "available": available, "message": message}


class EngineAdapter(Protocol):
    descriptor: EngineDescriptor

    def available(self) -> tuple[bool, str]: ...
    def validate(self, scenario: Scenario) -> None: ...
    def simulate(self, landscape: Landscape, scenario: Scenario, output: Path) -> SimulationResult: ...
