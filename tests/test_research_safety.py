import subprocess
from unittest.mock import Mock

import pytest

from scripts import check_research_safety as guard


@pytest.mark.parametrize(
    ("status", "path"),
    [
        ("M", "experiments/E001_funding_rate/README.md"),
        ("M", "experiments/E002_range/PROTOCOL.md"),
        ("D", "experiments/E003_range_nonlinear/PROTOCOL.md"),
        ("M", "reports/E001_funding_rate/cv_metrics.csv"),
        ("M", "reports/E002_range/ridge_cv_metadata.json"),
        ("D", "reports/E002_final_holdout/ATTEMPT_STARTED.json"),
        ("T", "reports/E002_final_holdout/holdout_summary.json"),
        ("M", "reports/E003_range_nonlinear/rf_cv_pooled.csv"),
        ("D", "reports/E001_E003_synthesis/E001_E003_FINAL_report_manifest.json"),
        ("M", "reports/pre_holdout_audit/E002_FROZEN_MANIFEST.json"),
        ("M", "reports/pre_holdout_audit/FINAL_HOLDOUT_PROTOCOL.md"),
        ("M", "config/research_protocol.yaml"),
        ("D", "reports/data_quality_report.json"),
        ("A", "reports/E002_final_holdout/dodatkowy raport\nUTC.md"),
    ],
)
def test_blocks_changes_in_historical_paths(status, path):
    assert guard.protected_changes(f"{status}\0{path}\0".encode()) == {(path, status)}


def test_allows_unrelated_changes_and_separate_experiments():
    diff = (
        b"M\0src/quantlab/data/quality.py\0"
        b"D\0tests/test_old.py\0"
        b"A\0experiments/E004_new/PROTOCOL.md\0"
        b"A\0reports/E004_new/results.json\0"
        b"A\0reports/E002_range_followup/results.json\0"
    )
    assert guard.protected_changes(diff) == set()


@pytest.mark.parametrize(
    ("diff", "path", "status"),
    [
        (
            b"D\0reports/pre_holdout_audit/E002_FROZEN_MANIFEST.json\0"
            b"A\0docs/archive/moved.json\0",
            "reports/pre_holdout_audit/E002_FROZEN_MANIFEST.json", "D",
        ),
        (
            b"D\0docs/draft.md\0A\0experiments/E002_range/moved.md\0",
            "experiments/E002_range/moved.md", "A",
        ),
    ],
)
def test_blocks_moves_to_or_from_historical_paths(diff, path, status):
    assert guard.protected_changes(diff) == {(path, status)}


def test_missing_git_base_fails_the_check(monkeypatch, capsys):
    git = Mock(side_effect=subprocess.CalledProcessError(
        128, ["git", "rev-parse"], stderr=b"fatal: Needed a single revision",
    ))
    monkeypatch.setattr(guard, "git", git)

    assert guard.main(["--base", "missing"]) == 2
    assert "Needed a single revision" in capsys.readouterr().err
    git.assert_called_once_with("rev-parse", "--verify", "--end-of-options", "missing^{commit}")


def test_pr_check_compares_the_two_resolved_commits(monkeypatch, capsys):
    git = Mock(side_effect=[b"base-sha\n", b"head-sha\n", b"M\0scripts/new_script.py\0"])
    monkeypatch.setattr(guard, "git", git)

    assert guard.main(["--base", "HEAD^1", "--head", "HEAD"]) == 0
    assert "passed" in capsys.readouterr().out
    assert git.call_args_list[0].args[-1] == "HEAD^1^{commit}"
    assert git.call_args_list[1].args[-1] == "HEAD^{commit}"
    diff_args = git.call_args.args
    assert diff_args[0] == "diff"
    assert {"--name-status", "--no-renames", "-z"} <= set(diff_args)
    assert diff_args[-3:] == ("base-sha", "head-sha", "--")


def test_local_check_detects_staged_changes_hidden_by_working_tree(monkeypatch, capsys):
    git = Mock(side_effect=[b"base-sha\n", b"M\0reports/E002_final_holdout/holdout_summary.json\0", b""])
    monkeypatch.setattr(guard, "git", git)

    assert guard.main([]) == 1
    assert "holdout_summary.json" in capsys.readouterr().err
    assert git.call_args_list[0].args[-1] == "main^{commit}"
    assert "--cached" in git.call_args_list[1].args
    assert "--cached" not in git.call_args_list[2].args


def test_malformed_diff_fails_the_check(monkeypatch, capsys):
    monkeypatch.setattr(guard, "git", Mock(side_effect=[b"base-sha\n", b"M\0"]))

    assert guard.main([]) == 2
    assert "Malformed Git name-status output" in capsys.readouterr().err
