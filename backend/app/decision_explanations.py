"""Structured, snapshot-friendly explanations for mobility decisions."""
from __future__ import annotations


def point_feature(coordinates):
    return {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": coordinates}}


def explain_outcome(outcome, source, choice, shared, *, closure_feature=None):
    """Keep evidence numeric. The shared renderer formats the scenario's clock."""
    conflict = outcome.get("conflict") or {}
    reason = conflict.get("reason")
    feature = conflict.get("feature") or point_feature(source.coordinates)
    stage = next((value["kind"] for value in reversed(outcome.get("stages", []))
                  if value.get("status") in {"infeasible", "unknown"}), None)
    if reason == "source_exposure":
        stage = "filling"
    elif reason == "destination_exposure":
        stage, feature = "unloading", point_feature(shared.delivery_coordinates)
    exposure = conflict.get("exposure_min")
    limit = exposure - shared.lead_time_min if exposure is not None else None
    base = {"place": conflict.get("road_name") or source.name, "feature": feature,
            "unit": shared.unit.callsign, "stage": stage,
            "severity": "info" if outcome["status"] == "clear" else outcome["status"],
            "message": outcome["reason"]}
    explanations = []
    if reason in {"source_exposure", "destination_exposure", "fire_exposure"}:
        explanations.append({**base, "code": reason, "category": "modelled_fire",
            "event_min": limit, "exposure_min": exposure,
            "vehicle_exit_min": conflict.get("vehicle_exit_min"), "lead_time_min": shared.lead_time_min,
            "message": ("O percurso rodoviário normal ultrapassa a janela de exposição; foi calculado um desvio."
                        if outcome["status"] == "clear" else
                        "A viagem não termina esta etapa dentro da janela de exposição configurada.")})
    elif reason in {"vehicle_restriction", "recorded_restriction", "proposed_closure"}:
        explanations.append({**base, "code": reason, "category": "restriction",
            "feature": closure_feature or feature, "constraint": conflict.get("constraint"),
            "actual": conflict.get("actual"), "limit": conflict.get("limit"),
            "exercise_assumption": conflict.get("exercise_assumption"),
            "event_min": getattr(shared, "departure_min", None)})
    elif outcome["status"] != "clear":
        message = outcome["reason"]
        code = "missing_information" if outcome["status"] == "unknown" else "trip_unavailable"
        if outcome["status"] == "unknown" and not (choice.flow_l_min or source.water.shared_flow_l_min or source.water.flow_l_min):
            code, message = "missing_flow", "Falta o caudal da fonte. Não é possível calcular o tempo de enchimento."
        elif shared.requested_l > (shared.unit.vehicle.water_tank_capacity_l or 0) - (shared.unit.vehicle.starting_water_l or 0):
            code, message = "vehicle_capacity", f"O pedido de {shared.requested_l:g} L excede a capacidade livre desta viatura."
            base.update(place=shared.unit.callsign,feature=point_feature(shared.unit.coordinates))
        elif source.water.available_volume_l is not None and shared.requested_l > (choice.available_volume_l if choice.available_volume_l is not None else source.water.available_volume_l):
            code = "insufficient_stock"
            message = f"A fonte dispõe de {choice.available_volume_l if choice.available_volume_l is not None else source.water.available_volume_l:g} L para um pedido de {shared.requested_l:g} L."
        explanations.append({**base, "code": code,
            "category": "missing_data" if outcome["status"] == "unknown" else "resource",
            "message": message})
    if outcome["status"] == "clear":
        for stage in outcome.get("stages", []):
            diagnostic = stage.get("conflict") or {}
            exposure = diagnostic.get("exposure_min")
            if diagnostic.get("reason") != "fire_exposure" or exposure is None:
                continue
            explanations.append({**base, "code": "fire_exposure", "category": "modelled_fire", "severity": "info",
                "place": diagnostic.get("road_name") or "Percurso normal", "stage": stage["kind"],
                "feature": diagnostic.get("feature"), "event_min": exposure-shared.lead_time_min,
                "exposure_min": exposure, "vehicle_exit_min": diagnostic.get("vehicle_exit_min"),
                "lead_time_min": shared.lead_time_min,
                "message": "Foi avaliado um desvio devido à exposição no percurso normal."})
    margin = outcome.get("minimum_forecast_margin_min")
    if outcome["status"] == "clear" and margin is not None and margin < 5:
        critical = min((stage for stage in outcome.get("stages", [])
                        if stage.get("route", {}).get("minimum_forecast_margin_min") is not None),
                       key=lambda stage: stage["route"]["minimum_forecast_margin_min"], default=None)
        detail = ({"stage": critical["kind"], "feature": critical["route"].get("feature"),
                   "event_min": critical["start_min"],
                   "place": "Regresso ao setor" if critical["kind"] == "inbound" else "Percurso de ida"}
                  if critical and abs(critical["route"]["minimum_forecast_margin_min"] - margin) < .02 else {})
        explanations.append({**base, **detail, "code": "small_margin", "category": "modelled_fire", "severity": "advisory",
            "margin_min": margin, "message": f"Restam {margin:.1f} minutos de margem modelada, já descontada a antecedência configurada."})
    outcome["explanations"] = explanations
    return outcome
