"""Real, isolated PostgreSQL regression tests for the operator import boundary."""

import csv
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from csi_data import importer
from csi_data import __main__ as cli
from csi_data.generate import generate
from csi_data.manifest import verify_files
from csi_data.policy import ROOT, canonical, digest, file_digest

@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    location = tmp_path_factory.mktemp("import-demo") / "demo"
    generate("demo", location)
    return location


@pytest.fixture
def target():
    project = "csi-import-test-" + uuid.uuid4().hex[:10]
    try:
        yield project
    finally:
        subprocess.run(
            ["docker", "compose", "-p", project, "down", "-v", "--remove-orphans"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )


def query(project: str, sql: str) -> subprocess.CompletedProcess[str]:
    command = [
        "docker",
        "compose",
        "-p",
        project,
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -A -t -v ON_ERROR_STOP=1 -U "$1" -d customer_insights -c "$2"',
        "sh",
        "customer_insights",
        sql,
    ]
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def assert_empty(project: str) -> None:
    result = query(
        project,
        "SELECT (SELECT count(*) FROM customers),(SELECT count(*) FROM authorizations),(SELECT count(*) FROM posted_entries),(SELECT count(*) FROM dataset_instance),(SELECT count(*) FROM source_events),(SELECT count(*) FROM transfer_groups)",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0|0|0|0|0|0"


def credentials(tmp_path: Path) -> Path:
    path = tmp_path / "credentials.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("customer_id", "password_hash"))
        for index in range(20):
            writer.writerow(
                (
                    f"cu_{index:05d}",
                    "$argon2id$v=19$m=65536,t=3,p=1$YWJjZGVmZ2hpamtsbW5vcA$YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXowMTIzNDU",
                )
            )
    return path


def run_cli(dataset: Path, target: str, monkeypatch) -> None:
    monkeypatch.setenv("CSI_CUSTOMER_PASSWORD", "synthetic-test-password-long")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "csi_data",
            "import",
            str(dataset),
            "--project",
            target,
            "--approve-target",
            target,
        ],
    )
    cli.main()


def test_changed_after_validation_rejected_by_normal_import(
    tmp_path, demo, target, monkeypatch
):
    dataset = tmp_path / "demo"
    shutil.copytree(demo, dataset)
    original_verify = cli.verify_files

    def tamper_after_verify(path):
        result = original_verify(path)
        posted = path / "posted_entries.csv"
        data = posted.read_bytes()
        posted.write_bytes(data.replace(b",MERCHANT,", b",TYPE_RULE,", 1))
        return result

    monkeypatch.setattr(cli, "verify_files", tamper_after_verify)
    with pytest.raises(ValueError, match="COPY byte hash mismatch"):
        run_cli(dataset, target, monkeypatch)
    assert_empty(target)


def test_changed_during_copy_rejected(tmp_path, demo, target, monkeypatch):
    dataset = tmp_path / "demo"
    shutil.copytree(demo, dataset)
    manifest = verify_files(dataset)
    original_chunks = importer.file_chunks
    monkeypatch.setattr(importer, "BLOCK_SIZE", 4096)
    changed = False

    def chunks(path):
        nonlocal changed
        for chunk in original_chunks(path):
            yield chunk
            if path.name == "posted_entries.csv" and not changed:
                data = path.read_bytes()
                offset = data.find(b"Synthetic", 1_048_576)
                assert offset > 1_048_576
                with path.open("r+b") as handle:
                    handle.seek(offset)
                    handle.write(b"X")
                changed = True

    monkeypatch.setattr(importer, "file_chunks", chunks)
    with pytest.raises(ValueError, match="COPY byte hash mismatch"):
        importer.stream_import(dataset, credentials(tmp_path), manifest, target)
    assert changed
    assert_empty(target)


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("CARD_PURCHASE", "classification_provenance", "TYPE_RULE"),
        ("BANK_FEE", "classification_provenance", "MERCHANT"),
        ("SPEND_REFUND", "classification_provenance", "TYPE_RULE"),
        ("BANK_FEE", "effect_group", "INCOME"),
    ],
)
def test_direct_import_rejects_invalid_classification_with_matching_hashes(
    tmp_path, demo, target, kind, field, value
):
    dataset = tmp_path / "demo"
    shutil.copytree(demo, dataset)
    posted = dataset / "posted_entries.csv"
    with posted.open(newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        records = list(reader)
    assert columns is not None
    original = next(record for record in records if record["transaction_type"] == kind)
    assert original[field] != value
    original[field] = value
    with posted.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["file_sha256"]["posted_entries.csv"] = file_digest(posted)
    manifest["seed_content_hash"] = digest(
        canonical(
            {
                "files": manifest["file_sha256"],
                "config_hash": manifest["config_hash"],
                "policy_hash": manifest["policy_hash"],
            }
        )
    )
    manifest["dataset_id"] = f"synthetic-demo-{manifest['seed_content_hash'][:20]}"
    manifest_path.write_bytes(canonical(manifest) + b"\n")
    with pytest.raises(subprocess.CalledProcessError):
        importer.stream_import(dataset, credentials(tmp_path), manifest, target)
    assert_empty(target)


def test_valid_import_replay_and_restricted_role(tmp_path, demo, target, monkeypatch):
    manifest = verify_files(demo)
    run_cli(demo, target, monkeypatch)
    initial = query(
        target,
        "SELECT dataset_id||'|'||seed_content_hash||'|'||instance_epoch FROM dataset_instance",
    )
    assert initial.returncode == 0
    assert initial.stdout.startswith(
        f"{manifest['dataset_id']}|{manifest['seed_content_hash']}|"
    )
    assert (
        query(target, "SELECT count(*) FROM posted_entries").stdout.strip() == "12800"
    )
    changed = query(
        target,
        "UPDATE customers SET customer_revision=customer_revision+1 WHERE id='cu_00000'; INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,classification_provenance) VALUES ('pe_replay_test','ac_00004_0','test:replay',10000,'ZAR','SALARY_CREDIT','INCOME','2026-10-20T12:00:00+02:00','2026-10-20T12:00:00+02:00','Replay preservation test','NOT_APPLICABLE')",
    )
    assert changed.returncode == 0, changed.stderr
    before_replay = query(
        target,
        "SELECT (SELECT customer_revision FROM customers WHERE id='cu_00000'),(SELECT amount_minor FROM posted_entries WHERE id='pe_replay_test')",
    ).stdout.strip()
    run_cli(demo, target, monkeypatch)
    assert (
        query(
            target,
            "SELECT dataset_id||'|'||seed_content_hash||'|'||instance_epoch FROM dataset_instance",
        ).stdout
        == initial.stdout
    )
    assert (
        query(
            target,
            "SELECT (SELECT customer_revision FROM customers WHERE id='cu_00000'),(SELECT amount_minor FROM posted_entries WHERE id='pe_replay_test')",
        ).stdout.strip()
        == before_replay
    )
    different = generate("demo", tmp_path / "different", seed=20261030)
    assert different["seed_content_hash"] != manifest["seed_content_hash"]
    with pytest.raises(ValueError, match="different seed"):
        run_cli(tmp_path / "different", target, monkeypatch)
    assert (
        query(
            target,
            "SELECT dataset_id||'|'||seed_content_hash||'|'||instance_epoch FROM dataset_instance",
        ).stdout
        == initial.stdout
    )
    denied = query(
        target,
        "SET ROLE customer_insights_api; UPDATE posted_entries SET amount_minor=0 WHERE id=(SELECT id FROM posted_entries LIMIT 1)",
    )
    assert denied.returncode != 0
    assert "permission denied" in denied.stderr.lower()
