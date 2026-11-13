"""Run one explicitly approved, repeatable synthetic transaction demonstration."""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from csi_data.manifest import verify_files


ROOT = Path(__file__).resolve().parents[2]


def command(*args: str, input: str | None = None) -> str:
    result = subprocess.run(
        args, cwd=ROOT, text=True, input=input, capture_output=True, check=True
    )
    return result.stdout.strip()


def database_snapshot(project: str, login: str, account: str, run_id: str) -> dict:
    result = command(
        "docker",
        "compose",
        "-p",
        project,
        "--profile",
        "tools",
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "--entrypoint",
        "psql",
        "db-import",
        "-X",
        "-q",
        "-A",
        "-t",
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        f"login={login}",
        "-v",
        f"account={account}",
        "-v",
        f"run_id={run_id}",
        "-h",
        "db",
        "-U",
        "customer_insights",
        "-d",
        "customer_insights",
        "-f",
        "-",
        input="""SELECT json_build_object(
          'dataset', (SELECT row_to_json(d) FROM dataset_instance d WHERE singleton),
          'customer', (SELECT row_to_json(c) FROM customers c WHERE login_id=:'login'),
          'account', (SELECT row_to_json(a) FROM accounts a WHERE id=:'account'),
          'merchants', (SELECT coalesce(json_agg(id), '[]'::json) FROM merchants
            WHERE id IN ('cedar-market','harbor-cafe')),
          'events', (SELECT coalesce(json_agg(json_build_object('event_id',event_id,
            'operation',operation,'payload',payload,'result',result)), '[]'::json)
            FROM simulator_events WHERE event_id IN (
              'sim:event:'||:'run_id'||'-buy', 'sim:event:'||:'run_id'||'-post',
              'sim:event:'||:'run_id'||'-cancel-pending',
              'sim:event:'||:'run_id'||'-cancel')));
""",
    )
    return json.loads(result.splitlines()[-1])


def selected_account(dataset: Path) -> tuple[str, str]:
    with (dataset / "customers.csv").open(newline="", encoding="utf-8") as handle:
        customers = [
            row
            for row in csv.DictReader(handle)
            if row["login_id"] == "synthetic-00004"
        ]
    if len(customers) != 1 or customers[0]["status"] != "ACTIVE":
        raise ValueError("Expected one active synthetic-00004 customer")
    customer_id = customers[0]["customer_id"]
    with (dataset / "accounts.csv").open(newline="", encoding="utf-8") as handle:
        accounts = [
            row
            for row in csv.DictReader(handle)
            if row["customer_id"] == customer_id
            and row["account_kind"] == "EVERYDAY"
            and row["status"] == "OPEN"
            and row["opened_on"] <= "2026-10-30"
        ]
    if len(accounts) != 1:
        raise ValueError("Expected one eligible everyday account for synthetic-00004")
    with (dataset / "merchants.csv").open(newline="", encoding="utf-8") as handle:
        merchants = {row["merchant_id"] for row in csv.DictReader(handle)}
    if not {"cedar-market", "harbor-cafe"} <= merchants:
        raise ValueError("Demo merchants are missing from the validated dataset")
    return customer_id, accounts[0]["account_id"]


def verify_snapshot(
    snapshot: dict, manifest: dict, customer_id: str, account: str, run_id: str
) -> None:
    dataset = snapshot["dataset"]
    if (
        not dataset
        or dataset["dataset_id"] != manifest["dataset_id"]
        or dataset["seed_content_hash"] != manifest["seed_content_hash"]
    ):
        raise ValueError(
            "Database dataset identity differs from the validated demo dataset"
        )
    if dataset["reference_date"] < "2026-10-30":
        raise ValueError("Demo event date is outside the database dataset window")
    customer = snapshot["customer"]
    account_row = snapshot["account"]
    if not customer or customer["id"] != customer_id or customer["status"] != "ACTIVE":
        raise ValueError("Database login does not match the validated demo customer")
    if (
        not account_row
        or account_row["customer_id"] != customer_id
        or account_row["status"] != "OPEN"
        or account_row["account_kind"] != "EVERYDAY"
        or account_row["opened_on"] > "2026-10-30"
    ):
        raise ValueError(
            "Database account does not belong to the eligible demo customer"
        )
    if set(snapshot["merchants"]) != {"cedar-market", "harbor-cafe"}:
        raise ValueError("Demo merchants are missing from the database")
    buy_auth = f"sim_auth_{run_id}-buy"
    cancel_auth = f"sim_auth_{run_id}-cancel-pending"
    expected = {
        f"sim:event:{run_id}-buy": (
            "pending",
            {
                "account_id": account,
                "merchant_id": "cedar-market",
                "amount_minor": 10000,
                "occurred_at": "2026-10-30T10:00:00+02:00",
                "description": "Synthetic demo purchase",
            },
        ),
        f"sim:event:{run_id}-post": (
            "post",
            {
                "authorization_id": buy_auth,
                "amount_minor": 8500,
                "posted_at": "2026-10-30T11:00:00+02:00",
            },
        ),
        f"sim:event:{run_id}-cancel-pending": (
            "pending",
            {
                "account_id": account,
                "merchant_id": "harbor-cafe",
                "amount_minor": 4000,
                "occurred_at": "2026-10-30T12:00:00+02:00",
                "description": "Synthetic cancellation demo",
            },
        ),
        f"sim:event:{run_id}-cancel": (
            "cancel",
            {
                "authorization_id": cancel_auth,
                "cancelled_at": "2026-10-30T12:30:00+02:00",
            },
        ),
    }
    for event in snapshot["events"]:
        if (event["operation"], event["payload"]) != expected[event["event_id"]] or (
            event["result"] is not None
            and event["result"].get("customer_id") != customer_id
        ):
            raise ValueError(
                "Existing run ID belongs to a different demo request; choose a new run ID"
            )


