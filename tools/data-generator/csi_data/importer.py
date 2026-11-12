"""Stream verified COPY bytes into one operator-only PostgreSQL transaction."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, Iterator

from .policy import FILES, ROOT, VERSION, canonical, digest

COPY_INPUTS = {
    "customers_stage": "customers.csv",
    "accounts_stage": "accounts.csv",
    "credentials_stage": "credentials.csv",
    "merchants_stage": "merchants.csv",
    "categories_stage": "categories.csv",
    "authorizations_stage": "authorizations.csv",
    "posted_stage": "posted_entries.csv",
}
BLOCK_SIZE = 1024 * 1024


def file_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(BLOCK_SIZE), b""):
            yield chunk


def stream_import(
    dataset: Path, credentials: Path, manifest: dict[str, Any], project: str
) -> None:
    hashes = manifest["file_sha256"]
    if (
        set(hashes) != set(FILES)
        or manifest["generator_version"] != VERSION
        or manifest["seed_content_hash"]
        != digest(
            canonical(
                {
                    "files": hashes,
                    "config_hash": manifest["config_hash"],
                    "policy_hash": manifest["policy_hash"],
                }
            )
        )
        or manifest["dataset_id"]
        != f"synthetic-{manifest['profile']}-{manifest['seed_content_hash'][:20]}"
    ):
        raise ValueError("Inconsistent import identity")
    script = (ROOT / "tools/db/import.sql").read_text()
    command = [
        "docker",
        "compose",
        "-p",
        project,
        "--profile",
        "tools",
        "run",
        "--rm",
        "-T",
        "db-import",
        "-v",
        f"dataset_id={manifest['dataset_id']}",
        "-v",
        f"seed_hash={manifest['seed_content_hash']}",
        "-v",
        f"generator_version={manifest['generator_version']}",
    ]
    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE)
    seen: set[str] = set()
    committed = False
    try:
        assert process.stdin is not None
        for line in script.splitlines(keepends=True):
            if line.strip() == "COMMIT;":
                if seen != set(COPY_INPUTS) or set(manifest["file_sha256"]) != set(
                    FILES
                ):
                    raise ValueError("Incomplete COPY input inventory")
                process.stdin.write(b"COMMIT;\n")
                committed = True
                continue
            if committed:
                raise ValueError("Unexpected SQL after COMMIT")
            process.stdin.write(line.encode())
            if not line.startswith("COPY "):
                continue
            stage = line.split("(", 1)[0].split()[1]
            name = COPY_INPUTS.get(stage)
            if name is None or stage in seen or " FROM STDIN " not in line:
                raise ValueError("Unsupported COPY operation")
            seen.add(stage)
            source = credentials if name == "credentials.csv" else dataset / name
            hasher = hashlib.sha256()
            for chunk in file_chunks(source):
                process.stdin.write(chunk)
                hasher.update(chunk)
            process.stdin.write(b"\\.\n")
            process.stdin.flush()
            if name in FILES and hasher.hexdigest() != manifest["file_sha256"][name]:
                raise ValueError(f"COPY byte hash mismatch: {name}")
        if not committed:
            raise ValueError("Import script has no COMMIT")
        process.stdin.close()
        if process.wait() != 0:
            raise subprocess.CalledProcessError(process.returncode, command)
    except BaseException:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
        process.wait()
        raise
