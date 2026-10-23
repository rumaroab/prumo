from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any
from urllib.parse import urljoin

import requests


class DemoClient:
    def __init__(self, base_url: str, username: str | None, password: str | None):
        self.base_url = base_url.rstrip("/") + "/"
        self.session = requests.Session()
        if username:
            if not password:
                raise RuntimeError("Set FIRELINE_DEMO_PASSWORD when using --username")
            self.request("POST", "api/session", json={"username": username, "password": password})

    def request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = self.session.request(method, urljoin(self.base_url, path), timeout=15, **kwargs)
        except requests.RequestException as error:
            raise RuntimeError(f"Cannot reach {self.base_url}: {error}") from error
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(f"{response.status_code}: {detail}")
        return response.json()


def status(client: DemoClient, run_id: str | None = None) -> dict[str, Any]:
    query = f"?run_id={run_id}" if run_id else ""
    return client.request("GET", f"api/internal/demo/status{query}")


def print_status(run: dict[str, Any], base_url: str) -> None:
    if run.get("state") == "not_created":
        print("No mobility demonstration has been created.")
        return
    elapsed = float(run.get("elapsed_seconds", 0))
    duration = float(run.get("duration_seconds", 0))
    next_event = run.get("next_event")
    print(f"State: {run['state']} · stage: {run['stage']} · time: {_clock(elapsed)} / {_clock(duration)}")
    print(f"Scenario: {urljoin(base_url.rstrip('/') + '/', run['scenario_url'].lstrip('/'))}")
    if next_event:
        print(f"Next: {next_event['id']} at {_clock(float(next_event['at_seconds']))} · {next_event['message_en']}")
    if run.get("error"):
        print(f"Stopped: {run['error']}")
    if run.get("report_path"):
        print(f"Execution report: {run['report_path']}")


def playback(client: DemoClient, run: dict[str, Any]) -> int:
    lease = client.request("POST", f"api/internal/demo/runs/{run['id']}/lease")
    token, run = lease["lease_token"], lease["run"]
    headers = {"X-Demo-Lease": token}
    speed = float(run["speed"])
    base_elapsed = float(run["elapsed_seconds"])
    anchor = time.monotonic()
    last_heartbeat = 0.0
    previous_state = run["state"]
    previous_stage = run["stage"]
    print_status(run, client.base_url)
    print(f"Runner acquired · {speed:g}× playback. Ctrl-C stops this process; the run remains resumable.")
    try:
        while True:
            current_state = run["state"]
            if run.get("error"):
                print_status(run, client.base_url)
                return 1
            if current_state == "completed":
                print_status(run, client.base_url)
                return 0
            if current_state == "error":
                print_status(run, client.base_url)
                return 1
            now_mono = time.monotonic()
            elapsed = base_elapsed + ((now_mono - anchor) * speed if current_state == "running" else 0)
            next_event = run.get("next_event")
            if current_state == "running" and next_event and elapsed + .01 >= float(next_event["at_seconds"]):
                run = client.request("POST", f"api/internal/demo/runs/{run['id']}/heartbeat",
                                     headers=headers, json={"elapsed_seconds": elapsed})
                base_elapsed = float(run["elapsed_seconds"])
                anchor = time.monotonic()
                if run["state"] != "running":
                    previous_state = run["state"]
                    continue
                receipt = client.request(
                    "POST", f"api/internal/demo/runs/{run['id']}/events/{next_event['id']}",
                    headers=headers, json={"elapsed_seconds": base_elapsed})
                print(f"[{_clock(float(next_event['at_seconds']))}] {receipt['event_id']} applied")
                run = status(client, run["id"])
                if run["stage"] != previous_stage:
                    print(f"Stage: {run['stage']}")
                    previous_stage = run["stage"]
                base_elapsed = float(run["elapsed_seconds"])
                anchor = time.monotonic()
                previous_state = run["state"]
                continue
            if now_mono - last_heartbeat >= 1:
                run = client.request("POST", f"api/internal/demo/runs/{run['id']}/heartbeat",
                                     headers=headers, json={"elapsed_seconds": elapsed})
                last_heartbeat = now_mono
                if run["state"] != previous_state:
                    print(f"Playback {run['state']} at {_clock(float(run['elapsed_seconds']))}.")
                    previous_state = run["state"]
                base_elapsed = float(run["elapsed_seconds"])
                anchor = time.monotonic()
            time.sleep(.2)
    except KeyboardInterrupt:
        print("\nRunner stopped. Start it again after the lease expires to resume from the last confirmed event.")
        return 130


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic PRUMO mobility presentation")
    parser.add_argument("--base-url", default=os.getenv("FIRELINE_DEMO_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--username", default=os.getenv("FIRELINE_DEMO_USERNAME"))
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "restart"):
        command = commands.add_parser(name)
        command.add_argument("--speed", type=float, choices=(1, 2), default=1)
    commands.add_parser("pause")
    commands.add_parser("resume")
    commands.add_parser("status")
    args = parser.parse_args()
    try:
        client = DemoClient(args.base_url, args.username, os.getenv("FIRELINE_DEMO_PASSWORD"))
        if args.command in {"run", "restart"}:
            run = client.request("POST", "api/internal/demo/runs",
                                 json={"speed": args.speed, "restart": args.command == "restart"})
            return playback(client, run)
        run = status(client)
        if run.get("state") == "not_created":
            print_status(run, args.base_url)
            return 1
        if args.command in {"pause", "resume"}:
            run = client.request("POST", f"api/internal/demo/runs/{run['id']}/control",
                                 json={"action": args.command})
        print_status(run, args.base_url)
        return 0
    except RuntimeError as error:
        print(f"Demo runner error: {error}", file=sys.stderr)
        return 1


def _clock(seconds: float) -> str:
    value = max(0, int(seconds))
    return f"{value // 60:02d}:{value % 60:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
