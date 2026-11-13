import csv
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from csi_data.generate import fundable, generate
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


@pytest.fixture(scope="module")
def benchmark(tmp_path_factory):
    output = tmp_path_factory.mktemp("seed") / "benchmark"
    generate("benchmark", output)
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


def test_discretionary_funding_uses_opening_funds_and_posted_income_timing():
    # Positive opening funds support a drawdown before the first allowance.
    opening = 12000
    posted = [(10, 1, -5000), (25, 2, 20000)]
    assert fundable(opening, posted, 9, 6000)
    assert not fundable(opening, posted, 9, 8000)
    assert fundable(opening, posted, 26, 20000)
    # A later recurring obligation cannot be spent twice in advance.
    assert not fundable(opening, [(20, 1, -11000)], 5, 2000)
    # Existing negative activity stays signed; it is not repaired by the check.
    assert not fundable(-1000, [], 5, 100)
    assert fundable(-1000, [(25, 1, 5000)], 26, 3000)


def test_four_account_demo_purchase_account_is_funded(demo):
    with (demo / "posted_entries.csv").open() as handle:
        entries = list(csv.DictReader(handle))
    fourth = "ac_00005_3"
    purchases = [
        item
        for item in entries
        if item["account_id"] == fourth and item["transaction_type"] == "CARD_PURCHASE"
    ]
    credits = [
        item
        for item in entries
        if item["account_id"] == fourth
        and item["transaction_type"] == "OWN_TRANSFER_IN"
    ]
    assert purchases
    assert credits
    groups = {item["transfer_group_id"] for item in credits}
    for group in groups:
        legs = [item for item in entries if item["transfer_group_id"] == group]
        assert len(legs) == 2
        assert {item["account_id"] for item in legs} == {"ac_00005_0", fourth}
        assert sum(int(item["amount_minor"]) for item in legs) == 0
    diagnostics = verify_files(demo)["balance_diagnostics"]["accounts"][fourth]
    assert diagnostics["longest_negative_month_end_run"] < 3


def test_student_income_gaps_keep_funded_activity_without_extreme_deficits(benchmark):
    with (benchmark / "customers.csv").open() as handle:
        students = {
            item["customer_id"]
            for item in csv.DictReader(handle)
            if item["primary_persona"] == "STUDENT"
        }
    with (benchmark / "accounts.csv").open() as handle:
        accounts = {
            item["account_id"]: item
            for item in csv.DictReader(handle)
            if item["customer_id"] in students
        }
    manifest = verify_files(benchmark)
    balances = manifest["balance_diagnostics"]["accounts"]
    allowances = Counter()
    purchases = Counter()
    with (benchmark / "posted_entries.csv").open() as handle:
        for item in csv.DictReader(handle):
            if item["account_id"] not in accounts:
                continue
            key = item["account_id"], item["posted_at"][:7]
            allowances[key] += item["transaction_type"] == "ALLOWANCE_CREDIT"
            purchases[key] += item["transaction_type"] == "CARD_PURCHASE"
    income_gaps = [
        (account, month)
        for account in accounts
        for month in balances[account]["month_end_minor"]
        if allowances[account, month] == 0
    ]
    assert income_gaps
    assert any(purchases[key] for key in income_gaps)
    assert any(not purchases[key] for key in income_gaps)
    assert any(
        any(
            int(month_end) < int(accounts[account]["opening_balance_minor"])
            for month_end in balances[account]["month_end_minor"].values()
        )
        for account in accounts
    )
    student_balances = [balances[account] for account in accounts]
    assert any(int(item["as_of_minor"]) < 0 for item in student_balances)
    # The unbounded baseline had 279 three-month runs and 58 runs of 20+ months.
    assert (
        sum(item["longest_negative_month_end_run"] >= 3 for item in student_balances)
        <= 30
    )
    assert all(item["longest_negative_month_end_run"] < 20 for item in student_balances)


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
                "2025-05-01T00:00:00+02:00",
                "0",
            )
        )
    assert validate_rows(copied)["zero_accounts"] is False


@pytest.mark.parametrize(
    "anchor,opening",
    [
        ("\\N", "0"),
        ("2025-05-01T01:00:00+02:00", "0"),
        ("2025-04-30T00:00:00+02:00", "0"),
        ("2026-11-01T00:00:00+02:00", "0"),
        ("2025-05-01T00:00:00+02:00", "1.25"),
    ],
)
def test_invalid_opening_anchors_are_rejected(tmp_path, demo, anchor, opening):
    copied = tmp_path / "bad-anchor"
    shutil.copytree(demo, copied)
    rewrite(
        copied / "accounts.csv",
        lambda records: records[0].update(
            balance_anchor_at=anchor, opening_balance_minor=opening
        ),
    )
    with pytest.raises(ValueError):
        validate_rows(copied)


def test_pre_anchor_posting_is_rejected(tmp_path, demo):
    copied = tmp_path / "pre-anchor"
    shutil.copytree(demo, copied)
    with (copied / "posted_entries.csv").open() as handle:
        first = next(csv.DictReader(handle))
    account = first["account_id"]
    rewrite(
        copied / "accounts.csv",
        lambda records: next(r for r in records if r["account_id"] == account).update(
            balance_anchor_at="2026-10-01T00:00:00+02:00"
        ),
    )
    with pytest.raises(ValueError, match="chronology"):
        validate_rows(copied)


def test_manifest_balance_diagnostics_are_rebuilt(tmp_path, demo):
    manifest = verify_files(demo)
    with (demo / "accounts.csv").open() as handle:
        account = next(
            r for r in csv.DictReader(handle) if r["account_id"] == "ac_00005_0"
        )
    with (demo / "posted_entries.csv").open() as handle:
        signed = sum(
            int(r["amount_minor"])
            for r in csv.DictReader(handle)
            if r["account_id"] == account["account_id"]
        )
    expected = int(account["opening_balance_minor"]) + signed
    assert (
        int(manifest["balance_diagnostics"]["accounts"]["ac_00005_0"]["as_of_minor"])
        == expected
    )
    copied = tmp_path / "false-balance"
    shutil.copytree(demo, copied)
    path = copied / "manifest.json"
    false_manifest = json.loads(path.read_text())
    false_manifest["balance_diagnostics"]["accounts"]["ac_00005_0"]["as_of_minor"] = "0"
    path.write_bytes(canonical(false_manifest) + b"\n")
    with pytest.raises(ValueError, match="balance diagnostics"):
        verify_files(copied)
