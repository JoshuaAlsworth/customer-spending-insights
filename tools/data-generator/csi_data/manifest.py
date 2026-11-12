"""Canonical seed identity and import preflight verification."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .policy import (
    FILES,
    PROFILES,
    REFERENCE,
    VERSION,
    canonical,
    digest,
    file_digest,
    policies,
)


def verify_files(output: Path) -> dict[str, Any]:
    from .validate import validate_rows

    manifest_bytes = (output / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest_bytes != canonical(manifest) + b"\n":
        raise ValueError("Noncanonical manifest JSON")
    tax, cat, policy_hash = policies()
    if (
        manifest["generator_version"] != VERSION
        or manifest["transaction_policy_version"] != tax["version"]
        or manifest["category_policy_version"] != cat["version"]
        or manifest["policy_hash"] != policy_hash
    ):
        raise ValueError("Unsupported policy or generator version")
    if manifest["config_hash"] != digest(canonical(manifest["parameters"])):
        raise ValueError("Configuration hash mismatch")
    profile = manifest["profile"]
    expected = PROFILES.get(profile)
    if (
        expected is None
        or manifest["master_seed"] != manifest["parameters"].get("seed")
        or manifest["parameters"] != {**expected, "seed": manifest["master_seed"]}
        or manifest["fixed_reference_date"] != REFERENCE.isoformat()
        or manifest["timezone"] != "Africa/Johannesburg"
        or manifest["independent_expected_results"] != "contracts/finance/fixtures.json"
        or manifest["instance_epoch"] is not None
        or manifest["customer_data_revision"] != 0
    ):
        raise ValueError("Unsupported dataset configuration")
    hashes = {}
    persona_counts: Counter[str] = Counter()
    modifier_counts: Counter[str] = Counter()
    account_owners: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    customer_ids: set[str] = set()
    high_ids: set[str] = set()
    high_entries = 0
    missing_metadata: Counter[str] = Counter()
    if set(manifest["file_counts"]) != set(FILES) or set(
        manifest["file_sha256"]
    ) != set(FILES):
        raise ValueError("Manifest file inventory mismatch")
    for name, columns in FILES.items():
        path = output / name
        with path.open("rb") as raw:
            if raw.read(3) == b"\xef\xbb\xbf":
                raise ValueError(f"UTF-8 BOM in {name}")
            raw.seek(0)
            last = b""
            for block in iter(lambda: raw.read(1024 * 1024), b""):
                if b"\r" in block or b"\x00" in block:
                    raise ValueError(f"Noncanonical bytes in {name}")
                last = block
            if not last.endswith(b"\n"):
                raise ValueError(f"Missing final LF in {name}")
        hashes[name] = file_digest(path)
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            if tuple(next(reader)) != columns:
                raise ValueError(f"Invalid header in {name}")
            count = 0
            for values in reader:
                if len(values) != len(columns) or any(
                    value == "" for value in values[:1]
                ):
                    raise ValueError(f"Malformed row in {name}")
                count += 1
                if name == "customers.csv":
                    customer_ids.add(values[0])
                    persona_counts[values[4]] += 1
                    modifiers = values[5].strip("{}")
                    if modifiers:
                        modifier_counts.update(modifiers.split(","))
                    if "HIGH_ACTIVITY" in modifiers.split(","):
                        high_ids.add(values[0])
                elif name == "accounts.csv":
                    account_owners[values[1]] += 1
                elif name == "merchants.csv":
                    missing_metadata["merchant_mcc"] += values[2] == "\\N"
                    missing_metadata["merchant_category"] += values[3] == "\\N"
                    missing_metadata["merchant_descriptor_variant"] += (
                        values[4] == "\\N"
                    )
                elif name == "posted_entries.csv":
                    type_counts[values[5]] += 1
                    high_entries += f"cu_{values[0][3:8]}" in high_ids
            if count != manifest["file_counts"].get(name, 0):
                raise ValueError(f"Count mismatch in {name}")
    if hashes != manifest["file_sha256"] or manifest["seed_content_hash"] != digest(
        canonical(
            {
                "files": hashes,
                "config_hash": manifest["config_hash"],
                "policy_hash": policy_hash,
            }
        )
    ):
        raise ValueError("Seed hash mismatch")
    if (
        manifest["dataset_id"]
        != f"synthetic-{profile}-{manifest['seed_content_hash'][:20]}"
    ):
        raise ValueError("Dataset identity mismatch")
    actual = {
        "personas": dict(persona_counts),
        "modifiers": dict(modifier_counts),
        "account_counts": dict(
            Counter(str(account_owners[id_]) for id_ in customer_ids)
        ),
        "transaction_types": dict(type_counts),
    }
    if (
        manifest["distribution_summaries"] != actual
        or manifest["high_activity_posted_entries"] != high_entries
        or manifest["metadata_missingness"] != dict(missing_metadata)
    ):
        raise ValueError("Manifest distribution summary mismatch")
    if manifest.get("scenario_coverage") != validate_rows(output):
        raise ValueError("Manifest scenario coverage mismatch")
    return manifest
