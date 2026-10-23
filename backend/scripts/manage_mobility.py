from __future__ import annotations

import argparse
import os

from backend.app.mobility_storage import create_user, init_mobility_db
from backend.app.storage import connect, init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage PRUMO pilot accounts and memberships")
    commands = parser.add_subparsers(dest="command", required=True)
    user = commands.add_parser("create-user")
    user.add_argument("username")
    user.add_argument("--name", required=True)
    user.add_argument("--role", choices=("administrator", "dispatcher", "crew"), required=True)
    membership = commands.add_parser("assign-crew")
    membership.add_argument("scenario_id")
    membership.add_argument("username")
    membership.add_argument("unit_id")
    args = parser.parse_args()
    init_db(); init_mobility_db()
    if args.command == "create-user":
        password = os.getenv("FIRELINE_NEW_USER_PASSWORD", "")
        if len(password) < 12:
            raise SystemExit("Set FIRELINE_NEW_USER_PASSWORD to at least 12 characters")
        created = create_user(args.username, args.name, password, args.role)
        print(f"Created {created['username']} ({created['role']}) with id {created['id']}")
        return
    with connect() as db:
        row = db.execute("SELECT id FROM users WHERE username=? AND role='crew' AND active=1", (args.username,)).fetchone()
        unit = db.execute("SELECT 1 FROM mobility_units WHERE id=? AND scenario_id=?", (args.unit_id, args.scenario_id)).fetchone()
        if not row:
            raise SystemExit("Active crew user not found")
        if not unit:
            raise SystemExit("Unit not found in that scenario")
        db.execute("INSERT INTO mobility_memberships(scenario_id,user_id,unit_id) VALUES (?,?,?) "
                   "ON CONFLICT(scenario_id,user_id) DO UPDATE SET unit_id=excluded.unit_id",
                   (args.scenario_id, row["id"], args.unit_id))
    print(f"Assigned {args.username} to {args.unit_id} in {args.scenario_id}")


if __name__ == "__main__":
    main()
