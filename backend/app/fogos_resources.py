from __future__ import annotations

from typing import Any
import hashlib
import json
import sqlite3

from .models import ScenarioResourceGroup, FogosResourceProvenance, OperationalUnit, VehicleProfile


RESOURCE_CATEGORIES = (
    ("operacionais", "Operacionais", "personnel"),
    ("meios_terrestres", "Meios terrestres", "vehicles"),
    ("meios_aereos", "Meios aéreos", "aircraft"),
)


def import_mobility_inventory(db: sqlite3.Connection, scenario_id: str, snapshot: dict[str, Any], stamp: str):
    """Expand reported asset totals atomically; never infer crew identities or specs."""
    resources = snapshot["normalized"].get("resources") or {}
    notes = ("Registo provisório criado a partir de um total do Fogos.pt. Confirmar identidade, "
             "localização e disponibilidade; características e capacidades não comunicadas.")
    for category, key, vehicle_class, vehicle_label, unit_label in (
        ("meios_terrestres", "vehicles", "other", "Viatura terrestre", "Unidade terrestre"),
        ("meios_aereos", "aircraft", "aircraft", "Aeronave", "Unidade aérea"),
    ):
        count = resources.get(key)
        if count is None:
            continue
        for index in range(1, count + 1):
            identity = hashlib.sha256(f"{scenario_id}|fogos.pt|{category}|{index}".encode()).hexdigest()[:20]
            provenance = FogosResourceProvenance(incident_id=str(snapshot["incident_id"]),
                snapshot_id=str(snapshot["id"]), category=category, sequence=index,
                observed_at=snapshot.get("observed_at"))
            vehicle = VehicleProfile(id=f"fv-{identity}", name=f"{vehicle_label} {index:02d}",
                vehicle_class=vehicle_class, notes=notes, import_provenance=provenance)
            unit = OperationalUnit(id=f"fu-{identity}", callsign=f"{unit_label} {index:02d}",
                organisation="Por confirmar (Fogos.pt)", vehicle_id=vehicle.id, status="unavailable",
                notes=notes, import_provenance=provenance)
            for table, value in (("mobility_vehicles", vehicle), ("mobility_units", unit)):
                db.execute(f"INSERT OR IGNORE INTO {table} VALUES (?,?,?,?,?,?)",
                    (value.id, scenario_id, json.dumps(value.model_dump(mode="json", exclude={"latest_location"}),
                                                      ensure_ascii=False), 1, stamp, stamp))


def seed_resource_groups(snapshot: dict[str, Any]) -> list[ScenarioResourceGroup]:
    normalized = snapshot["normalized"]
    resources = normalized.get("resources") or {}
    return [ScenarioResourceGroup(
        id=f"fogos-{category}",
        category=category,
        name=name,
        reported_count=resources.get(source_key),
        provider="fogos.pt",
        incident_id=str(snapshot["incident_id"]),
        snapshot_id=str(snapshot["id"]),
        observed_at=snapshot.get("observed_at"),
        synced_at=str(snapshot["retrieved_at"]),
    ) for category, name, source_key in RESOURCE_CATEGORIES]


def reconcile_resource_groups(
    existing: list[ScenarioResourceGroup], snapshot: dict[str, Any],
) -> tuple[list[ScenarioResourceGroup], list[dict[str, Any]]]:
    seeded = {group.category: group for group in seed_resource_groups(snapshot)}
    current = {group.category: group for group in existing}
    reconciled: list[ScenarioResourceGroup] = []
    changes: list[dict[str, Any]] = []
    for category, _, _ in RESOURCE_CATEGORIES:
        reported = seeded[category]
        local = current.get(category)
        if local is None:
            reconciled.append(reported)
            changes.append({
                "category": category,
                "name": reported.name,
                "before": None,
                "after": reported.reported_count,
                "created": True,
            })
            continue
        updated = local.model_copy(update={
            "reported_count": reported.reported_count,
            "provider": reported.provider,
            "incident_id": reported.incident_id,
            "snapshot_id": reported.snapshot_id,
            "observed_at": reported.observed_at,
            "synced_at": reported.synced_at,
        })
        reconciled.append(updated)
        if local.reported_count != updated.reported_count:
            changes.append({
                "category": category,
                "name": local.name,
                "before": local.reported_count,
                "after": updated.reported_count,
                "created": False,
            })
    return reconciled, changes
