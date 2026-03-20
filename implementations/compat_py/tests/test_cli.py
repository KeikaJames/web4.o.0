"""Tests for the compat_py CLI entry point."""

import json
from pathlib import Path

from implementations.sac_py.sac import SACContainer
from implementations.compat_py.cli import main

PASSPHRASE = "test-passphrase-for-cli"


def _create_sac(tmp_path):
    """Create a SAC container and save it, return (sac_path, memory_dir)."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    sac = SACContainer.create(memory_path=str(memory_dir))
    sac_path = tmp_path / "test.sac.json"
    sac.save(sac_path, PASSPHRASE)
    return sac_path, memory_dir


def test_cli_allowed_write(tmp_path, capsys):
    sac_path, memory_dir = _create_sac(tmp_path)
    input_file = memory_dir / "input.txt"
    input_file.write_text("hello cli")
    output_file = memory_dir / "output.txt"

    rc = main([
        "--sac", str(sac_path),
        "--passphrase", PASSPHRASE,
        "--input", str(input_file),
        "--output", str(output_file),
    ])

    assert rc == 0
    assert output_file.read_text() == "HELLO CLI"
    out = capsys.readouterr().out
    assert "performed:   True" in out
    assert "reason_code: SUCCESS" in out


def test_cli_denied_without_confirmation(tmp_path, capsys):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    sac = SACContainer.create(memory_path=str(memory_dir))
    sac.permissions.actions_require_confirmation = ["file.write"]
    sac_path = tmp_path / "test.sac.json"
    sac.save(sac_path, PASSPHRASE)

    input_file = memory_dir / "input.txt"
    input_file.write_text("should deny")
    output_file = memory_dir / "denied.txt"

    rc = main([
        "--sac", str(sac_path),
        "--passphrase", PASSPHRASE,
        "--input", str(input_file),
        "--output", str(output_file),
    ])

    assert rc == 1
    assert not output_file.exists()
    out = capsys.readouterr().out
    assert "performed:   False" in out
    assert "REQUIRES_CONFIRMATION" in out


def test_cli_json_output(tmp_path, capsys):
    sac_path, memory_dir = _create_sac(tmp_path)
    input_file = memory_dir / "input.txt"
    input_file.write_text("json test")
    output_file = memory_dir / "output.txt"

    rc = main([
        "--sac", str(sac_path),
        "--passphrase", PASSPHRASE,
        "--input", str(input_file),
        "--output", str(output_file),
        "--json",
    ])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["performed"] is True
    assert data["reason_code"] == "SUCCESS"
    assert data["operation"] == "file.write"
    assert data["bytes_written"] > 0


def test_cli_missing_passphrase(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SAC_PASSPHRASE", raising=False)
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    rc = main([
        "--sac", "fake.json",
        "--input", "fake.txt",
        "--output", "fake_out.txt",
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "passphrase required" in err


def test_cli_bad_sac_path(tmp_path, capsys):
    rc = main([
        "--sac", str(tmp_path / "nonexistent.json"),
        "--passphrase", PASSPHRASE,
        "--input", "fake.txt",
        "--output", "fake_out.txt",
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "failed to load SAC" in err
