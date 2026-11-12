"""Approve a verified synthetic dataset for the local simulator role."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

from .manifest import verify_files
from .policy import ROOT

FIXTURE_ID = "spending-overview-isolated-fixture-v2"
FIXTURE_HASH = "manual-independent-fixture-v2"
FIXTURE_EPOCH = "a4f4b3cc-f782-4ac5-992b-50ed15971211"


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve a trusted simulator dataset")
    parser.add_argument("project")
    parser.add_argument("approve_target")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset", type=Path)
    source.add_argument("--fixture", action="store_true")
    args = parser.parse_args()
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", args.project)
        or args.project != args.approve_target
        or not (ROOT / ".env").is_file()
    ):
        parser.error("Explicit project approval and local .env are required")
    if args.fixture:
        if os.getenv("CSI_ISOLATED_TEST_DB") != "1":
            parser.error("Fixture approval requires CSI_ISOLATED_TEST_DB=1")
        dataset_id, seed_hash, epoch = FIXTURE_ID, FIXTURE_HASH, FIXTURE_EPOCH
    else:
        directory = args.dataset if args.dataset.is_absolute() else ROOT / args.dataset
        try:
            manifest = verify_files(directory)
        except (OSError, ValueError, KeyError) as error:
            parser.error(f"Dataset manifest validation failed: {error}")
        dataset_id = manifest["dataset_id"]
        seed_hash = manifest["seed_content_hash"]
        epoch = ""
    environment = os.environ.copy()
    environment.update(
        SIMULATOR_APPROVED_DATASET_ID=dataset_id,
        SIMULATOR_APPROVED_SEED_HASH=seed_hash,
        SIMULATOR_APPROVED_EPOCH=epoch,
    )
    result = subprocess.run(
        [
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
            "db-sim-provision",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        parser.error(
            "Approval failed: target dataset identity, epoch or role is invalid"
        )
    print(f"Approved {dataset_id} for Compose project {args.project}")


if __name__ == "__main__":
    main()
