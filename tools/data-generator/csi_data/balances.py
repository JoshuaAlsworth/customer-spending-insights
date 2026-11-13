"""Rebuild posted-balance diagnostics from canonical CSV rows with disk-backed ordering."""

from __future__ import annotations

import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .policy import REFERENCE, month_dates
from .validate import minor, rows, timestamp


def diagnostics(directory: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="csi-balances-") as temporary:
        database = sqlite3.connect(Path(temporary) / "balances.sqlite")
        try:
            database.executescript("""
                CREATE TABLE accounts(id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
                  persona TEXT NOT NULL, status TEXT NOT NULL, opened TEXT NOT NULL,
                  anchor TEXT NOT NULL, opening INTEGER NOT NULL);
                CREATE TABLE postings(account TEXT NOT NULL, posted TEXT NOT NULL,
                  entry_id TEXT NOT NULL, amount INTEGER NOT NULL);
            """)
            personas = {
                r["customer_id"]: r["primary_persona"]
                for r in rows(directory, "customers.csv")
            }
            with database:
                for record in rows(directory, "accounts.csv"):
                    database.execute(
                        "INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)",
                        (
                            record["account_id"],
                            record["customer_id"],
                            record["account_kind"],
                            personas[record["customer_id"]],
                            record["status"],
                            record["opened_on"],
                            record["balance_anchor_at"],
                            minor(record["opening_balance_minor"]),
                        ),
                    )
                for record in rows(directory, "posted_entries.csv"):
                    timestamp(record["posted_at"])
                    database.execute(
                        "INSERT INTO postings VALUES (?,?,?,?)",
                        (
                            record["account_id"],
                            record["posted_at"],
                            record["entry_id"],
                            minor(record["amount_minor"]),
                        ),
                    )
            database.execute(
                "CREATE INDEX postings_account_date ON postings(account,posted,entry_id)"
            )
            by_account: dict[str, Any] = {}
            by_customer: dict[str, int] = defaultdict(int)
            groups: dict[str, Counter[str]] = defaultdict(Counter)
            query = """SELECT a.id,a.owner,a.kind,a.persona,a.status,a.opened,a.anchor,a.opening,
                p.posted,p.amount FROM accounts a LEFT JOIN postings p ON p.account=a.id
                ORDER BY a.id,p.posted,p.entry_id"""
            cursor = database.execute(query)
            pending = cursor.fetchone()
            while pending is not None:
                account_id, owner, kind, persona, status, opened, anchor, opening = (
                    pending[:8]
                )
                if timestamp(anchor).date() < date.fromisoformat(opened):
                    raise ValueError("Anchor predates account opening")
                balance = opening
                minimum = opening
                month_end: dict[str, str] = {}
                negative_count = 0
                longest_run = run = 0
                for month in month_dates(timestamp(anchor).date(), REFERENCE):
                    next_month = (month.replace(day=28) + timedelta(days=4)).replace(
                        day=1
                    )
                    while (
                        pending is not None
                        and pending[0] == account_id
                        and pending[8] is not None
                        and pending[8][:7] < next_month.strftime("%Y-%m")
                    ):
                        if pending[8] < anchor:
                            raise ValueError("Posting predates opening anchor")
                        balance += pending[9]
                        minimum = min(minimum, balance)
                        pending = cursor.fetchone()
                    month_end[month.strftime("%Y-%m")] = str(balance)
                    if balance < 0:
                        negative_count += 1
                        run += 1
                        longest_run = max(longest_run, run)
                    else:
                        run = 0
                if (
                    pending is not None
                    and pending[0] == account_id
                    and pending[8] is None
                ):
                    pending = cursor.fetchone()
                if pending is not None and pending[0] == account_id:
                    raise ValueError("Posting after reference date")
                by_account[account_id] = {
                    "as_of_minor": str(balance),
                    "running_min_minor": str(minimum),
                    "month_end_minor": month_end,
                    "negative_month_ends": negative_count,
                    "longest_negative_month_end_run": longest_run,
                }
                for group in (f"kind:{kind}", f"persona:{persona}"):
                    groups[group]["accounts"] += 1
                    groups[group]["as_of_minor"] += balance
                    groups[group]["negative_month_ends"] += negative_count
                    groups[group]["prolonged_negative_warnings"] += longest_run >= 3
                if status == "OPEN" and date.fromisoformat(opened) <= REFERENCE:
                    by_customer[owner] += balance
                if pending is None:
                    break
            return {
                "accounts": by_account,
                "combined_customer_minor": {
                    owner: str(by_customer[owner]) if owner in by_customer else None
                    for owner in sorted(personas)
                },
                "groups": {name: dict(value) for name, value in sorted(groups.items())},
                "quality_warnings": sorted(
                    account
                    for account, value in by_account.items()
                    if value["longest_negative_month_end_run"] >= 3
                ),
            }
        finally:
            database.close()
