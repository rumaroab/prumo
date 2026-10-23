from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import backend.app.storage as base_storage
from backend.app.mobility_routing import _blocked, _eligible, _eligible_node
from backend.app.mobility_storage import (MobilityConflict, act_on_movement, add_location,
                                          create_movement, create_share, create_user, hash_password, init_mobility_db,
                                          delete_route_plan, list_movements, list_route_plans, mobility_metrics,
                                          review_road_report, save_road_report, save_route_plan,
                                          revise_movement, revoke_share, save_unit, save_vehicle, session_user,
                                          shared_movement, update_unit_status, verify_password, login, logout)
from backend.app.models import (LocationCreate, MovementAction, MovementCreate, MovementRevision, OperationalUnit,
                                RoadReport, RouteLocation, RoutePlanInput, VehicleProfile)
from backend.app.storage import init_db


class MobilityStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = base_storage.DB
        base_storage.DB = Path(self.temp.name) / "mobility.sqlite3"
        init_db()
        init_mobility_db()
        with base_storage.connect() as db:
            stamp = datetime.now(UTC).isoformat()
            db.execute("INSERT INTO scenarios(id,name,revision,definition,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                       ("incident", "Exercise", 1, "{}", stamp, stamp))
        self.vehicle = VehicleProfile(name="Heavy 1", vehicle_class="heavy", width_m=2.5, weight_t=18)
        save_vehicle("incident", self.vehicle)
        self.unit = OperationalUnit(organisation="Civil Protection", callsign="CP-1", vehicle_id=self.vehicle.id)
        save_unit("incident", self.unit)
        add_location("incident", self.unit.id, LocationCreate(coordinates=(-8.29, 41.43),
                     observed_at=datetime.now(UTC), source="radio"))

    def tearDown(self):
        base_storage.DB = self.previous_db
        self.temp.cleanup()

    def movement_value(self):
        return MovementCreate(unit_id=self.unit.id, vehicle_id=self.vehicle.id, purpose="Road control",
                              origin=RouteLocation(name="Base", coordinates=(-8.29, 41.43)),
                              destination=RouteLocation(name="Village", coordinates=(-8.28, 41.44)),
                              departure_at=datetime.now(UTC),
                              route={"status": "clear", "segment_ids": ["segment-1"],
                                     "selected": {"road_names": ["Main road"]}})

    def route_plan_value(self):
        movement = self.movement_value()
        return RoutePlanInput(purpose=movement.purpose, origin=movement.origin,
                              destination=movement.destination, departure_at=movement.departure_at,
                              vehicle_class="light", preview_signature="preview")

    def test_route_plan_is_independent_of_unit_and_can_be_edited_or_discarded(self):
        route = {"status": "unknown", "message": "Estimated", "preview_signature": "preview"}
        saved = save_route_plan("incident", self.route_plan_value(), route)
        self.assertEqual(saved["revision"], 1)
        self.assertNotIn("preview_signature", saved["route"])
        self.assertEqual(list_route_plans("incident")[0]["id"], saved["id"])
        self.assertEqual(mobility_metrics(["incident"])["incident"]["active_movements"], 0)
        changed = self.route_plan_value().model_copy(update={"expected_revision": 1, "purpose": "New purpose"})
        updated = save_route_plan("incident", changed, route, saved["id"])
        self.assertEqual(updated["revision"], 2)
        with self.assertRaises(MobilityConflict):
            save_route_plan("incident", changed, route, saved["id"])
        delete_route_plan("incident", saved["id"], 2)
        self.assertEqual(list_route_plans("incident"), [])

    def test_route_plan_links_atomically_to_a_real_movement(self):
        plan = save_route_plan("incident", self.route_plan_value(), {"status": "clear"})
        value = self.movement_value().model_copy(update={
            "route_plan_id": plan["id"], "route_plan_revision": plan["revision"]})
        wrong = value.model_copy(update={"purpose": "Different purpose"})
        with self.assertRaises(MobilityConflict):
            create_movement("incident", wrong)
        self.assertEqual(list_movements("incident"), [])
        movement = create_movement("incident", value)
        linked = list_route_plans("incident")[0]
        self.assertEqual(linked["assigned_movement_id"], movement["id"])
        with self.assertRaises(MobilityConflict):
            delete_route_plan("incident", plan["id"], linked["revision"])

    def test_route_plan_assignment_rejects_a_unit_that_moved_after_preview(self):
        plan = save_route_plan("incident", self.route_plan_value(), {"status": "clear"})
        value = self.movement_value().model_copy(update={
            "route_plan_id": plan["id"], "route_plan_revision": plan["revision"]})
        add_location("incident", self.unit.id, LocationCreate(coordinates=(-8.27, 41.45),
                     observed_at=datetime.now(UTC), source="radio"))
        with self.assertRaisesRegex(MobilityConflict, "localização da unidade mudou"):
            create_movement("incident", value)
        self.assertEqual(list_movements("incident"), [])
        self.assertIsNone(list_route_plans("incident")[0]["assigned_movement_id"])

    def test_planning_preview_cannot_be_used_as_a_vehicle_preview(self):
        from backend.app.mobility_routing import preview_signature
        from backend.app.models import MobilityRouteRequest
        value = self.route_plan_value()
        planned = MobilityRouteRequest(origin=value.origin, destination=value.destination,
                                       vehicle_class="light", departure_at=value.departure_at)
        assigned = MobilityRouteRequest(origin=value.origin, destination=value.destination,
                                        vehicle_id=self.vehicle.id, departure_at=value.departure_at)
        generic_vehicle = VehicleProfile(id="planning-light", name="Viatura de planeamento", vehicle_class="light")
        route = {"status": "clear", "selected": {"segment_ids": ["segment-1"]}}
        self.assertNotEqual(preview_signature(planned, route, generic_vehicle),
                            preview_signature(assigned, route, self.vehicle))
        with self.assertRaises(ValueError):
            MobilityRouteRequest(origin=value.origin, destination=value.destination,
                                 vehicle_id=self.vehicle.id, vehicle_class="light", departure_at=value.departure_at)

    def test_active_unit_and_vehicle_cannot_be_double_booked(self):
        create_movement("incident", self.movement_value())
        with self.assertRaises(MobilityConflict):
            create_movement("incident", self.movement_value())
        with self.assertRaises(MobilityConflict):
            update_unit_status("incident", self.unit.id, "unavailable", 1)

    def test_aircraft_cannot_be_routed_or_assigned_on_road_network(self):
        from backend.app.mobility_routing import route_mobility
        from backend.app.models import MobilityRouteRequest
        aircraft=VehicleProfile(name='Aeronave 01',vehicle_class='aircraft')
        save_vehicle('incident',aircraft)
        unit=OperationalUnit(organisation='Por confirmar',callsign='Unidade aérea 01',vehicle_id=aircraft.id)
        save_unit('incident',unit)
        value=self.movement_value().model_copy(update={'unit_id':unit.id,'vehicle_id':aircraft.id})
        request=MobilityRouteRequest(origin=value.origin,destination=value.destination,vehicle_id=aircraft.id,
                                    departure_at=value.departure_at)
        self.assertFalse(_eligible({'highway':'primary'},aircraft))
        with self.assertRaisesRegex(ValueError,'aéreos'):
            route_mobility(Path('.'),request,aircraft,[])
        with self.assertRaisesRegex(MobilityConflict,'aéreos'):
            create_movement('incident',value)

    def test_mobility_metrics_summarize_operational_attention(self):
        initial = mobility_metrics(["incident", "empty"])
        self.assertEqual(initial["incident"], {
            "total_units": 1, "available_units": 1, "active_movements": 0,
            "pending_road_reports": 0, "routes_needing_review": 0,
        })
        self.assertEqual(initial["empty"]["total_units"], 0)

        create_movement("incident", self.movement_value())
        save_road_report("incident", RoadReport(segment_id="segment-1", road_name="Main road",
            kind="blocked", reason="Tree", source="crew", observed_at=datetime.now(UTC)))
        current = mobility_metrics(["incident"])["incident"]
        self.assertEqual(current["available_units"], 0)
        self.assertEqual(current["active_movements"], 1)
        self.assertEqual(current["pending_road_reports"], 1)
        self.assertEqual(current["routes_needing_review"], 1)

    def test_unit_availability_can_be_changed_when_unassigned(self):
        changed = update_unit_status("incident", self.unit.id, "unavailable", 1)
        self.assertEqual(changed["status"], "unavailable")
        self.assertEqual(changed["revision"], 2)

    def test_actions_are_idempotent_and_reject_obsolete_versions(self):
        movement = create_movement("incident", self.movement_value())
        action = MovementAction(action="accept", expected_revision=1, expected_brief_version=1,
                                request_id="request-0001")
        accepted = act_on_movement("incident", movement["id"], action)
        duplicate = act_on_movement("incident", movement["id"], action)
        self.assertEqual(accepted["revision"], duplicate["revision"])
        with self.assertRaises(MobilityConflict):
            act_on_movement("incident", movement["id"], MovementAction(
                action="depart", expected_revision=1, expected_brief_version=1, request_id="request-0002"))

    def test_confirmed_road_report_flags_active_movement(self):
        movement = create_movement("incident", self.movement_value())
        report = save_road_report("incident", RoadReport(segment_id="segment-1", road_name="Main road",
            kind="blocked", reason="Tree", source="crew", observed_at=datetime.now(UTC)))
        review_road_report("incident", report["id"], "confirmed", 1)
        current = next(item for item in list_movements("incident") if item["id"] == movement["id"])
        self.assertTrue(current["needs_review"])
        accepted = act_on_movement("incident", movement["id"], MovementAction(
            action="accept", expected_revision=1, expected_brief_version=1, request_id="request-1001"))
        with self.assertRaises(MobilityConflict):
            act_on_movement("incident", movement["id"], MovementAction(
                action="depart", expected_revision=accepted["revision"], expected_brief_version=1,
                request_id="request-1002"))
        revised = revise_movement("incident", movement["id"], MovementRevision(
            route={"status": "clear", "segment_ids": ["segment-2"]},
            expected_revision=accepted["revision"]))
        self.assertEqual(revised["brief_version"], 2)
        self.assertFalse(revised["needs_review"])

    def test_revised_brief_requires_its_own_acknowledgment(self):
        created = create_movement("incident", self.movement_value())
        accepted = act_on_movement("incident", created["id"], MovementAction(
            action="accept", expected_revision=1, expected_brief_version=1, request_id="request-ack-1"))
        revised = revise_movement("incident", created["id"], MovementRevision(
            route={"status": "clear", "segment_ids": ["segment-2"]},
            expected_revision=accepted["revision"]))
        self.assertEqual(revised["acknowledged_brief_version"], 1)
        with self.assertRaises(MobilityConflict):
            act_on_movement("incident", created["id"], MovementAction(
                action="depart", expected_revision=revised["revision"], expected_brief_version=2,
                request_id="request-ack-2"))
        with self.assertRaises(MobilityConflict):
            act_on_movement("incident", created["id"], MovementAction(
                action="acknowledge_brief", expected_revision=revised["revision"], expected_brief_version=1,
                request_id="request-ack-3"))
        acknowledged = act_on_movement("incident", created["id"], MovementAction(
            action="acknowledge_brief", expected_revision=revised["revision"], expected_brief_version=2,
            request_id="request-ack-4"))
        self.assertEqual(acknowledged["status"], "accepted")
        self.assertEqual(acknowledged["acknowledged_brief_version"], 2)
        departed = act_on_movement("incident", created["id"], MovementAction(
            action="depart", expected_revision=acknowledged["revision"], expected_brief_version=2,
            request_id="request-ack-5"))
        self.assertEqual(departed["status"], "travelling")

    def test_password_hash_is_salted_and_verified(self):
        first, second = hash_password("strong passphrase"), hash_password("strong passphrase")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("strong passphrase", first))
        self.assertFalse(verify_password("wrong", first))

    def test_sessions_and_shared_briefs_are_revocable_and_minimal(self):
        user = create_user("crew-1", "Crew 1", "long crew passphrase", "crew")
        token, signed_in = login("crew-1", "long crew passphrase")
        self.assertEqual(signed_in["id"], user["id"])
        self.assertEqual(session_user(token)["role"], "crew")
        movement = create_movement("incident", self.movement_value())
        share = create_share(movement["id"])
        brief = shared_movement(share)
        self.assertNotIn("unit_id", brief)
        self.assertNotIn("vehicle_id", brief)
        revoke_share(share)
        with self.assertRaises(KeyError):
            shared_movement(share)
        logout(token)
        self.assertIsNone(session_user(token))


