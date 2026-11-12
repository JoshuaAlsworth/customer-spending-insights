"""Streaming, disk-backed validation before any database mutation."""

from __future__ import annotations

import csv
import re
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path

from .policy import FILES, REFERENCE, policies

INTEGER = re.compile(r"(?:0|[1-9][0-9]*|-[1-9][0-9]*)\Z")


def fail(message: str) -> None:
    raise ValueError(message)


def rows(directory: Path, name: str):
    with (directory / name).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        if tuple(reader.fieldnames or ()) != FILES[name]:
            fail(f"Invalid {name} header")
        for line, record in enumerate(reader, 2):
            if None in record or any(value is None for value in record.values()):
                fail(f"Invalid {name} row {line}")
            yield record


def required(record: dict[str, str], *keys: str) -> None:
    if any(record[key] in ("", "\\N") for key in keys):
        fail(f"Missing required {keys}")


def minor(value: str) -> int:
    if not INTEGER.fullmatch(value):
        fail("Noncanonical minor-unit amount")
    amount = int(value)
    if amount < -(2**63) or amount > 2**63 - 1:
        fail("Minor-unit amount exceeds BIGINT")
    return amount


def timestamp(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+02:00", value):
        fail("Noncanonical timestamp")
    return datetime.fromisoformat(value)


def validate_rows(directory: Path) -> dict[str, bool | int]:
    tax, cat, _ = policies()
    with tempfile.TemporaryDirectory(prefix="csi-validation-") as temporary:
        database = sqlite3.connect(Path(temporary) / "validation.sqlite")
        try:
            database.executescript("""
                CREATE TABLE customers(id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE, modifiers TEXT NOT NULL);
                CREATE TABLE accounts(id TEXT PRIMARY KEY, owner TEXT NOT NULL, opened TEXT NOT NULL);
                CREATE TABLE authorizations(id TEXT PRIMARY KEY, account TEXT NOT NULL, status TEXT NOT NULL, occurred TEXT NOT NULL, links INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE entries(id TEXT PRIMARY KEY, account TEXT NOT NULL, owner TEXT NOT NULL, type TEXT NOT NULL, effect TEXT NOT NULL, amount INTEGER NOT NULL, category TEXT, provenance TEXT, posted TEXT NOT NULL, compensated INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE events(id TEXT PRIMARY KEY);
                CREATE TABLE transfers(id TEXT PRIMARY KEY, owner TEXT NOT NULL, first_account TEXT NOT NULL, amount INTEGER NOT NULL, kind TEXT NOT NULL, first_month TEXT NOT NULL, cross_month INTEGER NOT NULL DEFAULT 0, legs INTEGER NOT NULL DEFAULT 1);
            """)
            with database:
                for record in rows(directory, "customers.csv"):
                    required(
                        record,
                        "customer_id",
                        "display_name",
                        "login_id",
                        "status",
                        "primary_persona",
                    )
                    if record["customer_revision"] != "0" or record[
                        "primary_persona"
                    ] not in ("STUDENT", "SALARIED", "FREELANCER"):
                        fail("Invalid initial customer")
                    database.execute(
                        "INSERT INTO customers VALUES (?,?,?)",
                        (
                            record["customer_id"],
                            record["login_id"],
                            record["modifiers"],
                        ),
                    )
                for record in rows(directory, "accounts.csv"):
                    required(
                        record,
                        "account_id",
                        "customer_id",
                        "account_kind",
                        "alias",
                        "masked_suffix",
                        "currency",
                        "opened_on",
                        "status",
                    )
                    if (
                        record["currency"] != "ZAR"
                        or not database.execute(
                            "SELECT 1 FROM customers WHERE id=?",
                            (record["customer_id"],),
                        ).fetchone()
                    ):
                        fail("Invalid account owner or currency")
                    if (
                        not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["opened_on"])
                        or date.fromisoformat(record["opened_on"]) > REFERENCE
                    ):
                        fail("Invalid account opening date")
                    if (
                        database.execute(
                            "SELECT count(*) FROM accounts WHERE owner=?",
                            (record["customer_id"],),
                        ).fetchone()[0]
                        >= 4
                    ):
                        fail("Customer account limit exceeded")
                    database.execute(
                        "INSERT INTO accounts VALUES (?,?,?)",
                        (
                            record["account_id"],
                            record["customer_id"],
                            record["opened_on"],
                        ),
                    )
                category_codes = set()
                for record in rows(directory, "categories.csv"):
                    if (
                        record["category_code"] not in cat["categories"]
                        or record["display_name"]
                        != cat["categories"][record["category_code"]]
                        or record["policy_version"] != cat["version"]
                        or record["display_order"]
                        != str(
                            list(cat["categories"]).index(record["category_code"]) + 1
                        )
                        or record["category_code"] in category_codes
                    ):
                        fail("Category policy mismatch")
                    category_codes.add(record["category_code"])
                if category_codes != set(cat["categories"]):
                    fail("Incomplete category catalogue")
                merchants = {}
                for record in rows(directory, "merchants.csv"):
                    required(record, "merchant_id", "display_name")
                    if (
                        record["default_category_code"] != "\\N"
                        and record["default_category_code"] not in cat["categories"]
                    ):
                        fail("Unknown merchant category")
                    if record["mcc"] != "\\N" and not re.fullmatch(
                        r"\d{4}", record["mcc"]
                    ):
                        fail("Invalid merchant MCC")
                    if record["merchant_id"] in merchants:
                        fail("Duplicate merchant")
                    merchants[record["merchant_id"]] = (
                        record["default_category_code"],
                        record["mcc"],
                    )
                for record in rows(directory, "authorizations.csv"):
                    required(
                        record,
                        "authorization_id",
                        "account_id",
                        "authorized_amount_minor",
                        "occurred_at",
                        "lifecycle_status",
                        "raw_description",
                        "source_event_id",
                    )
                    if minor(record["authorized_amount_minor"]) <= 0 or record[
                        "lifecycle_status"
                    ] not in ("PENDING", "POSTED", "CANCELLED"):
                        fail("Invalid authorization amount or state")
                    if (
                        record["merchant_id"] != "\\N"
                        and record["merchant_id"] not in merchants
                    ):
                        fail("Unknown authorization merchant")
                    account = database.execute(
                        "SELECT opened FROM accounts WHERE id=?",
                        (record["account_id"],),
                    ).fetchone()
                    occurred = timestamp(record["occurred_at"])
                    if (
                        not account
                        or occurred.date() < date.fromisoformat(account[0])
                        or occurred.date() > REFERENCE
                    ):
                        fail("Authorization account or chronology invalid")
                    database.execute(
                        "INSERT INTO events VALUES (?)", (record["source_event_id"],)
                    )
                    database.execute(
                        "INSERT INTO authorizations(id,account,status,occurred) VALUES (?,?,?,?)",
                        (
                            record["authorization_id"],
                            record["account_id"],
                            record["lifecycle_status"],
                            record["occurred_at"],
                        ),
                    )
                for record in rows(directory, "posted_entries.csv"):
                    required(
                        record,
                        "entry_id",
                        "account_id",
                        "source_event_id",
                        "amount_minor",
                        "currency",
                        "transaction_type",
                        "effect_group",
                        "posted_at",
                        "occurred_at",
                        "raw_description",
                        "classification_provenance",
                    )
                    kind = record["transaction_type"]
                    rule = tax["types"].get(kind)
                    amount = minor(record["amount_minor"])
                    if (
                        not rule
                        or amount == 0
                        or (amount > 0) != (rule["sign"] == "POSITIVE")
                        or record["effect_group"] != rule["effect"]
                        or record["currency"] != "ZAR"
                    ):
                        fail("Invalid type, sign, effect or currency")
                    account = database.execute(
                        "SELECT owner,opened FROM accounts WHERE id=?",
                        (record["account_id"],),
                    ).fetchone()
                    posted, occurred = (
                        timestamp(record["posted_at"]),
                        timestamp(record["occurred_at"]),
                    )
                    if (
                        not account
                        or posted < occurred
                        or posted.date() < date.fromisoformat(account[1])
                        or posted.date() > REFERENCE
                    ):
                        fail("Invalid posting account or chronology")
                    category = (
                        None
                        if record["category_code"] == "\\N"
                        else record["category_code"]
                    )
                    provenance = record["classification_provenance"]
                    if (
                        record["merchant_id"] != "\\N"
                        and record["merchant_id"] not in merchants
                    ):
                        fail("Unknown posting merchant")
                    if rule["effect"] == "SPEND":
                        if (
                            category not in cat["categories"]
                            or provenance not in cat["provenance"]
                            or provenance == "NOT_APPLICABLE"
                        ):
                            fail("Invalid spending classification")
                        if rule["category"] in (
                            "BANK_FEES",
                            "CASH_WITHDRAWALS",
                            "MONEY_SENT",
                        ) and (
                            category != rule["category"] or provenance != "TYPE_RULE"
                        ):
                            fail("Invalid type-rule category")
                        if kind in ("CARD_PURCHASE", "DEBIT_ORDER"):
                            if provenance not in (
                                "OBLIGATION",
                                "MERCHANT",
                                "MCC",
                                "UNCATEGORIZED",
                            ):
                                fail("Unsupported purchase classification provenance")
                            merchant = merchants.get(record["merchant_id"])
                            if provenance == "MERCHANT" and (
                                not merchant or merchant[0] != category
                            ):
                                fail("Merchant classification mismatch")
                            if provenance == "MCC" and (
                                not merchant
                                or merchant[0] != "\\N"
                                or merchant[1] != "5411"
                                or category != "GROCERIES"
                            ):
                                fail("MCC classification mismatch")
                            if provenance == "UNCATEGORIZED" and (
                                category != "UNCATEGORIZED"
                                or (
                                    merchant
                                    and (merchant[0] != "\\N" or merchant[1] == "5411")
                                )
                            ):
                                fail("Unsupported uncategorized classification")
                    elif category is not None or provenance != "NOT_APPLICABLE":
                        fail("Non-spending entry has a category")
                    original_id = record["original_entry_id"]
                    if (original_id != "\\N") != ("original" in rule):
                        fail("Invalid original linkage")
                    if original_id != "\\N":
                        original = database.execute(
                            "SELECT account,owner,type,effect,amount,category,provenance,posted,compensated FROM entries WHERE id=?",
                            (original_id,),
                        ).fetchone()
                        if (
                            not original
                            or original[1] != account[0]
                            or original[7] >= record["posted_at"]
                        ):
                            fail("Invalid compensation ownership or chronology")
                        if kind == "SPEND_REFUND":
                            if (
                                original[2] != "CARD_PURCHASE"
                                or category != original[5]
                                or provenance != original[6]
                                or (
                                    original[8] < 0
                                    or original[8] + amount > -original[4]
                                )
                            ):
                                fail("Invalid refund")
                        elif kind == "SPEND_REVERSAL":
                            if (
                                original[3] != "SPEND"
                                or original[4] >= 0
                                or original[8]
                                or amount != -original[4]
                                or category != original[5]
                                or provenance != original[6]
                            ):
                                fail("Invalid spend reversal")
                        elif kind == "INCOME_REVERSAL":
                            if (
                                original[3] != "INCOME"
                                or original[4] <= 0
                                or original[8]
                                or amount != -original[4]
                            ):
                                fail("Invalid income reversal")
                        else:
                            fail("Fixture-only transfer reversal unsupported")
                        database.execute(
                            "UPDATE entries SET compensated=compensated+? WHERE id=?",
                            (
                                amount
                                if kind == "SPEND_REFUND"
                                else (
                                    -original[4] + 1 if kind == "SPEND_REVERSAL" else -1
                                ),
                                original_id,
                            ),
                        )
                    auth_id = record["authorization_id"]
                    if auth_id != "\\N":
                        auth = database.execute(
                            "SELECT account,status,occurred,links FROM authorizations WHERE id=?",
                            (auth_id,),
                        ).fetchone()
                        if (
                            kind != "CARD_PURCHASE"
                            or not auth
                            or auth[0] != record["account_id"]
                            or auth[1] != "POSTED"
                            or auth[2] > record["posted_at"]
                            or auth[3]
                        ):
                            fail("Invalid authorization completion")
                        database.execute(
                            "UPDATE authorizations SET links=1 WHERE id=?", (auth_id,)
                        )
                    group = record["transfer_group_id"]
                    if (group != "\\N") != (rule["effect"] == "INTERNAL"):
                        fail("Invalid transfer group")
                    if group != "\\N":
                        previous = database.execute(
                            "SELECT owner,first_account,amount,kind,legs FROM transfers WHERE id=?",
                            (group,),
                        ).fetchone()
                        if previous:
                            if (
                                previous[0] != account[0]
                                or previous[1] == record["account_id"]
                                or previous[2] + amount != 0
                                or previous[3] == kind
                                or previous[4] != 1
                                or {previous[3], kind}
                                != {"OWN_TRANSFER_IN", "OWN_TRANSFER_OUT"}
                            ):
                                fail("Invalid transfer pair")
                            database.execute(
                                "UPDATE transfers SET legs=2,cross_month=(first_month<>?) WHERE id=?",
                                (record["posted_at"][:7], group),
                            )
                        else:
                            database.execute(
                                "INSERT INTO transfers(id,owner,first_account,amount,kind,first_month) VALUES (?,?,?,?,?,?)",
                                (
                                    group,
                                    account[0],
                                    record["account_id"],
                                    amount,
                                    kind,
                                    record["posted_at"][:7],
                                ),
                            )
                    database.execute(
                        "INSERT INTO events VALUES (?)", (record["source_event_id"],)
                    )
                    database.execute(
                        "INSERT INTO entries(id,account,owner,type,effect,amount,category,provenance,posted) VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            record["entry_id"],
                            record["account_id"],
                            account[0],
                            kind,
                            rule["effect"],
                            amount,
                            category,
                            provenance,
                            record["posted_at"],
                        ),
                    )
                if (
                    database.execute(
                        "SELECT 1 FROM transfers WHERE legs<>2 LIMIT 1"
                    ).fetchone()
                    or database.execute(
                        "SELECT 1 FROM authorizations WHERE (status='POSTED')<>(links=1) LIMIT 1"
                    ).fetchone()
                ):
                    fail("Incomplete transfer or authorization")
                database.executescript("""
                    CREATE INDEX scenario_accounts_owner ON accounts(owner);
                    CREATE INDEX scenario_entries_account ON entries(account);
                    CREATE INDEX scenario_entries_owner_posted ON entries(owner,posted);
                    CREATE INDEX scenario_authorizations_account_status ON authorizations(account,status);
                """)

                def scalar(query: str) -> int | None:
                    result = database.execute(query).fetchone()
                    return result[0] if result else None

                return {
                    "zero_accounts": bool(
                        scalar(
                            "SELECT 1 FROM customers c WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.owner=c.id) LIMIT 1"
                        )
                    ),
                    "empty_account": bool(
                        scalar(
                            "SELECT 1 FROM accounts a WHERE NOT EXISTS (SELECT 1 FROM entries e WHERE e.account=a.id) AND NOT EXISTS (SELECT 1 FROM authorizations z WHERE z.account=a.id) LIMIT 1"
                        )
                    ),
                    "pending_only": bool(
                        scalar(
                            "SELECT 1 FROM accounts a WHERE NOT EXISTS (SELECT 1 FROM entries e WHERE e.account=a.id) AND EXISTS (SELECT 1 FROM authorizations z WHERE z.account=a.id AND z.status='PENDING') LIMIT 1"
                        )
                    ),
                    "four_accounts": bool(
                        scalar(
                            "SELECT 1 FROM accounts GROUP BY owner HAVING count(*)=4 LIMIT 1"
                        )
                    ),
                    "cross_month_transfer": bool(
                        scalar("SELECT 1 FROM transfers WHERE cross_month=1 LIMIT 1")
                    ),
                    "refund_only_category_periods": scalar(
                        "SELECT count(*) FROM (SELECT account,substr(posted,1,7),category FROM entries WHERE effect='SPEND' GROUP BY account,substr(posted,1,7),category HAVING max(amount>0)=1 AND max(amount<0)=0)"
                    ),
                    "dormant_customer": bool(
                        scalar(
                            "SELECT 1 FROM customers c WHERE c.modifiers LIKE '%DORMANT%' AND NOT EXISTS (SELECT 1 FROM entries e WHERE e.owner=c.id AND substr(e.posted,1,7)='2026-10') LIMIT 1"
                        )
                    ),
                    "newly_opened_account": bool(
                        scalar(
                            "SELECT 1 FROM accounts a JOIN customers c ON c.id=a.owner WHERE c.modifiers LIKE '%NEW%' AND a.opened>='2026-09-01' LIMIT 1"
                        )
                    ),
                    "high_activity_customers": scalar(
                        "SELECT count(*) FROM (SELECT c.id FROM customers c JOIN entries e ON e.owner=c.id WHERE c.modifiers LIKE '%HIGH_ACTIVITY%' GROUP BY c.id HAVING count(*)>=2500)"
                    ),
                }
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Duplicate or invalid identity: {error}") from error
        finally:
            database.close()