def total(project: str, account: str) -> int:
    result = command(
        "docker",
        "compose",
        "-p",
        project,
        "--profile",
        "tools",
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "--entrypoint",
        "psql",
        "db-import",
        "-X",
        "-q",
        "-A",
        "-t",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        "db",
        "-U",
        "customer_insights",
        "-d",
        "customer_insights",
        "-c",
        f"SELECT COALESCE(sum(amount_minor), 0) FROM posted_entries WHERE account_id = '{account}'",
    )
    return int(result.splitlines()[-1])


def simulate(project: str, *args: str) -> dict:
    result = command(
        sys.executable, str(ROOT / "tools/simulator/cli.py"), project, project, *args
    )
    return json.loads(result)


def check_simulator_password(project: str) -> None:
    exists = command(
        "docker",
        "compose",
        "-p",
        project,
        "--profile",
        "tools",
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "--entrypoint",
        "psql",
        "db-import",
        "-X",
        "-q",
        "-A",
        "-t",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        "db",
        "-U",
        "customer_insights",
        "-d",
        "customer_insights",
        "-c",
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'customer_insights_simulator')",
    ).splitlines()[-1]
    if exists == "t":
        try:
            command(
                "docker",
                "compose",
                "-p",
                project,
                "--profile",
                "simulator",
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "--entrypoint",
                "psql",
                "db-sim",
                "-X",
                "-q",
                "-A",
                "-t",
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                "db",
                "-U",
                "customer_insights_simulator",
                "-d",
                "customer_insights",
                "-c",
                "SELECT 1",
            )
        except subprocess.CalledProcessError as error:
            raise ValueError(
                "Existing simulator database password differs from .env; no password was rotated"
            ) from error
    elif exists != "f":
        raise ValueError("Could not verify the simulator database role")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if not args.approve or not re.fullmatch(r"[a-z0-9-]{1,30}", args.run_id):
        parser.error(
            "Use a short lowercase run ID and --approve to authorize these financial mutations"
        )
    project = os.environ["CSI_COMPOSE_PROJECT"]
    dataset = ROOT / "generated-data" / project / "demo"
    manifest = verify_files(dataset)
    if manifest["profile"] != "demo":
        parser.error("The selected project has no approved demo dataset")
    customer_id, account = selected_account(dataset)
    verify_snapshot(
        database_snapshot(project, "synthetic-00004", account, args.run_id),
        manifest,
        customer_id,
        account,
        args.run_id,
    )
    check_simulator_password(project)
    command(
        sys.executable,
        "-m",
        "csi_data.simulator_approval",
        project,
        project,
        "--dataset",
        str(dataset),
    )
    before = total(project, account)
    pending = simulate(
        project,
        "pending",
        f"{args.run_id}-buy",
        account,
        "cedar-market",
        "10000",
        "2026-10-30T10:00:00+02:00",
        "Synthetic demo purchase",
    )
    if (
        pending.get("customer_id") != customer_id
        or pending.get("authorization_id") != f"sim_auth_{args.run_id}-buy"
    ):
        raise ValueError("Simulator purchase targeted an unexpected customer")
    after_pending = total(project, account)
    if after_pending != before:
        raise ValueError("Pending authorization changed posted totals")
    posted = simulate(
        project,
        "post",
        f"{args.run_id}-post",
        pending["authorization_id"],
        "8500",
        "2026-10-30T11:00:00+02:00",
    )
    if posted.get("customer_id") != customer_id:
        raise ValueError("Simulator posting targeted an unexpected customer")
    after_post = total(project, account)
    expected_post_total = before if posted["replayed"] else before - 8500
    if after_post != expected_post_total:
        raise ValueError("Posting changed the account by an unexpected amount")
    cancelled_pending = simulate(
        project,
        "pending",
        f"{args.run_id}-cancel-pending",
        account,
        "harbor-cafe",
        "4000",
        "2026-10-30T12:00:00+02:00",
        "Synthetic cancellation demo",
    )
    if cancelled_pending.get("customer_id") != customer_id:
        raise ValueError(
            "Simulator cancellation authorization targeted an unexpected customer"
        )
    cancelled = simulate(
        project,
        "cancel",
        f"{args.run_id}-cancel",
        cancelled_pending["authorization_id"],
        "2026-10-30T12:30:00+02:00",
    )
    if cancelled.get("customer_id") != customer_id:
        raise ValueError("Simulator cancellation targeted an unexpected customer")
    after_cancel = total(project, account)
    if after_cancel != after_post:
        raise ValueError("Cancellation changed posted totals")
    retry = simulate(
        project,
        "post",
        f"{args.run_id}-post",
        pending["authorization_id"],
        "8500",
        "2026-10-30T11:00:00+02:00",
    )
    if not retry.get("replayed") or total(project, account) != after_cancel:
        raise ValueError("Idempotent retry changed posted totals")
    print(
        json.dumps(
            {
                "project": project,
                "customer": "synthetic-00004",
                "account": account,
                "logical_date": "2026-10-30 Africa/Johannesburg",
                "posted_before_minor": before,
                "after_pending_minor": after_pending,
                "after_post_minor": after_post,
                "after_cancel_minor": after_cancel,
                "purchase": posted,
                "cancellation": cancelled,
                "retry": retry,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Demo failed: {error}", file=sys.stderr)
        sys.exit(1)
