"""Operator CLI for generation, verification and controlled Compose import."""

from __future__ import annotations

import argparse
import csv
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from argon2 import PasswordHasher

from .generate import generate
from .importer import stream_import
from .manifest import verify_files
from .policy import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic financial data tooling")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("generate")
    make.add_argument("profile", choices=("demo", "benchmark"))
    make.add_argument("output", type=Path)
    make.add_argument("--chunk-size", type=int, default=1000)
    make.add_argument("--seed", type=int)
    check = commands.add_parser("validate")
    check.add_argument("output", type=Path)
    load = commands.add_parser("import")
    load.add_argument("output", type=Path)
    load.add_argument("--project", required=True)
    load.add_argument("--approve-target", required=True)
    args = parser.parse_args()
    if args.command == "generate":
        if args.profile == "benchmark":
            volume = args.output.parent
            while not volume.exists():
                volume = volume.parent
            free = shutil.disk_usage(volume).free
            if free < 3_000_000_000:
                parser.error("Benchmark requires at least 3 GB free disk space")
        manifest = generate(
            args.profile, args.output, chunk_size=args.chunk_size, seed=args.seed
        )
    else:
        manifest = verify_files(args.output)
    if args.command == "import":
        if (
            args.approve_target != args.project
            or not args.project
            or not (ROOT / ".env").is_file()
        ):
            parser.error(
                "Explicit target approval must equal the Compose project; .env is required"
            )
        if manifest["profile"] == "benchmark":
            if shutil.disk_usage(ROOT).free < 3_000_000_000:
                parser.error("Benchmark import requires at least 3 GB free disk space")
            memory = subprocess.run(
                ["docker", "info", "--format", "{{.MemTotal}}"],
                check=True,
                capture_output=True,
                text=True,
            )
            if int(memory.stdout.strip()) < 2_000_000_000:
                parser.error("Benchmark import requires at least 2 GB Docker memory")
        probe = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                args.project,
                "--profile",
                "tools",
                "run",
                "--rm",
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
                "SELECT dataset_id || '|' || seed_content_hash FROM dataset_instance",
            ],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        accepted = probe.stdout.strip()
        expected = f"{manifest['dataset_id']}|{manifest['seed_content_hash']}"
        if accepted == expected:
            print(f"Identical approved seed: no-op ({manifest['dataset_id']})")
            return
        if accepted:
            raise ValueError(
                "Occupied database has a different seed; explicit reset is required"
            )
        password = os.environ.get("CSI_CUSTOMER_PASSWORD") or getpass.getpass(
            "Synthetic customer login password: "
        )
        if len(password) < 16:
            parser.error("Synthetic customer password must be at least 16 characters")
        hasher = PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=1, hash_len=32, salt_len=16
        )
        with tempfile.TemporaryDirectory(prefix="csi-credentials-") as temporary:
            secrets = Path(temporary)
            with (secrets / "credentials.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(("customer_id", "password_hash"))
                with (args.output / "customers.csv").open(
                    encoding="utf-8", newline=""
                ) as customers:
                    for customer in csv.DictReader(customers):
                        writer.writerow(
                            (customer["customer_id"], hasher.hash(password))
                        )
            stream_import(
                args.output, secrets / "credentials.csv", manifest, args.project
            )
    print(
        f"{manifest['dataset_id']} {manifest['seed_content_hash']} {manifest['file_counts']}"
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Data operation failed: {error}", file=sys.stderr)
        sys.exit(1)
