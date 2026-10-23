from __future__ import annotations

from backend.app.engines import ENGINES
from backend.app.models import Scenario
from backend.app.seed_demo import generate_bundled_demos
from backend.app.storage import create_run, init_db
from backend.app.worker import process


def main() -> None:
    init_db()
    generate_bundled_demos()
    for engine_name in ("farsite", "quicfire", "wrf_sfire"):
        engine = ENGINES[engine_name]
        available, reason = engine.available()
        if not available:
            print(f"Skipping {engine_name}: {reason}")
            continue
        scenario = Scenario(name=f"Penha demonstration · {engine.descriptor.display_name}", engine=engine_name,
                            engine_profile=engine.descriptor.default_profile, ignition=(-8.2782, 41.4298),
                            wind_speed_kmh=24, wind_direction_deg=285, moisture="moderate",
                            duration_min=120, exposure_buffer_m=30)
        run = create_run(scenario)
        process(run)
        print(f"Generated {engine_name} run {run.id}")


if __name__ == "__main__":
    main()
