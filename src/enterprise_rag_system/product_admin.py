"""Offline operator commands for pilot credentials and consistent backups."""

import argparse
import json
from pathlib import Path

from enterprise_rag_system.product_backup import verify_backup
from enterprise_rag_system.product_store import Registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue-user", help="Create or rotate a credential; prints it once")
    issue.add_argument("--tenant", required=True)
    issue.add_argument("--user", required=True)
    issue.add_argument("--role", choices=["admin", "editor", "reader"], required=True)
    revoke = commands.add_parser("revoke-user")
    revoke.add_argument("--tenant", required=True)
    revoke.add_argument("--user", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    commands.add_parser("prune-measurements", help="Remove expired quality measurements")
    commands.add_parser("verify-backup", help="Validate a registry snapshot without modifying it")
    args = parser.parse_args()
    if args.command == "verify-backup":
        print(json.dumps(verify_backup(args.database)))
        return
    if args.command != "issue-user" and not args.database.is_file():
        parser.error("Database does not exist")
    store = Registry(args.database)
    if args.command == "issue-user":
        print(store.issue_user(args.tenant, args.user, args.role))
    elif args.command == "revoke-user":
        store.revoke(args.tenant, args.user)
        print("Credential revoked")
    elif args.command == "prune-measurements":
        print(f"Removed {store.prune_measurements()} measurements")
    else:
        store.backup(args.destination)
        print("Backup completed")


if __name__ == "__main__":
    main()
