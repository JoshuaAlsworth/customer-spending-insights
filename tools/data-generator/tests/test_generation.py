import csv
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from csi_data.generate import generate
from csi_data.manifest import verify_files
from csi_data.policy import FILES, canonical, stream
from csi_data.validate import validate_rows


def rewrite(path: Path, change):
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        records = list(reader)
    change(records)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    output = tmp_path_factory.mktemp("seed") / "demo"
    generate("demo", output)
    return output


def test_independent_runs_and_chunk_sizes_match_exact_bytes(tmp_path, demo):
    second = tmp_path / "second"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "csi_data",
            "generate",
            "demo",
            str(second),
            "--chunk-size",
            "7",
        ],
        check=True,
        capture_output=True,
    )
    for name in FILES:
        assert (demo / name).read_bytes() == (second / name).read_bytes()
    assert (demo / "manifest.json").read_bytes() == (
        second / "manifest.json"
    ).read_bytes()
    assert verify_files(demo) == verify_files(second)


def test_seed_change_changes_identity(tmp_path, demo):
    changed = generate("demo", tmp_path / "changed", seed=20261030)
    assert changed["seed_content_hash"] != verify_files(demo)["seed_content_hash"]
    assert (
        stream(20261031, 5, "activity").random()
        != stream(20261031, 5, "identity").random()
    )
    assert (
        stream(20261031, 5, "activity").random()
        == stream(20261031, 5, "activity").random()
    )


def test_demo_scenarios_and_policy(demo):
    manifest = verify_files(demo)
    assert manifest["file_counts"]["customers.csv"] == 20
    assert 11000 <= manifest["file_counts"]["posted_entries.csv"] <= 14000
    assert manifest["distribution_summaries"]["personas"] == {
        "STUDENT": 4,
        "SALARIED": 10,
        "FREELANCER": 6,
    }
    with (demo / "accounts.csv").open() as handle:
        accounts = list(csv.DictReader(handle))
    owner_counts = Counter(account["customer_id"] for account in accounts)
    assert owner_counts["cu_00000"] == 0
    assert owner_counts["cu_00005"] == 4
    with (demo / "posted_entries.csv").open() as handle:
        entries = list(csv.DictReader(handle))
    assert all(entry["account_id"] != "ac_00001_0" for entry in entries)
    assert all(entry["account_id"] != "ac_00002_0" for entry in entries)
    assert (
        sum(
            entry["entry_id"].startswith(("pe_00018_", "pe_00019_"))
            for entry in entries
        )
        >= 5500
    )
    generated_types = {entry["transaction_type"] for entry in entries}
    assert {
        "SPEND_REFUND",
        "SPEND_REVERSAL",
        "INCOME_REVERSAL",
        "INTEREST_CREDIT",
        "CASH_WITHDRAWAL",
        "EXTERNAL_PAYMENT",
    } <= generated_types
    assert any(entry["authorization_id"] != "\\N" for entry in entries)
    assert any(
        entry["classification_provenance"] == "MCC"
        and entry["category_code"] == "GROCERIES"
        for entry in entries
    )
    assert any(
        entry["classification_provenance"] == "UNCATEGORIZED"
        and entry["category_code"] == "UNCATEGORIZED"
        for entry in entries
    )
    assert 5500 <= manifest["high_activity_posted_entries"] <= 7500
    assert manifest["scenario_coverage"]["refund_only_category_periods"] > 0
    assert manifest["scenario_coverage"]["high_activity_customers"] == 2
    crossing = [
        entry for entry in entries if entry["transfer_group_id"] == "tg_00006_202510"
    ]
    assert len(crossing) == 2
    assert {entry["posted_at"][:7] for entry in crossing} == {"2025-10", "2025-11"}
    assert all(entry["source_event_id"].startswith("gen:entry:") for entry in entries)
    assert all(entry["amount_minor"] != "0" for entry in entries)
    with (demo / "authorizations.csv").open() as handle:
        auth = list(csv.DictReader(handle))
    assert any(
        item["account_id"] == "ac_00002_0" and item["lifecycle_status"] == "PENDING"
        for item in auth
    )
    assert all(item["source_event_id"].startswith("gen:auth:") for item in auth)
    assert any(item["lifecycle_status"] == "POSTED" for item in auth)
    assert manifest["file_sha256"] == {
        name: __import__("hashlib").sha256((demo / name).read_bytes()).hexdigest()
        for name in FILES
    }
    assert (
        canonical(json.loads((demo / "manifest.json").read_text())) + b"\n"
        == (demo / "manifest.json").read_bytes()
    )


def test_tampered_file_rejected(tmp_path, demo):
    copied = tmp_path / "tampered"
    shutil.copytree(demo, copied)
    with (copied / "customers.csv").open("ab") as handle:
        handle.write(b"extra\n")
    with pytest.raises(ValueError, match="Count mismatch|Seed hash mismatch|Malformed"):
        verify_files(copied)


