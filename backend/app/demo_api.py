from __future__ import annotations

import os

from fastapi import APIRouter, Body, Header, HTTPException, Request

from .mobility_api import _user
from .mobility_demo import (DemoConflict, acquire_demo_lease, apply_demo_event, control_demo,
                            create_demo_run, current_demo_run, demo_run, heartbeat_demo)
from .mobility_storage import MobilityConflict


router = APIRouter()


def _administrator(request: Request) -> dict:
    if os.getenv("FIRELINE_DEMO_ENABLED", "0").lower() not in {"1", "true", "yes"}:
        raise HTTPException(404, "Demo runner is disabled")
    user = _user(request)
    if user["role"] != "administrator":
        raise HTTPException(403, "Administrator access required")
    return user


@router.get("/api/internal/demo/status")
def demo_status(request: Request, run_id: str | None = None):
    _administrator(request)
    try:
        selected = demo_run(run_id) if run_id else current_demo_run()
    except KeyError:
        raise HTTPException(404, "Demo run not found")
    return selected or {"state": "not_created"}


@router.post("/api/internal/demo/runs", status_code=201)
def create_run(request: Request, payload: dict = Body(default_factory=dict)):
    user = _administrator(request)
    try:
        return create_demo_run(user.get("id"), float(payload.get("speed", 1)), bool(payload.get("restart", False)))
    except DemoConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(422, str(error)) from error


@router.post("/api/internal/demo/runs/{run_id}/lease")
def acquire_lease(run_id: str, request: Request):
    _administrator(request)
    try:
        token, run = acquire_demo_lease(run_id)
        return {"lease_token": token, "run": run}
    except KeyError:
        raise HTTPException(404, "Demo run not found")
    except DemoConflict as error:
        raise HTTPException(409, str(error)) from error


@router.post("/api/internal/demo/runs/{run_id}/heartbeat")
def heartbeat(run_id: str, request: Request, payload: dict = Body(...),
              x_demo_lease: str | None = Header(None)):
    _administrator(request)
    if not x_demo_lease:
        raise HTTPException(401, "Demo runner lease required")
    try:
        return heartbeat_demo(run_id, x_demo_lease, float(payload.get("elapsed_seconds", 0)))
    except KeyError:
        raise HTTPException(404, "Demo run not found")
    except DemoConflict as error:
        raise HTTPException(409, str(error)) from error


@router.post("/api/internal/demo/runs/{run_id}/control")
def control(run_id: str, request: Request, payload: dict = Body(...)):
    _administrator(request)
    action = str(payload.get("action", ""))
    if action not in {"pause", "resume"}:
        raise HTTPException(422, "Action must be pause or resume")
    try:
        return control_demo(run_id, action)
    except KeyError:
        raise HTTPException(404, "Demo run not found")
    except DemoConflict as error:
        raise HTTPException(409, str(error)) from error


@router.post("/api/internal/demo/runs/{run_id}/events/{event_id}")
def apply_event(run_id: str, event_id: str, request: Request, payload: dict = Body(...),
                x_demo_lease: str | None = Header(None)):
    _administrator(request)
    if not x_demo_lease:
        raise HTTPException(401, "Demo runner lease required")
    try:
        return apply_demo_event(run_id, event_id, x_demo_lease, float(payload.get("elapsed_seconds", 0)))
    except KeyError:
        raise HTTPException(404, "Demo run or entity not found")
    except DemoConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, MobilityConflict) as error:
        raise HTTPException(422, str(error)) from error
