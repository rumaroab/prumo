# Mobility pilot deployment and exercise

This pilot coordinates operational journeys. It does not certify a route as safe. “No recorded conflict” means only that the prepared road data and current confirmed reports contain no detected conflict.

## Single-server HTTPS setup

1. Prepare a Linux or macOS host with Python 3.12, `uv`, Node.js, and persistent storage for the repository `data/` directory.
2. Put an HTTPS reverse proxy such as Caddy or nginx in front of the application. Proxy to `127.0.0.1:8000`, preserve `Host` and `X-Forwarded-Proto`, and expose only the proxy. Browser location check-ins require HTTPS.
3. Bootstrap the first administrator on the first start:

   ```bash
   export FIRELINE_SHARED_MODE=1
   export FIRELINE_BOOTSTRAP_ADMIN=pilot-admin
   export FIRELINE_BOOTSTRAP_ADMIN_PASSWORD='use-a-long-unique-passphrase'
   ./start.sh
   ```

   Remove `FIRELINE_BOOTSTRAP_ADMIN_PASSWORD` from the service environment after the account exists. Startup never replaces an existing account.

4. Run the service under a service manager with `FIRELINE_SHARED_MODE=1`, `FIRELINE_HOST=127.0.0.1`, and a fixed working directory. The health probe is `GET /api/health`.
5. Back up `data/platform.sqlite3`, `data/areas/`, and `data/runs/` together while the service is stopped. Restore the same set before restarting.

Do not publish port 8000 directly. Shared mode protects API endpoints, uses revocable 12-hour server sessions, and marks its session cookie HTTPS-only.

## Accounts and crew assignment

Create dispatchers and crew accounts from the server. Pass the password through the environment so it does not appear in shell history:

```bash
FIRELINE_NEW_USER_PASSWORD='another-long-passphrase' \
  uv run python -m backend.scripts.manage_mobility create-user dispatcher-1 \
  --name 'Dispatcher 1' --role dispatcher
```

Create vehicles and units in **Units and vehicles**. Then assign a crew account to one unit:

```bash
uv run python -m backend.scripts.manage_mobility assign-crew SCENARIO_ID crew-1 UNIT_ID
```

Crew users see only their assigned unit and its movements. Administrators and dispatchers see the complete scenario.

## Road data

Newly prepared areas store exact links between visible road sections and directed routing edges plus available OpenStreetMap vehicle limits. Existing packages remain usable and display a limited-data warning. Reprepare an area before a real exercise to gain exact directional reports and the newest restriction data.

Unknown width, height, weight, surface, gate, or endpoint access remains visible in the route assessment. A dispatcher may acknowledge missing information but cannot bypass a known prohibition.

## Supervised exercise

Use two dispatchers and three crew accounts from different organisations.

1. Register a light vehicle and a heavy vehicle, then record fresh unit locations by phone and by radio.
2. Create and acknowledge a journey; progress through departure, arrival, and completion.
3. Report a blocked road from a crew phone. Confirm it in **Updates** and verify that affected active movements become **Needs review**.
4. Compare the light and heavy vehicles on a constrained route.
5. Disconnect a crew phone, reopen the last briefing, and complete the exercise by radio through the dispatcher.

Measure routine assignment time, road-report time, and crew update taps. The targets are 60 seconds, 20 seconds, and one primary tap after setup. Record observed confusion or missing road information; these targets are evaluation criteria, not safety or performance claims.

## Deterministic presentation runner

The internal runner creates a dedicated **Mobility demonstration** scenario and replays 25 fictional communications and operational updates over eight minutes. It uses a bundled synthetic road network, performs normal vehicle-aware route calculations, and does not contact external services or alter existing scenarios.

Enable the internal endpoints only on the presentation server:

```bash
export FIRELINE_DEMO_ENABLED=1
./start.sh
```

In a second terminal, start the real-time presentation:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m backend.scripts.mobility_demo run
```

The runner prints the scenario URL. Open it as an administrator and leave the runner process active. Use `--speed 2` for a four-minute rehearsal:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m backend.scripts.mobility_demo run --speed 2
```

Playback controls are separate commands, so they can be invoked from another terminal:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m backend.scripts.mobility_demo status
UV_CACHE_DIR=.uv-cache uv run python -m backend.scripts.mobility_demo pause
UV_CACHE_DIR=.uv-cache uv run python -m backend.scripts.mobility_demo resume
UV_CACHE_DIR=.uv-cache uv run python -m backend.scripts.mobility_demo restart --speed 2
```

`restart` archives the previous demo run and its scenario, then creates a clean scenario. It does not delete ordinary scenarios, accounts, simulation results, or prepared road packages.

For shared-server mode, provide an administrator account. The password is read from the environment rather than the command line:

```bash
export FIRELINE_DEMO_USERNAME=pilot-admin
export FIRELINE_DEMO_PASSWORD='the-administrator-passphrase'
UV_CACHE_DIR=.uv-cache uv run python -m backend.scripts.mobility_demo \
  --base-url https://pilot.example.org run
```

The runner holds a short exclusive lease. If it is interrupted, wait about 12 seconds and run `run` again to resume from the last confirmed event. A failed assertion stops playback visibly; use `status` to read the cause and `restart` after correcting it.

Completed runs remain visible for inspection. Their machine-readable reports are written under `data/demo/mobility-reports/`. Each report records the script and fixture checksums, applied events, route identities, and pass/fail assertions for rerouting, the heavy-vehicle bridge exclusion, brief acknowledgment, and reopening resolution.

The banner and every incoming message identify the content as simulated. The runner is a presentation aid and does not demonstrate live integrations, operational readiness, or achieved usability targets. Disable `FIRELINE_DEMO_ENABLED` outside controlled presentations.