class VehicleRoutingRulesTests(unittest.TestCase):
    def test_dimensions_surface_access_and_barriers(self):
        heavy = VehicleProfile(name="Tanker", vehicle_class="tanker", width_m=2.6, height_m=3.4,
                               weight_t=20, off_road=False)
        self.assertFalse(_eligible({"maxwidth": "2.4"}, heavy))
        self.assertFalse(_eligible({"surface": "gravel"}, heavy))
        self.assertFalse(_eligible({"access": "private"}, heavy))
        self.assertTrue(_eligible({"maxwidth": "3.0", "maxheight": "4.0", "maxweight": "30"}, heavy))
        self.assertFalse(_eligible_node({"barrier": "bollard"}))

    def test_directional_report_blocks_only_matching_edge(self):
        vehicle = VehicleProfile(name="Patrol", vehicle_class="light")
        reports = {"s1": [{"kind": "blocked", "status": "confirmed", "direction": "forward",
                             "affected_vehicle_classes": []}]}
        self.assertTrue(_blocked((1, 2, 0), vehicle, reports, {(1, 2, 0): [("s1", "forward")]}))
        self.assertFalse(_blocked((2, 1, 0), vehicle, reports, {(2, 1, 0): [("s1", "reverse")]}))

    def test_reopening_report_does_not_cancel_an_active_block(self):
        vehicle = VehicleProfile(name="Patrol", vehicle_class="light")
        reports = {"s1": [{"kind": "blocked", "status": "confirmed", "direction": "both", "affected_vehicle_classes": []},
                          {"kind": "reopening", "status": "confirmed", "direction": "both", "affected_vehicle_classes": []}]}
        self.assertTrue(_blocked((1, 2, 0), vehicle, reports, {(1, 2, 0): [("s1", "forward")]}))


if __name__ == "__main__":
    unittest.main()
