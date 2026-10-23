"""Back up the local SQLite database and rebuild the Portuguese exercise data.

Run with the application stopped: python -m backend.scripts.reset_and_seed_pt
Cached terrain, road packages and calculated fire results are retained.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from backend.app.seed_demo import seed as seed_bundled
from backend.app.settings import DATA, DB, ROOT
from backend.scripts.seed_decision_demo import export_public_bundle, seed as seed_decision


def reset_and_seed() -> None:
    backup = None
    if DB.exists():
        sidecars = [DB.with_name(DB.name + suffix) for suffix in ("-wal", "-shm")]
        if any(path.exists() for path in sidecars):
            raise RuntimeError("Pare a aplicação e feche as ligações à base de dados antes de a repor.")
        destination = DATA / "backups" / f"antes-reposicao-pt-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        destination.mkdir(parents=True, exist_ok=False)
        backup = destination / DB.name
        with sqlite3.connect(DB) as source, sqlite3.connect(backup) as target:
            if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("A base de dados atual falhou a verificação de integridade.")
            source.backup(target)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("A cópia de segurança falhou a verificação de integridade.")
        DB.unlink()

    seed_bundled()
    comparisons = seed_decision()
    export_public_bundle(comparisons, ROOT / "public_demo_site" / "demo.json")
    public_dist = ROOT / "public_demo_site" / "dist"
    if public_dist.exists():
        export_public_bundle(comparisons, public_dist / "demo.json")

    print(f"Cópia de segurança: {backup or 'base de dados nova'}")
    print(f"Base de dados reposta: {DB}")
    print("Exemplos em português: 2 cenários, 6 autotanques, 72 comparações de água e 72 avaliações de acessos.")


if __name__ == "__main__":
    reset_and_seed()
