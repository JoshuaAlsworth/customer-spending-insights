"""Local entrypoints reject unsafe targets before touching Docker state."""

import os
import csv
import importlib.util
import subprocess
import sys

from csi_data.policy import ROOT


def test_invalid_port_rejected_before_docker() -> None:
    result = subprocess.run(
        ["sh", str(ROOT / "tools/dev/local.sh"), "up"],
        cwd=ROOT,
        env={**os.environ, "CSI_WEB_PORT": "65536"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "CSI_WEB_PORT" in result.stderr


def test_busy_port_names_owning_container_before_start(tmp_path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  "compose up --help") echo --wait;;\n'
        '  "compose run --help") echo --no-deps;;\n'
        '  "ps --filter publish=8088 --format {{.Names}}") echo occupied-web;;\n'
        '  *"--entrypoint true"*) exit 1;;\n'
        "esac\n"
    )
    docker.chmod(0o755)
    result = subprocess.run(
        ["sh", str(ROOT / "tools/dev/local.sh"), "up"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CSI_COMPOSE_PROJECT": "csi-port-test",
            "CSI_WEB_PORT": "8088",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "occupied-web" in result.stderr
    assert not (tmp_path / ".env").exists()


def test_invalid_project_rejected_before_docker() -> None:
    result = subprocess.run(
        ["sh", str(ROOT / "tools/dev/local.sh"), "down"],
        cwd=ROOT,
        env={**os.environ, "CSI_COMPOSE_PROJECT": "../other"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "CSI_COMPOSE_PROJECT" in result.stderr


def test_invalid_secret_rejected_before_start(tmp_path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  "compose up --help") echo --wait;;\n'
        '  "compose run --help") echo --no-deps;;\n'
        "esac\n"
    )
    docker.chmod(0o755)
    (tmp_path / ".env").write_text(
        "POSTGRES_PASSWORD=" + "a" * 48 + "\n"
        "API_DB_PASSWORD=" + "b" * 48 + "\n"
        "CURSOR_SECRET=" + "invalid" * 10 + "\n"
        "SIMULATOR_DB_PASSWORD=" + "c" * 48 + "\n"
    )
    result = subprocess.run(
        ["sh", str(ROOT / "tools/dev/local.sh"), "up"],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "CURSOR_SECRET" in result.stderr


def test_demo_requires_operator_approval() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/dev/demo.py"), "review1"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "tools/data-generator")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--approve" in result.stderr


def test_incomplete_manifest_fails_without_traceback(tmp_path) -> None:
    (tmp_path / "manifest.json").write_text('{"invalid":true}\n')
    result = subprocess.run(
        [sys.executable, "-m", "csi_data", "validate", str(tmp_path)],
        cwd=ROOT / "tools/data-generator",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "missing manifest field" in result.stderr
    assert "Traceback" not in result.stderr


def test_demo_resolves_login_owner_from_validated_rows(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location("demo", ROOT / "tools/dev/demo.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with (tmp_path / "customers.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["customer_id", "login_id", "status"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "customer_id": "unexpected-id",
                "login_id": "synthetic-00004",
                "status": "ACTIVE",
            }
        )
    with (tmp_path / "accounts.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "account_id",
                "customer_id",
                "account_kind",
                "status",
                "opened_on",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "account_id": "correct-account",
                "customer_id": "unexpected-id",
                "account_kind": "EVERYDAY",
                "status": "OPEN",
                "opened_on": "2025-05-01",
            }
        )
        writer.writerow(
            {
                "account_id": "wrong-account",
                "customer_id": "cu_00004",
                "account_kind": "EVERYDAY",
                "status": "OPEN",
                "opened_on": "2025-05-01",
            }
        )
    with (tmp_path / "merchants.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["merchant_id"])
        writer.writeheader()
        writer.writerow({"merchant_id": "cedar-market"})
        writer.writerow({"merchant_id": "harbor-cafe"})
    assert module.selected_account(tmp_path) == ("unexpected-id", "correct-account")


def test_extra_arguments_never_reach_docker(tmp_path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(f"#!/bin/sh\nprintf called >> '{tmp_path / 'calls'}'\n")
    docker.chmod(0o755)
    (tmp_path / ".env").write_text("present\n")
    commands = [
        ["down", "unexpected"],
        ["status", "unexpected"],
        ["help", "unexpected"],
        ["credentials", "unexpected"],
        ["demo", "run1", "--approve", "unexpected"],
        ["provision", "project", "unexpected"],
        ["up", "unexpected"],
        ["logs", "unexpected"],
        ["build", "unexpected"],
        ["check", "unexpected"],
        ["format", "unexpected"],
        ["test", "unexpected"],
        ["test:docker", "all", "unexpected"],
        ["simulate:provision", "project", "project", "--fixture", "unexpected"],
        ["secure:up", "project", "unexpected"],
        ["benchmark:prepare", "csi-benchmark-test", "csi-benchmark-test", "unexpected"],
        [
            "benchmark:run",
            "csi-benchmark-test",
            "smoke",
            "synthetic-00004",
            "unexpected",
        ],
        ["benchmark:down", "csi-benchmark-test", "csi-benchmark-test", "unexpected"],
        ["recovery:backup", "csi-benchmark-test", "/tmp/dump", "unexpected"],
        [
            "recovery:restore",
            "/tmp/dump",
            "csi-recovery-test",
            "csi-recovery-test",
            "unexpected",
        ],
        ["k8s:up", "csi-benchmark-test", "csi-hardening-test", "unexpected"],
        [
            "k8s:down",
            "csi-benchmark-test",
            "csi-hardening-test",
            "csi-hardening-test",
            "unexpected",
        ],
        [
            "k8s:demo",
            "csi-benchmark-test",
            "csi-hardening-test",
            "hpa",
            "synthetic-00004",
            "unexpected",
        ],
    ]
    for arguments in commands:
        result = subprocess.run(
            ["sh", str(ROOT / "dev"), *arguments],
            cwd=ROOT,
            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2, arguments
        assert "Usage:" in result.stderr, arguments
    assert not (tmp_path / "calls").exists()


def test_recovery_refuses_existing_or_unapproved_target_before_docker(tmp_path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(f"#!/bin/sh\nprintf called >> '{tmp_path / 'calls'}'\n")
    docker.chmod(0o755)
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"backup")
    for args in (
        [
            "restore",
            str(backup),
            "customer-spending-insights",
            "customer-spending-insights",
        ],
        ["restore", str(backup), "csi-recovery-test", "wrong-target"],
    ):
        result = subprocess.run(
            ["sh", str(ROOT / "tools/recovery/local.sh"), *args],
            cwd=ROOT,
            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
    assert not (tmp_path / "calls").exists()


def test_demo_rejects_conflicting_simulator_environment_before_docker(tmp_path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(f"#!/bin/sh\nprintf called >> '{tmp_path / 'calls'}'\n")
    docker.chmod(0o755)
    (tmp_path / ".env").write_text(
        "POSTGRES_PASSWORD=" + "a" * 48 + "\n"
        "API_DB_PASSWORD=" + "b" * 48 + "\n"
        "CURSOR_SECRET=" + "c" * 64 + "\n"
        "SIMULATOR_DB_PASSWORD=" + "d" * 48 + "\n"
    )
    result = subprocess.run(
        ["sh", str(ROOT / "tools/dev/local.sh"), "demo", "run1", "--approve"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "SIMULATOR_DB_PASSWORD": "e" * 48,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "SIMULATOR_DB_PASSWORD environment override differs" in result.stderr
    assert not (tmp_path / "calls").exists()