@pytest.mark.parametrize(
    "mutation", ["duplicate_event", "missing_transfer", "invalid_refund"]
)
def test_invalid_relationships_rejected(tmp_path, demo, mutation):
    copied = tmp_path / mutation
    shutil.copytree(demo, copied)
    entry_file = copied / "posted_entries.csv"
    if mutation == "duplicate_event":
        with (copied / "authorizations.csv").open() as handle:
            source = next(csv.DictReader(handle))["source_event_id"]
        rewrite(entry_file, lambda rows: rows[0].update(source_event_id=source))
    elif mutation == "missing_transfer":
        rewrite(
            entry_file,
            lambda rows: rows.__setitem__(
                slice(None),
                [row for row in rows if row["transaction_type"] != "OWN_TRANSFER_IN"],
            ),
        )
    else:

        def change(rows):
            refund = next(
                row
                for row in rows
                if row["transaction_type"] == "SPEND_REFUND"
                and any(
                    candidate["transaction_type"] == "BANK_FEE"
                    and candidate["account_id"] == row["account_id"]
                    for candidate in rows
                )
            )
            original = next(
                row
                for row in rows
                if row["transaction_type"] == "BANK_FEE"
                and row["account_id"] == refund["account_id"]
            )
            refund["original_entry_id"] = original["entry_id"]

        rewrite(entry_file, change)
    with pytest.raises(ValueError):
        validate_rows(copied)


def test_policy_and_configuration_mismatch_rejected(tmp_path, demo):
    copied = tmp_path / "wrong-policy"
    shutil.copytree(demo, copied)
    manifest_path = copied / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["transaction_policy_version"] = "unsupported"
    manifest_path.write_bytes(canonical(manifest) + b"\n")
    with pytest.raises(ValueError, match="policy"):
        verify_files(copied)
    manifest["transaction_policy_version"] = "CSI-TAX-1.0"
    manifest["fixed_reference_date"] = "2026-11-01"
    manifest_path.write_bytes(canonical(manifest) + b"\n")
    with pytest.raises(ValueError, match="configuration"):
        verify_files(copied)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_account",
        "before_opening",
        "over_refund",
        "bad_authorization",
        "bad_provenance",
    ],
)
def test_invalid_financial_rows_rejected(tmp_path, demo, mutation):
    copied = tmp_path / mutation
    shutil.copytree(demo, copied)

    def change(rows):
        if mutation == "wrong_account":
            rows[0]["account_id"] = "unknown-account"
        elif mutation == "before_opening":
            rows[0]["posted_at"] = "2024-01-01T10:00:00+02:00"
        elif mutation == "over_refund":
            refund = next(
                row for row in rows if row["transaction_type"] == "SPEND_REFUND"
            )
            refund["amount_minor"] = "999999999"
        elif mutation == "bad_authorization":
            purchase = next(
                row
                for row in rows
                if row["transaction_type"] == "CARD_PURCHASE"
                and row["authorization_id"] == "\\N"
            )
            purchase["authorization_id"] = "missing-authorization"
        else:
            purchase = next(
                row for row in rows if row["transaction_type"] == "CARD_PURCHASE"
            )
            purchase["classification_provenance"] = "TYPE_RULE"

    rewrite(copied / "posted_entries.csv", change)
    with pytest.raises(ValueError):
        validate_rows(copied)


@pytest.mark.parametrize(
    "claim,wrong",
    [
        ("zero_accounts", False),
        ("empty_account", False),
        ("pending_only", False),
        ("four_accounts", False),
        ("cross_month_transfer", False),
        ("refund_only_category_periods", 0),
        ("dormant_customer", False),
        ("newly_opened_account", False),
        ("high_activity_customers", 0),
    ],
)
def test_fabricated_scenario_claim_rejected(tmp_path, demo, claim, wrong):
    copied = tmp_path / claim
    shutil.copytree(demo, copied)
    manifest_path = copied / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["scenario_coverage"][claim] = wrong
    manifest_path.write_bytes(canonical(manifest) + b"\n")
    with pytest.raises(ValueError, match="scenario|summary"):
        verify_files(copied)


@pytest.mark.parametrize("change", ["missing", "unsupported"])
def test_scenario_inventory_rejected(tmp_path, demo, change):
    copied = tmp_path / change
    shutil.copytree(demo, copied)
    manifest_path = copied / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if change == "missing":
        del manifest["scenario_coverage"]["four_accounts"]
    else:
        manifest["scenario_coverage"]["invented"] = True
    manifest_path.write_bytes(canonical(manifest) + b"\n")
    with pytest.raises(ValueError, match="scenario"):
        verify_files(copied)


def test_absent_scenario_is_observed_as_false(tmp_path, demo):
    copied = tmp_path / "no-zero-account-customer"
    shutil.copytree(demo, copied)
    with (copied / "accounts.csv").open("a", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            (
                "ac_00000_0",
                "cu_00000",
                "EVERYDAY",
                "Everyday",
                "0000",
                "ZAR",
                "2025-05-01",
                "OPEN",
            )
        )
    assert validate_rows(copied)["zero_accounts"] is False
