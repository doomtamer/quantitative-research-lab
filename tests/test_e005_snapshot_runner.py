from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import e005_snapshot as snapshot
from scripts import e005_authorization as authorization
from scripts import run_e005_development as runner


def row(at, step):
    opened = snapshot.milliseconds(at)
    closed = opened + step // timedelta(milliseconds=1) - 1
    return [opened, "10", "12", "8", "11", "4", closed, "0", 1, "0", "0", "0"]


def test_requests_cannot_cross_the_e005_final_test_boundary():
    for span in snapshot.SPANS:
        pages = list(snapshot.pages(span))
        assert pages[0]["startTime"] == snapshot.milliseconds(span.start)
        assert pages[-1]["endTime"] == snapshot.milliseconds(span.end) - 1
        assert pages[-1]["endTime"] < snapshot.milliseconds(snapshot.CUTOFF)
        assert sum(page["limit"] for page in pages) == len(span.schedule())
    opener = Mock()
    with pytest.raises(ValueError, match="Refusing"):
        snapshot.fetch(opener, {**pages[-1], "endTime": snapshot.milliseconds(snapshot.CUTOFF)})
    opener.open.assert_not_called()


@pytest.mark.parametrize("mutation", ["cutoff", "utc", "ohlcv", "duplicate"])
def test_audit_rejects_unsafe_or_invalid_responses(mutation):
    span = snapshot.SPANS[-1]
    params = next(snapshot.pages(span))
    valid = row(span.start, span.delta)
    candidate = valid.copy()
    if mutation == "cutoff":
        candidate = row(snapshot.CUTOFF, span.delta)
    elif mutation == "utc":
        candidate[6] += 1
    elif mutation == "ohlcv":
        candidate[2] = "9"
    rows = [valid, candidate] if mutation == "duplicate" else [candidate]
    with pytest.raises(ValueError):
        snapshot.read_page(json.dumps(rows).encode(), params, span, {})


def test_runner_verifies_complete_scope_hashes_and_rows(tmp_path, monkeypatch):
    small_spans = tuple(snapshot.Span(part.name, part.interval, part.start, part.start + 2 * part.delta)
                        for part in snapshot.SPANS)
    monkeypatch.setattr(runner, "SPANS", small_spans)
    identifier = "a" * 32
    folder = tmp_path / snapshot.DATA / identifier
    folder.mkdir(parents=True)
    inputs = {}
    for span in small_spans:
        requests = [{"params": params, "row_count": params["limit"], "response_sha256": "f" * 64,
                     "started_utc": "2025-01-01T01:00:00+00:00", "received_utc": "2025-01-01T01:00:01+00:00"}
                    for params in snapshot.pages(span)]
        inputs[span.name] = snapshot.store_span(
            folder, span, {at: ["10", "12", "8", "11", "4"] for at in span.schedule()}, requests,
        )
    manifest = {
        "experiment_id": snapshot.EXPERIMENT, "protocol_sha256": snapshot.PROTOCOL_SHA256,
        "scope": "development_and_validation_only", "exclusive_cutoff_utc": snapshot.CUTOFF.isoformat(),
        "endpoint": snapshot.ENDPOINT, "symbol": "BTCUSDT", "complete": True,
        "funding": "funding_excluded", "equity_prices": "traded_open_proxy",
        "historical_signal_availability_verified": False, "inputs": inputs,
    }
    path = folder / "snapshot_manifest.json"
    payload = json.dumps(manifest).encode()
    path.write_bytes(payload)
    digest = sha256(payload).hexdigest()
    assert {name: len(rows) for name, rows in runner.verify_snapshot(tmp_path, identifier, digest).items()} == {
        "daily": 2, "development": 2, "validation": 2,
    }
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        runner.verify_snapshot(tmp_path, identifier, "0" * 64)
    target = folder / "validation.csv"
    target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        runner.verify_snapshot(tmp_path, identifier, digest)


