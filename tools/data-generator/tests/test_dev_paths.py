"""The shell dispatcher must pass one exact dataset directory to the importer."""

import os
import subprocess

import pytest

from csi_data.policy import ROOT


@pytest.mark.parametrize("kind", ["absolute", "relative", "spaces"])
def test_import_dispatcher_resolves_dataset_path(tmp_path, kind):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "arguments"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CSI_UV_CAPTURE"\n')
    fake_uv.chmod(0o755)
    dataset = tmp_path / ("dataset with spaces" if kind == "spaces" else "dataset")
    dataset.mkdir()
    supplied = str(dataset) if kind != "relative" else os.path.relpath(dataset, ROOT)
    env = dict(
        os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", CSI_UV_CAPTURE=str(capture)
    )
    result = subprocess.run(
        [str(ROOT / "dev"), "data:import", supplied, "csi-test", "csi-test"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    arguments = capture.read_text().splitlines()
    assert arguments[6] == str(dataset.resolve())


def test_import_dispatcher_rejects_missing_dataset(tmp_path):
    missing = tmp_path / "missing"
    result = subprocess.run(
        [str(ROOT / "dev"), "data:import", str(missing), "csi-test", "csi-test"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "dataset" in result.stderr.lower()


def test_import_dispatcher_rejects_unapproved_target(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    result = subprocess.run(
        [str(ROOT / "dev"), "data:import", str(dataset), "csi-test", "another-project"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "approval" in result.stderr.lower()
