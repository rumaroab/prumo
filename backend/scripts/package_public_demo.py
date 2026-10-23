"""Copy the calculated, fictional exercise bundle into the static viewer build."""
from __future__ import annotations

import shutil
from pathlib import Path

from backend.app.settings import ROOT
from backend.scripts.seed_decision_demo import export_public_bundle, seed


def package() -> Path:
    root = ROOT / "public_demo_site"
    dist = root / "dist"
    built = dist / "public-demo.html"
    if not built.exists():
        raise FileNotFoundError("Build the public viewer with vite.public.config.ts first")
    outcomes = seed()
    export_public_bundle(outcomes, dist / "demo.json")
    shutil.copyfile(dist / "demo.json", root / "demo.json")
    shutil.copyfile(built, dist / "index.html")
    return dist


if __name__ == "__main__":
    print(package())