def test_runner_refuses_execution_before_opening_any_snapshot(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(runner, "check_protocol", lambda _root: None)
    monkeypatch.setattr(runner, "verify_frozen_request", Mock(return_value=b"test-only"))
    monkeypatch.setattr(runner, "require_independent_authorization",
                        Mock(side_effect=PermissionError("Independent research authorization required")))
    load = Mock()
    execute = Mock()
    monkeypatch.setattr(runner, "verify_snapshot", load)
    monkeypatch.setattr(runner, "_run_verified_inputs", execute)
    assert runner.main(["run", "a" * 32, "b" * 64, "--code-sha256", "c" * 64,
                        "--approval-run-id", "123"], root=tmp_path) == 2
    assert "Independent research authorization" in capsys.readouterr().err
    load.assert_not_called()
    execute.assert_not_called()
    assert not (tmp_path / runner.RUNS).exists()


def test_authorization_only_never_reads_data(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(runner, "check_protocol", lambda _root: None)
    monkeypatch.setattr(runner, "verify_frozen_request", Mock(return_value=b"test-only"))
    decision = Mock(return_value={"decision": "approved"})
    monkeypatch.setattr(runner, "require_independent_authorization", decision)
    load = Mock()
    monkeypatch.setattr(runner, "verify_snapshot", load)
    assert runner.main(["authorize", "a" * 32, "b" * 64, "--code-sha256", "c" * 64,
                        "--approval-run-id", "123"], root=tmp_path) == 0
    decision.assert_called_once_with(b"test-only", "123")
    load.assert_not_called()
    assert json.loads(capsys.readouterr().out) == {"decision": "approved"}


def test_frozen_protocol_digest_is_exact(tmp_path):
    snapshot.check_protocol(snapshot.ROOT)
    path = tmp_path / snapshot.PROTOCOL
    path.parent.mkdir(parents=True)
    path.write_bytes((snapshot.ROOT / snapshot.PROTOCOL).read_bytes() + b"\n")
    with pytest.raises(ValueError, match="protocol SHA-256"):
        snapshot.check_protocol(tmp_path)


def test_internal_writer_uses_unique_output_and_period_local_context(monkeypatch, tmp_path):
    simulate, report = Mock(return_value={}), Mock()
    monkeypatch.setattr(runner, "run_suite", simulate)
    monkeypatch.setattr(runner, "write_report", report)
    monkeypatch.setattr(runner, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    _, development, validation = snapshot.SPANS
    value = {"open": "10", "close": "11"}
    verified = {
        "daily": [(development.start - timedelta(hours=1), value),
                  (validation.start - timedelta(days=1, hours=1), value)],
        "development": [(development.start, value), (development.end - development.delta, value)],
        "validation": [(validation.start, value), (validation.end - validation.delta, value)],
    }
    path = runner._run_verified_inputs(tmp_path, verified, "b" * 32, "c" * 64, "d" * 64, "test-only")
    assert path == tmp_path / runner.RUNS / ("a" * 32)
    assert (path / "COMPLETED").exists()
    started = json.loads((path / "ATTEMPT_STARTED.json").read_bytes())
    assert started["funding"] == "funding_excluded"
    assert started["signal_availability"]["basis"] == "simulation_assumption"
    assert [call.kwargs["period_name"] for call in report.call_args_list] == ["development", "validation"]
    development_period, _, day_context = simulate.call_args_list[0].args
    assert development_period.end < validation.start
    assert all(item.day < development_period.end.date() for item in day_context)
    assert all(item.availability_basis == "simulation_assumption" for item in day_context)
    with pytest.raises(FileExistsError):
        runner._run_verified_inputs(tmp_path, verified, "b" * 32, "c" * 64, "d" * 64, "test-only")


def test_frozen_bytes_bind_execution_to_exact_snapshot_scope_and_code(tmp_path, monkeypatch):
    monkeypatch.setattr(authorization, "CODE_FILES", ("runner.py",))
    (tmp_path / "runner.py").write_bytes(b"synthetic runner\n")
    frozen = authorization.freeze(tmp_path, "a" * 32, "b" * 64)
    folder = tmp_path / frozen["directory"]
    digest = frozen["code_sha256"]
    verified = authorization.verify_frozen_request(folder, "a" * 32, "b" * 64, digest)
    assert sha256(verified).hexdigest() == frozen["approval_request_sha256"]
    assert set(json.loads(verified)["scope"]) == {"daily", "development", "validation"}
    with pytest.raises(ValueError, match="approval request differs"):
        authorization.verify_frozen_request(folder, "a" * 32, "c" * 64, digest)
    (folder / "runner.py").write_bytes(b"synthetic runner\r\n")
    with pytest.raises(ValueError, match="executing code differs"):
        authorization.verify_frozen_request(folder, "a" * 32, "b" * 64, digest)
    (folder / "runner.py").write_bytes(b"different runner")
    with pytest.raises(ValueError, match="executing code differs"):
        authorization.verify_frozen_request(folder, "a" * 32, "b" * 64, digest)


@pytest.fixture
def reconstructed_e005_package(tmp_path):
    source = tmp_path / "source"
    for name in authorization.CODE_FILES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic E005 file: {name}\n".encode("utf-8"))
    snapshot_id, manifest_digest = "a" * 32, "b" * 64
    old = authorization.freeze(source, snapshot_id, manifest_digest)
    runner_source = source / "scripts/run_e005_development.py"
    runner_source.write_bytes(runner_source.read_bytes().replace(b"synthetic", b"Synthetic", 1))
    frozen = authorization.freeze(source, snapshot_id, manifest_digest)
    frozen_folder = source / frozen["directory"]
    reconstructed = tmp_path / "checkout"
    for name in (*authorization.CODE_FILES, "code_manifest.json", "approval_request.json"):
        target = reconstructed / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((frozen_folder / name).read_bytes())
    return reconstructed, source / old["directory"], snapshot_id, manifest_digest, frozen["code_sha256"]


def test_reconstructed_package_rejects_one_changed_byte_in_each_protected_file(reconstructed_e005_package):
    checkout, _, snapshot_id, manifest_digest, code_digest = reconstructed_e005_package
    request = authorization.verify_frozen_request(checkout, snapshot_id, manifest_digest, code_digest)
    assert request == (checkout / "approval_request.json").read_bytes()
    assert len(json.loads((checkout / "code_manifest.json").read_bytes())["files"]) == 12
    for name in authorization.CODE_FILES:
        path = checkout / name
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with pytest.raises(ValueError, match="executing code differs"):
            authorization.verify_frozen_request(checkout, snapshot_id, manifest_digest, code_digest)
        path.write_bytes(original)


@pytest.mark.parametrize(("name", "error"), [
    ("code_manifest.json", "executing code differs"),
    ("approval_request.json", "approval request differs"),
])
def test_reconstructed_package_rejects_stale_metadata(reconstructed_e005_package, name, error):
    checkout, old, snapshot_id, manifest_digest, code_digest = reconstructed_e005_package
    (checkout / name).write_bytes((old / name).read_bytes())
    with pytest.raises(ValueError, match=error):
        authorization.verify_frozen_request(checkout, snapshot_id, manifest_digest, code_digest)


@pytest.mark.parametrize("field", ["protocol_sha256", "scope"])
def test_reconstructed_package_rejects_modified_protocol_or_dates(reconstructed_e005_package, field):
    checkout, _, snapshot_id, manifest_digest, code_digest = reconstructed_e005_package
    path = checkout / "approval_request.json"
    request = json.loads(path.read_bytes())
    if field == "protocol_sha256":
        request[field] = "f" * 64
    else:
        request[field]["validation"]["exclusive_end_utc"] = "2024-01-02T00:00:00+00:00"
    path.write_bytes(authorization.canonical(request))
    with pytest.raises(ValueError, match="approval request differs"):
        authorization.verify_frozen_request(checkout, snapshot_id, manifest_digest, code_digest)


@pytest.fixture
def synthetic_github_approval(tmp_path, monkeypatch):
    request = b"test-only synthetic request"
    digest = sha256(request).hexdigest()
    signer = "a" * 40
    run = {
        "id": 123, "path": ".github/workflows/e005-approval.yml@main", "event": "workflow_dispatch",
        "head_branch": "main", "head_sha": signer, "run_attempt": 1,
        "status": "completed", "conclusion": "success",
        "repository": {"full_name": authorization.REPO},
        "head_repository": {"full_name": authorization.REPO},
        "actor": {"type": "User", "id": 41}, "triggering_actor": {"type": "User", "id": 41},
    }
    reviews = [{"state": "approved", "comment": f"E005 approve sha256:{digest}",
                "user": {"type": "User", "id": 52}, "environments": [{"name": authorization.ENVIRONMENT}]}]
    trusted_cli = tmp_path / "gh.exe"
    trusted_cli.touch()
    monkeypatch.setattr(authorization, "GH", trusted_cli)
    monkeypatch.setattr(authorization, "policy", lambda: (52, signer))
    responses = [run, reviews, [{"verificationResult": {"test_only": True}}]]
    calls = []

    def gh(args, **kwargs):
        calls.append(args)
        assert args[0] == str(trusted_cli)
        assert not {"GH_TOKEN", "GH_HOST", "GH_CONFIG_DIR", "HTTPS_PROXY"} & set(kwargs["env"])
        if args[1] == "attestation":
            assert Path(args[3]).read_bytes() == f"quantlab-e005-decision-v1\n123\n{digest}\n".encode("ascii")
        return SimpleNamespace(returncode=0, stdout=json.dumps(responses[len(calls) - 1]).encode())

    monkeypatch.setattr(authorization.subprocess, "run", gh)
    return request, signer, digest, responses, calls


def test_github_verifier_pins_authority_and_binds_specific_run(synthetic_github_approval, monkeypatch):
    request, signer, digest, _, calls = synthetic_github_approval
    monkeypatch.setenv("GH_HOST", "untrusted.invalid")
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    monkeypatch.setenv("GH_CONFIG_DIR", "synthetic-config")
    monkeypatch.setenv("HTTPS_PROXY", "https://untrusted.invalid")
    expected = {"run_id": "123", "reviewer_id": 52, "workflow_commit": signer,
                "request_sha256": digest, "decision": "approved"}
    assert authorization.require_independent_authorization(request, "123") == expected
    assert calls[0][-1] == f"/repos/{authorization.REPO}/actions/runs/123"
    assert calls[1][-1] == calls[0][-1] + "/approvals"
    verify = calls[2]
    assert verify[verify.index("--signer-workflow") + 1] == authorization.WORKFLOW
    assert verify[verify.index("--signer-digest") + 1] == signer
    assert verify[verify.index("--source-ref") + 1] == "refs/heads/main"
    assert "--deny-self-hosted-runners" in verify


@pytest.mark.parametrize(("key", "value"), [
    ("conclusion", "cancelled"), ("status", "in_progress"), ("run_attempt", 2),
    ("id", 456), ("head_sha", "b" * 40), ("head_branch", "feature/other"),
    ("path", ".github/workflows/other.yml@main"),
    ("path", ".github/workflows/e005-approval.yml"),
    ("path", ".github/workflows/e005-approval.yml@feature/other"),
    ("path", ".github/workflows/e005-approval.yml@main-extra"),
    ("repository", {"full_name": "other/quantitative-research-lab"}),
    ("head_repository", {"full_name": "other/quantitative-research-lab"}),
    ("event", "push"),
    ("actor", {"type": "User", "id": 52}), ("triggering_actor", {"type": "User", "id": 52}),
])
def test_github_verifier_rejects_wrong_workflow_status_or_self_approval(synthetic_github_approval, key, value):
    request, _, _, responses, calls = synthetic_github_approval
    responses[0][key] = value
    with pytest.raises(PermissionError):
        authorization.require_independent_authorization(request, "123")
    assert len(calls) == 2


@pytest.mark.parametrize(("key", "value"), [
    ("state", "rejected"), ("comment", "Approved"), ("user", {"type": "User", "id": 99}),
    ("environments", [{"name": "other-environment"}]),
])
def test_green_run_without_exact_review_is_refused(synthetic_github_approval, key, value):
    request, _, _, responses, calls = synthetic_github_approval
    responses[1][0][key] = value
    with pytest.raises(PermissionError):
        authorization.require_independent_authorization(request, "123")
    assert len(calls) == 2



def test_successful_workflow_without_a_review_is_refused(synthetic_github_approval):
    request, _, _, responses, calls = synthetic_github_approval
    responses[1] = []
    with pytest.raises(PermissionError, match="exactly one decision"):
        authorization.require_independent_authorization(request, "123")
    assert len(calls) == 2


def test_no_attestation_or_reused_approval_for_changed_request(synthetic_github_approval):
    request, _, _, responses, calls = synthetic_github_approval
    responses[2] = []
    with pytest.raises(PermissionError, match="No verified approval"):
        authorization.require_independent_authorization(request, "123")
    calls.clear()
    with pytest.raises(PermissionError, match="explicit approval"):
        authorization.require_independent_authorization(request + b"changed", "123")


def test_no_local_policy_or_path_to_override_it(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "winreg", None)
    monkeypatch.setenv("HOME", "synthetic-home")
    monkeypatch.setenv("E005_APPROVAL_POLICY", "synthetic-policy.json")
    with pytest.raises(PermissionError, match="machine policy"):
        authorization.require_independent_authorization(b"synthetic request", "123")
    with pytest.raises(PermissionError, match="numeric --approval-run-id"):
        authorization.require_independent_authorization(b"synthetic request", "../123")
