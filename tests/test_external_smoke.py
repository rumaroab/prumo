from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.app.engines.archived_external import FarsiteEngine, QuicFireEngine, WrfSfireEngine
from backend.app.io import load_landscape
from backend.app.models import Scenario


@unittest.skipUnless(os.getenv("RUN_EXTERNAL_ENGINE_SMOKES") == "1",
                     "set RUN_EXTERNAL_ENGINE_SMOKES=1 after configuring Docker/licenses/Slurm")
class ExternalEngineSmokeTests(unittest.TestCase):
    """Tiny opt-in end-to-end checks for site-specific external runtimes."""

    def run_engine(self, name: str, profile: str = "default") -> None:
        engine = {"farsite": FarsiteEngine(), "quicfire": QuicFireEngine(), "wrf_sfire": WrfSfireEngine()}[name]
        available, reason = engine.available()
        if not available:
            self.skipTest(reason)
        scenario = Scenario(engine=name, engine_profile=profile, ignition=(-8.2782, 41.4298),
                            duration_min=10, wind_speed_kmh=12, wind_direction_deg=270)
        with tempfile.TemporaryDirectory() as folder:
            result = engine.simulate(load_landscape(), scenario, Path(folder))
            self.assertEqual(result.arrival_minutes.shape, result.coverage.shape)
            self.assertEqual(result.crs, "EPSG:3763")
            self.assertTrue(result.manifest)
            required = {"engine_version", "profile", "runner", "command", "runtime_identity",
                        "input_sha256", "weather_source", "output_interval_min", "runtime_seconds",
                        "warnings", "generated_files"}
            self.assertFalse(required - set(result.manifest))

    def test_farsite_tiny_domain(self):
        self.run_engine("farsite")

    def test_quicfire_tiny_domain_when_licensed(self):
        self.run_engine("quicfire")

    def test_wrf_sfire_tiny_domain_when_configured(self):
        self.run_engine("wrf_sfire", "coupled-idealized")
