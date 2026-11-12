"""Local operator entry point for the restricted PostgreSQL simulator."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
AUTHORIZATION = re.compile(r"[A-Za-z0-9_:-]{1,120}\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+02:00\Z")
PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}\Z")


def valid(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def timestamp(value: str, label: str) -> str:
    valid(value, TIMESTAMP, label)
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Invalid {label}") from error
    return value


def amount(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise ValueError("Amount must be positive integer cents, at most 18 digits")
    return int(value)


def arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restricted local transaction simulation"
    )
    parser.add_argument("project")
    parser.add_argument("approve_target")
    actions = parser.add_subparsers(dest="operation", required=True)
    pending = actions.add_parser("pending")
    pending.add_argument("event_key")
    pending.add_argument("account_id")
    pending.add_argument("merchant_id")
    pending.add_argument("amount_minor")
    pending.add_argument("occurred_at")
    pending.add_argument("description")
    post = actions.add_parser("post")
    post.add_argument("event_key")
    post.add_argument("authorization_id")
    post.add_argument("amount_minor")
    post.add_argument("posted_at")
    cancel = actions.add_parser("cancel")
    cancel.add_argument("event_key")
    cancel.add_argument("authorization_id")
    cancel.add_argument("cancelled_at")
    args = parser.parse_args(argv)
    valid(args.project, PROJECT, "Compose project")
    if args.project != args.approve_target:
        raise ValueError("Explicit target approval must match the Compose project")
    if not (ROOT / ".env").is_file():
        raise ValueError("Local .env is required")
    valid(args.event_key, IDENTIFIER, "event key")
    if args.operation == "pending":
        payload = {
            "account_id": valid(args.account_id, IDENTIFIER, "account ID"),
            "merchant_id": valid(args.merchant_id, IDENTIFIER, "merchant ID"),
            "amount_minor": amount(args.amount_minor),
            "occurred_at": timestamp(args.occurred_at, "occurrence time"),
            "description": args.description,
        }
        if not 1 <= len(args.description) <= 200:
            raise ValueError("Description must be 1 to 200 characters")
    elif args.operation == "post":
        payload = {
            "authorization_id": valid(
                args.authorization_id, AUTHORIZATION, "authorization ID"
            ),
            "amount_minor": amount(args.amount_minor),
            "posted_at": timestamp(args.posted_at, "posting time"),
        }
    else:
        payload = {
            "authorization_id": valid(
                args.authorization_id, AUTHORIZATION, "authorization ID"
            ),
            "cancelled_at": timestamp(args.cancelled_at, "cancellation time"),
        }
    args.payload = payload
    return args


def run(argv: list[str]) -> int:
    try:
        args = arguments(argv)
        command = [
            "docker",
            "compose",
            "-p",
            args.project,
            "--profile",
            "simulator",
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "db-sim",
            "-v",
            f"operation={args.operation}",
            "-v",
            f"event_key={args.event_key}",
            "-v",
            f"payload={json.dumps(args.payload, sort_keys=True, separators=(',', ':'))}",
        ]
        result = subprocess.run(
            command,
            input="SELECT public.simulate_transaction(:'operation', :'event_key', :'payload'::jsonb);\n",
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )
        if result.returncode:
            for reason in (
                "Idempotency key conflicts",
                "Authorization is no longer pending",
                "Event is outside the supported dataset window",
                "Posting precedes authorization",
                "Ineligible pending amount or account date",
                "Source event already exists",
                "Final amount must be positive",
                "Invalid simulator",
                "Invalid pending",
                "Invalid posting",
                "Invalid authorization",
                "Simulator target or identity is invalid",
                "Simulator dataset is not approved",
                "Cancellation precedes authorization",
                "Invalid cancellation time",
            ):
                if reason in result.stderr:
                    raise ValueError(reason)
            raise ValueError(
                "Simulation failed; check the target, role provisioning and eligible records"
            )
        outcome = json.loads(result.stdout.strip())
        print(json.dumps(outcome, sort_keys=True))
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
