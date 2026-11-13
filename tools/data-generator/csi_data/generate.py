"""Deterministic synthetic identities, activity and canonical CSV output."""

from __future__ import annotations

import csv
import math
from bisect import insort
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .policy import (
    FILES,
    MERCHANTS,
    OPENING_BALANCE_BANDS,
    PROFILES,
    PURCHASE_AMOUNTS,
    REFERENCE,
    VERSION,
    canonical,
    digest,
    file_digest,
    month_dates,
    policies,
    row,
    stamp,
    stream,
)


def fundable(
    opening: int, events: list[tuple[int, int, int]], when: int, amount: int
) -> bool:
    """Check actual signed postings through the proposed debit and later planned debits."""
    balance = opening
    reached = False
    for posted, _, signed in events:
        if posted >= when and not reached:
            if balance < amount:
                return False
            reached = True
        balance += signed
        if reached and balance < amount:
            return False
    return reached or balance >= amount


def generate(
    profile: str, output: Path, *, chunk_size: int = 1000, seed: int | None = None
) -> dict[str, Any]:
    if profile not in PROFILES or chunk_size < 1:
        raise ValueError("Unsupported profile or chunk size")
    params = dict(PROFILES[profile])
    if seed is not None:
        if seed < 0:
            raise ValueError("Seed must be non-negative")
        params["seed"] = seed
    output.mkdir(parents=True, exist_ok=False)
    tax, cat, policy_hash = policies()
    writers = {}
    handles = {}
    counts = Counter()
    summary = {
        "personas": Counter(),
        "account_counts": Counter(),
        "modifiers": Counter(),
        "transaction_types": Counter(),
    }
    high_posted = 0
    try:
        for name, columns in FILES.items():
            handle = (output / name).open("w", encoding="utf-8", newline="")
            handles[name] = handle
            writers[name] = csv.writer(
                handle, lineterminator="\n", quoting=csv.QUOTE_MINIMAL
            )
            writers[name].writerow(columns)
        for number, (code, label) in enumerate(cat["categories"].items(), 1):
            row(writers["categories.csv"], (code, label, number, cat["version"]))
            counts["categories.csv"] += 1
        for merchant_id, label, mcc, category, variant in MERCHANTS:
            row(writers["merchants.csv"], (merchant_id, label, mcc, category, variant))
            counts["merchants.csv"] += 1
        for index in range(params["customers"]):
            identity_rng = stream(params["seed"], index, "identity")
            activity_rng = stream(params["seed"], index, "activity")
            relation_rng = stream(params["seed"], index, "relations")
            balance_rng = stream(params["seed"], index, "opening-balances")
            if profile == "demo":
                persona = (["STUDENT"] * 4 + ["SALARIED"] * 10 + ["FREELANCER"] * 6)[
                    index
                ]
                high = index in (18, 19)
                no_accounts = index == 0
                empty = index == 1
                pending_only = index == 2
                dormant = index == 3
                recent = index == 4
                account_count = (
                    0
                    if no_accounts
                    else 4
                    if index == 5
                    else 2
                    if index in (6, 7, 18, 19)
                    else 1
                )
            else:
                persona = identity_rng.choices(
                    ["STUDENT", "SALARIED", "FREELANCER"], [20, 60, 20]
                )[0]
                high = identity_rng.random() < 0.01
                dormant = identity_rng.random() < 0.05
                recent = identity_rng.random() < 0.05
                empty = pending_only = no_accounts = False
                account_count = 2 if identity_rng.random() < 0.25 else 1
            modifiers = [
                name
                for name, condition in (
                    ("HIGH_ACTIVITY", high),
                    ("DORMANT", dormant),
                    ("NEW", recent),
                    ("MULTI_ACCOUNT", account_count > 1),
                )
                if condition
            ]
            customer_id = f"cu_{index:05d}"
            row(
                writers["customers.csv"],
                (
                    customer_id,
                    f"Synthetic Customer {index + 1:05d}",
                    f"synthetic-{index + 1:05d}",
                    "ACTIVE",
                    persona,
                    "{" + ",".join(modifiers) + "}",
                    0,
                ),
            )
            counts["customers.csv"] += 1
            summary["personas"][persona] += 1
            summary["account_counts"][str(account_count)] += 1
            summary["modifiers"].update(modifiers)
            accounts = []
            openings = {}
            start = date.fromisoformat(params["start"])
            opened = date(2026, 9, 1) if recent else start
            for account_number in range(account_count):
                account_id = f"ac_{index:05d}_{account_number}"
                kind = (
                    "EVERYDAY"
                    if account_number == 0
                    else "SAVINGS"
                    if account_number == 1
                    else "SECONDARY_TRANSACTIONAL"
                )
                lower, upper = OPENING_BALANCE_BANDS[kind]
                opening_balance = balance_rng.randint(lower, upper)
                if profile == "demo" and index == 1 and account_number == 0:
                    opening_balance = 0
                row(
                    writers["accounts.csv"],
                    (
                        account_id,
                        customer_id,
                        kind,
                        ("Everyday", "Savings", "Secondary", "Additional")[
                            account_number
                        ],
                        f"{(index * 13 + account_number) % 10000:04d}",
                        "ZAR",
                        opened.isoformat(),
                        "OPEN",
                        stamp(opened, 0),
                        opening_balance,
                    ),
                )
                counts["accounts.csv"] += 1
                accounts.append(account_id)
                openings[account_id] = opening_balance
            if not accounts:
                continue
            sequence = 0
            funding_events: dict[str, list[tuple[int, int, int]]] = (
                {account: [] for account in accounts}
                if persona == "STUDENT" or len(accounts) > 2
                else {}
            )

            def can_fund(account: str, day: date, hour: int, amount: int) -> bool:
                return account not in funding_events or fundable(
                    openings[account],
                    funding_events[account],
                    day.toordinal() * 24 + hour,
                    amount,
                )

            def entry(
                account: str,
                day: date,
                kind: str,
                amount: int,
                description: str,
                category: str | None = None,
                provenance: str = "NOT_APPLICABLE",
                merchant: str | None = None,
                original: str | None = None,
                auth: str | None = None,
                group: str | None = None,
                hour: int = 12,
            ) -> str:
                nonlocal sequence
                sequence += 1
                entry_id = f"pe_{index:05d}_{sequence:07d}"
                rule = tax["types"][kind]
                if (amount > 0) != (rule["sign"] == "POSITIVE") or (
                    category is None
                ) != (rule["effect"] != "SPEND"):
                    raise ValueError("Generated entry violates the financial policy")
                row(
                    writers["posted_entries.csv"],
                    (
                        entry_id,
                        account,
                        f"gen:entry:{entry_id}",
                        amount,
                        "ZAR",
                        kind,
                        rule["effect"],
                        stamp(day, hour),
                        stamp(day, hour),
                        description,
                        merchant,
                        category,
                        provenance,
                        original,
                        auth,
                        group,
                    ),
                )
                counts["posted_entries.csv"] += 1
                summary["transaction_types"][kind] += 1
                if account in funding_events:
                    insort(
                        funding_events[account],
                        (day.toordinal() * 24 + hour, sequence, amount),
                    )
                return entry_id

            if empty:
                continue
            if pending_only:
                auth_id = f"au_{index:05d}_0001"
                row(
                    writers["authorizations.csv"],
                    (
                        auth_id,
                        accounts[0],
                        25000,
                        stamp(REFERENCE, 10),
                        "PENDING",
                        MERCHANTS[0][0],
                        "Cedar Market pending",
                        f"gen:auth:{auth_id}",
                    ),
                )
                counts["authorizations.csv"] += 1
                continue
            payday = identity_rng.randint(20, 28)
            base_salary = identity_rng.randint(600000, 4500000)
            has_rent = identity_rng.random() < 0.7
            base_rent = round(base_salary * identity_rng.uniform(0.18, 0.38))
            base_connectivity = identity_rng.randint(4000, 90000)
            activity_rate = (
                params["high_rate"] if high else params["ordinary_rate"]
            ) * identity_rng.uniform(0.8, 1.2)
            for month in month_dates(opened, REFERENCE):
                next_month = (month + timedelta(days=32)).replace(day=1)
                last = min(REFERENCE, next_month - timedelta(days=1))
                available = (last - max(month, opened)).days + 1
                if available <= 0 or (dormant and month.month not in (1, 7)):
                    continue
                if (
                    persona == "SALARIED"
                    and month.day <= payday <= last.day
                    and (last - month).days >= payday - 1
                ):
                    salary_amount = base_salary + activity_rng.randint(-15000, 15000)
                    salary_id = entry(
                        accounts[0],
                        month.replace(day=payday),
                        "SALARY_CREDIT",
                        salary_amount,
                        "Synthetic salary",
                    )
                    if (
                        profile == "demo" and index == 7 and month == date(2025, 5, 1)
                    ) or relation_rng.random() < 0.001:
                        entry(
                            accounts[0],
                            month.replace(day=payday) + timedelta(days=1),
                            "INCOME_REVERSAL",
                            -salary_amount,
                            "Synthetic salary correction",
                            original=salary_id,
                        )
                elif persona == "STUDENT":
                    for _ in range(activity_rng.randint(0, 2)):
                        entry(
                            accounts[0],
                            month.replace(day=min(25, last.day)),
                            "ALLOWANCE_CREDIT",
                            activity_rng.randint(50000, 500000),
                            "Synthetic allowance",
                        )
                else:
                    for _ in range(activity_rng.randint(0, 6)):
                        day = month + timedelta(days=activity_rng.randrange(available))
                        entry(
                            accounts[0],
                            day,
                            "EXTERNAL_RECEIPT",
                            min(
                                2500000,
                                max(
                                    50000,
                                    round(
                                        activity_rng.lognormvariate(
                                            math.log(base_salary / 3), 0.6
                                        )
                                    ),
                                ),
                            ),
                            "Synthetic freelance receipt",
                        )
                if persona != "STUDENT" and has_rent and available > 5:
                    entry(
                        accounts[0],
                        month + timedelta(days=2),
                        "DEBIT_ORDER",
                        -round(base_rent * activity_rng.uniform(0.98, 1.02)),
                        "Synthetic rent",
                        "HOUSING_UTILITIES",
                        "OBLIGATION",
                    )
                if available > 10:
                    connectivity_day = month + timedelta(days=8)
                    connectivity = round(
                        base_connectivity * activity_rng.uniform(0.98, 1.02)
                    )
                    if can_fund(accounts[0], connectivity_day, 12, connectivity):
                        entry(
                            accounts[0],
                            connectivity_day,
                            "DEBIT_ORDER",
                            -connectivity,
                            "Synthetic connectivity",
                            "SUBSCRIPTIONS_COMMS",
                            "OBLIGATION",
                        )
                if len(accounts) > 1 and available > 12 and activity_rng.random() < 0.4:
                    entry(
                        accounts[1],
                        month + timedelta(days=11),
                        "INTEREST_CREDIT",
                        activity_rng.randint(50, 3500),
                        "Synthetic savings interest",
                    )
                days = list(range(available))
                activity_rng.shuffle(days)
                target = round(activity_rate * available / (next_month - month).days)
                for event_index in range(max(0, target)):
                    day = max(month, opened) + timedelta(
                        days=days[event_index % available]
                    )
                    force_card = (
                        profile == "demo"
                        and index == 5
                        and month == date(2025, 5, 1)
                        and event_index < 2
                    )
                    activity_kind = activity_rng.random()
                    if not force_card and activity_kind < 0.012:
                        amount = activity_rng.randrange(10000, 300001, 5000)
                        if can_fund(accounts[0], day, 12, amount):
                            entry(
                                accounts[0],
                                day,
                                "CASH_WITHDRAWAL",
                                -amount,
                                "Synthetic ATM withdrawal",
                                "CASH_WITHDRAWALS",
                                "TYPE_RULE",
                            )
                        continue
                    if not force_card and activity_kind < 0.03:
                        amount = activity_rng.randint(5000, 500000)
                        if can_fund(accounts[0], day, 12, amount):
                            entry(
                                accounts[0],
                                day,
                                "EXTERNAL_PAYMENT",
                                -amount,
                                "Synthetic external payment",
                                "MONEY_SENT",
                                "TYPE_RULE",
                            )
                        continue
                    merchant_id, label, mcc, default_category, variant = MERCHANTS[
                        activity_rng.randrange(len(MERCHANTS))
                    ]
                    category = default_category or (
                        "GROCERIES" if mcc == "5411" else "UNCATEGORIZED"
                    )
                    provenance = (
                        "MERCHANT"
                        if default_category
                        else "MCC"
                        if mcc == "5411"
                        else "UNCATEGORIZED"
                    )
                    mu, sigma, minimum, maximum = PURCHASE_AMOUNTS.get(
                        category, (10.2, 0.8, 1000, 300000)
                    )
                    purchase_scale = (
                        0.08 if high else 0.5 if persona == "STUDENT" else 1.0
                    )
                    amount = -min(
                        maximum,
                        max(
                            minimum,
                            round(
                                activity_rng.lognormvariate(mu, sigma) * purchase_scale
                            ),
                        ),
                    )
                    description = (
                        variant if variant and activity_rng.random() < 0.4 else label
                    )
                    purchase_account = (
                        accounts[-1]
                        if len(accounts) > 2 and activity_rng.random() < 0.12
                        else accounts[0]
                    )
                    purchase_hour = 10 + event_index % 9
                    if purchase_account == accounts[-1] and len(accounts) > 2:
                        if not can_fund(purchase_account, day, purchase_hour, -amount):
                            transfer_amount = max(-amount, 100000)
                            if not can_fund(accounts[0], day, 9, transfer_amount):
                                transfer_amount = -amount
                            if can_fund(accounts[0], day, 9, transfer_amount):
                                group = f"tg_{index:05d}_{sequence + 1:07d}"
                                entry(
                                    accounts[0],
                                    day,
                                    "OWN_TRANSFER_OUT",
                                    -transfer_amount,
                                    "Own transfer",
                                    group=group,
                                    hour=9,
                                )
                                entry(
                                    purchase_account,
                                    day,
                                    "OWN_TRANSFER_IN",
                                    transfer_amount,
                                    "Own transfer",
                                    group=group,
                                    hour=9,
                                )
                            else:
                                purchase_account = accounts[0]
                    if not can_fund(purchase_account, day, purchase_hour, -amount):
                        continue
                    auth_id = None
                    if (
                        force_card and event_index == 1
                    ) or relation_rng.random() < 0.01:
                        auth_id = (
                            f"au_{index:05d}_{counts['authorizations.csv'] + 1:07d}"
                        )
                        row(
                            writers["authorizations.csv"],
                            (
                                auth_id,
                                purchase_account,
                                -amount + relation_rng.randint(0, 500),
                                stamp(day, 9),
                                "POSTED",
                                merchant_id,
                                description + " authorization",
                                f"gen:auth:{auth_id}",
                            ),
                        )
                        counts["authorizations.csv"] += 1
                    purchase = entry(
                        purchase_account,
                        day,
                        "CARD_PURCHASE",
                        amount,
                        description,
                        category,
                        provenance,
                        merchant_id,
                        auth=auth_id,
                        hour=purchase_hour,
                    )
                    if day < REFERENCE and (
                        (force_card and event_index == 0)
                        or relation_rng.random() < 0.002
                    ):
                        entry(
                            purchase_account,
                            day + timedelta(days=1),
                            "SPEND_REVERSAL",
                            -amount,
                            description + " reversal",
                            category,
                            provenance,
                            merchant_id,
                            original=purchase,
                        )
                    elif relation_rng.random() < 0.012 and day < REFERENCE:
                        refund_day = min(
                            REFERENCE, day + timedelta(days=relation_rng.randint(1, 14))
                        )
                        if refund_day > day:
                            entry(
                                purchase_account,
                                refund_day,
                                "SPEND_REFUND",
                                relation_rng.randint(1, -amount),
                                description + " refund",
                                category,
                                provenance,
                                merchant_id,
                                original=purchase,
                            )
                if available > 15 and activity_rng.random() < 0.55:
                    entry(
                        accounts[0],
                        month + timedelta(days=14),
                        "BANK_FEE",
                        -activity_rng.randint(500, 8500),
                        "Synthetic account fee",
                        "BANK_FEES",
                        "TYPE_RULE",
                    )
                cross_month = (
                    profile == "demo" and index == 6 and month == date(2025, 10, 1)
                )
                if (
                    len(accounts) > 1
                    and available > 12
                    and (cross_month or activity_rng.random() < 0.6)
                ):
                    transfer_day = last if cross_month else month + timedelta(days=11)
                    amount = activity_rng.randint(10000, 200000)
                    if can_fund(accounts[0], transfer_day, 12, amount):
                        group = f"tg_{index:05d}_{month:%Y%m}"
                        entry(
                            accounts[0],
                            transfer_day,
                            "OWN_TRANSFER_OUT",
                            -amount,
                            "Own transfer",
                            group=group,
                        )
                        in_day = (
                            transfer_day + timedelta(days=1)
                            if cross_month
                            else transfer_day
                        )
                        entry(
                            accounts[1],
                            in_day,
                            "OWN_TRANSFER_IN",
                            amount,
                            "Own transfer",
                            group=group,
                        )
            if profile == "demo" or activity_rng.random() < 0.05:
                for state in ("PENDING", "CANCELLED"):
                    auth_id = f"au_{index:05d}_{counts['authorizations.csv'] + 1:07d}"
                    row(
                        writers["authorizations.csv"],
                        (
                            auth_id,
                            accounts[0],
                            activity_rng.randint(1000, 300000),
                            stamp(REFERENCE, 10),
                            state,
                            MERCHANTS[0][0],
                            "Synthetic card authorization",
                            f"gen:auth:{auth_id}",
                        ),
                    )
                    counts["authorizations.csv"] += 1
            if high:
                high_posted += sequence
            if (index + 1) % chunk_size == 0:
                for handle in handles.values():
                    handle.flush()
    finally:
        for handle in handles.values():
            handle.close()
    hashes = {name: file_digest(output / name) for name in FILES}
    config_hash = digest(canonical(params))
    seed_hash = digest(
        canonical(
            {"files": hashes, "config_hash": config_hash, "policy_hash": policy_hash}
        )
    )
    manifest = {
        "dataset_id": f"synthetic-{profile}-{seed_hash[:20]}",
        "seed_content_hash": seed_hash,
        "generator_version": VERSION,
        "profile": profile,
        "master_seed": params["seed"],
        "fixed_reference_date": REFERENCE.isoformat(),
        "timezone": "Africa/Johannesburg",
        "transaction_policy_version": tax["version"],
        "category_policy_version": cat["version"],
        "parameters": params,
        "config_hash": config_hash,
        "policy_hash": policy_hash,
        "file_counts": dict(counts),
        "file_sha256": hashes,
        "instance_epoch": None,
        "customer_data_revision": 0,
        "scenario_coverage": None,
        "distribution_summaries": {key: dict(value) for key, value in summary.items()},
        "high_activity_posted_entries": high_posted,
        "metadata_missingness": {
            "merchant_mcc": sum(mcc is None for _, _, mcc, _, _ in MERCHANTS),
            "merchant_category": sum(
                category is None for _, _, _, category, _ in MERCHANTS
            ),
            "merchant_descriptor_variant": sum(
                variant is None for _, _, _, _, variant in MERCHANTS
            ),
        },
        "independent_expected_results": "contracts/finance/fixtures.json",
    }
    from .balances import diagnostics
    from .validate import validate_rows

    manifest["scenario_coverage"] = validate_rows(output)
    manifest["balance_diagnostics"] = diagnostics(output)
    (output / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest
