"""Runtime engine registry. Installed adapters use the fireline.engines entry point group."""

from importlib.metadata import entry_points
import re

from .cell2fire import Cell2FireEngine
from .mtt import MTTEngine


def _discover() -> tuple[dict, dict[str, str]]:
    engines = {engine.descriptor.id: engine for engine in (MTTEngine(), Cell2FireEngine())}
    failures: dict[str, str] = {}
    for entry in entry_points(group="fireline.engines"):
        identifier = entry.name
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identifier):
            failures[identifier] = "Invalid engine ID"
            continue
        if identifier in engines:
            failures[identifier] = "Duplicate engine ID; bundled adapter retained"
            continue
        try:
            factory = entry.load()
            adapter = factory() if isinstance(factory, type) else factory
            descriptor = adapter.descriptor
            if (descriptor.id != identifier or not callable(descriptor.payload) or not descriptor.profiles
                    or descriptor.default_profile not in descriptor.profiles or not descriptor.weather_modes
                    or not callable(adapter.available)
                    or not callable(adapter.simulate) or not callable(adapter.validate)):
                raise ValueError("Adapter does not implement the engine contract")
            if descriptor.execution_pool not in {"thread", "process"} or not descriptor.concurrency_key or not descriptor.runner:
                raise ValueError("Invalid execution pool or concurrency key")
            if any(existing.descriptor.concurrency_key == descriptor.concurrency_key
                   and existing.descriptor.execution_pool != descriptor.execution_pool
                   for existing in engines.values()):
                raise ValueError("Concurrency key is already used by a different execution pool")
            engines[identifier] = adapter
        except Exception as error:
            failures[identifier] = f"Adapter failed to load: {error}"
    return engines, failures


ENGINES, ENGINE_FAILURES = _discover()


def available_engines() -> list[dict]:
    values = []
    for engine in ENGINES.values():
        try:
            available, message = engine.available()
        except Exception as error:
            available, message = False, f"Availability check failed: {error}"
        try:
            payload = engine.descriptor.payload(bool(available), str(message))
            if engine.descriptor.id in ENGINE_FAILURES:
                payload["registry_warning"] = ENGINE_FAILURES[engine.descriptor.id]
            values.append(payload)
        except Exception as error:
            values.append({"id": engine.descriptor.id, "display_name": engine.descriptor.id,
                           "available": False, "message": f"Descriptor failed: {error}"})
    for identifier, failure in ENGINE_FAILURES.items():
        if identifier not in ENGINES:
            values.append({"id": identifier, "display_name": identifier, "profiles": [], "default_profile": "",
                           "weather_modes": [], "profile_weather": {}, "runner": "unavailable", "compute_class": "unknown",
                           "limitations": [], "supports_multiple_ignitions": False, "supports_delayed_ignitions": False,
                           "execution_pool": "thread", "concurrency_key": "unavailable", "available": False,
                           "message": failure})
    return values


def compatible_profile(engine, weather_kind: str) -> str | None:
    """Return the preferred profile that accepts the requested weather source."""
    descriptor = engine.descriptor
    ordered = (descriptor.default_profile, *(
        profile for profile in descriptor.profiles if profile != descriptor.default_profile
    ))
    for profile in ordered:
        modes = descriptor.profile_weather.get(profile, descriptor.weather_modes)
        if weather_kind in modes:
            return profile
    return None
