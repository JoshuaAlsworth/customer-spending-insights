"""Canonical synthetic CSV generation and manifest verification."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
POLICY_FILES = ("taxonomy.json", "categories.json")
FILES = {
    "customers.csv": (
        "customer_id",
        "display_name",
        "login_id",
        "status",
        "primary_persona",
        "modifiers",
        "customer_revision",
    ),
    "accounts.csv": (
        "account_id",
        "customer_id",
        "account_kind",
        "alias",
        "masked_suffix",
        "currency",
        "opened_on",
        "status",
        "balance_anchor_at",
        "opening_balance_minor",
    ),
    "merchants.csv": (
        "merchant_id",
        "display_name",
        "mcc",
        "default_category_code",
        "descriptor_variant",
    ),
    "categories.csv": (
        "category_code",
        "display_name",
        "display_order",
        "policy_version",
    ),
    "authorizations.csv": (
        "authorization_id",
        "account_id",
        "authorized_amount_minor",
        "occurred_at",
        "lifecycle_status",
        "merchant_id",
        "raw_description",
        "source_event_id",
    ),
    "posted_entries.csv": (
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
        "merchant_id",
        "category_code",
        "classification_provenance",
        "original_entry_id",
        "authorization_id",
        "transfer_group_id",
    ),
}
MERCHANTS = (
    ("cedar-market", "Cedar Market", "5411", "GROCERIES", "CEDAR MARKET CPT"),
    ("citylink-fuel", "Citylink Fuel", "5541", "TRANSPORT_FUEL", "CITYLINK FUEL 014"),
    ("harbor-cafe", "Harbor Café", "5812", "FOOD_DINING", None),
    ("oak-home", "Oak Home Store", "5311", "SHOPPING", "OAK HOME ONLINE"),
    ("blue-pharmacy", "Blue Pharmacy", "5912", "HEALTH", None),
    ("river-books", "River Books", "5942", "EDUCATION", None),
    ("bay-cinema", "Bay Cinema", "7832", "ENTERTAINMENT_LEISURE", None),
    ("fern-mobile", "Fern Mobile", "4814", "SUBSCRIPTIONS_COMMS", None),
    ("willow-food", "Willow Food Shop", "5411", None, None),
    ("cloud-kiosk", "Cloud Kiosk", None, None, None),
)
PURCHASE_AMOUNTS = {
    "GROCERIES": (10.9, 0.6, 1000, 300000),
    "TRANSPORT_FUEL": (10.4, 0.65, 1000, 250000),
    "FOOD_DINING": (10.0, 0.8, 1000, 180000),
    "SHOPPING": (10.5, 0.9, 1000, 300000),
    "HEALTH": (10.2, 0.8, 1000, 300000),
}
UTC2 = timezone(timedelta(hours=2))
VERSION = "1.1.0"
OPENING_BALANCE_BANDS = {
    "EVERYDAY": (0, 3_000_000),
    "SAVINGS": (0, 10_000_000),
    "SECONDARY_TRANSACTIONAL": (0, 2_000_000),
}
PROFILES = {
    "demo": {
        "seed": 20261031,
        "start": "2025-05-01",
        "customers": 20,
        "ordinary_rate": 21,
        "high_rate": 170,
    },
    "benchmark": {
        "seed": 20261032,
        "start": "2024-11-01",
        "customers": 3000,
        "ordinary_rate": 10,
        "high_rate": 120,
    },
}
REFERENCE = date(2026, 10, 31)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def policies() -> tuple[dict[str, Any], dict[str, Any], str]:
    paths = [ROOT / "contracts/finance" / name for name in POLICY_FILES]
    tax, cat = (json.loads(path.read_text()) for path in paths)
    if len(tax["types"]) != 16 or len(cat["categories"]) != 14:
        raise ValueError("Unsupported financial policy catalogue")
    return (
        tax,
        cat,
        digest(
            canonical(
                {
                    name: json.loads(path.read_text())
                    for name, path in zip(POLICY_FILES, paths, strict=True)
                }
            )
        ),
    )


def stream(seed: int, customer: int, stage: str) -> random.Random:
    material = canonical([seed, customer, stage, VERSION])
    return random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))


def stamp(day: date, hour: int, minute: int = 0) -> str:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC2).isoformat(
        timespec="seconds"
    )


def month_dates(start: date, end: date):
    current = start.replace(day=1)
    while current <= end:
        yield current
        current = (current + timedelta(days=32)).replace(day=1)


def row(writer: csv.writer, values: tuple[Any, ...]) -> None:
    writer.writerow(tuple("\\N" if value is None else value for value in values))
