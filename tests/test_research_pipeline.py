from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from quantlab.research import pipeline


EXPERIMENT = "E004_synthetic"
INPUT = f"data/research/{EXPERIMENT}/development/example.csv"
RUN_ID = "a" * 32
SYNTHETIC_INPUT = b"date,value\n2027-01-01,1\n"


def assert_execution_blocked(plan):
    assert plan["authorization"] == {
        "status": "unverified",
        "reason": "independent_verifier_not_configured",
    }
    assert plan["execution_allowed"] is False


@pytest.fixture
def draft(tmp_path):
    relative = pipeline.scaffold(tmp_path, EXPERIMENT)
    return tmp_path / relative


@pytest.fixture
def complete(draft):
    protocol = json.loads(draft.read_bytes())
    protocol.update(
        question="Does synthetic persistence improve MAE?",
        rationale="Check only the planning workflow.",
        h0="No improvement in MAE.",
        h1="Lower MAE in development.",
        instrument="Synthetic BTCUSDT",
        forecast_time_utc="After the daily UTC close.",
        target="Next daily close return.",
        features=["previous_return"],
        feature_availability="Previous return is known at the forecast time.",
        benchmarks=["zero return"],
        models=["fixed Ridge"],
        tuning="None. Hyperparameters are fixed.",
        primary_metric="MAE",
        secondary_metrics=["RMSE"],
        success_criteria="Lower pooled MAE and improvement on most folds.",
        development={"start": "2027-01-01", "end": "2027-06-30"},
        reserved_holdout={"start": "2027-07-02", "end": "2027-12-31"},
        inputs=[{"path": INPUT, "sha256": sha256(SYNTHETIC_INPUT).hexdigest(),
                 "provenance": "Generated synthetic fixture."}],
        stability_analysis="Compare MAE differences across validation folds.",
        leakage_audit="Verify timestamps and fold-local preprocessing.",
    )
    draft.write_text(json.dumps(protocol), encoding="utf-8")
    return draft, protocol


def test_scaffold_is_incomplete_and_cannot_be_overwritten(tmp_path, draft, capsys):
    original = draft.read_bytes()
    assert pipeline.main(["validate", EXPERIMENT], root=tmp_path) == 2
    assert "Protocol question" in capsys.readouterr().err
    assert pipeline.main(["scaffold", EXPERIMENT], root=tmp_path) == 2
    assert "already exists" in capsys.readouterr().err
    assert draft.read_bytes() == original


def test_dry_run_without_approval_reads_no_data_and_writes_no_results(tmp_path, complete, monkeypatch, capsys):
    path, _ = complete
    dataset = tmp_path / INPUT
    dataset.parent.mkdir(parents=True)
    dataset.write_bytes(SYNTHETIC_INPUT)
    original_open = Path.open

    def deny_input_reads(self, *args, **kwargs):
        assert self != dataset
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_input_reads)
    assert pipeline.main(["dry-run", EXPERIMENT, "--run-id", RUN_ID], root=tmp_path) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["signature"] == "missing"
    assert_execution_blocked(plan)
    assert plan["scope"] == "development-only"
    assert plan["protocol_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert plan["inputs"] == [{
        "path": INPUT, "present": True, "expected_sha256": sha256(SYNTHETIC_INPUT).hexdigest(),
    }]
    assert plan["artifacts"]["manifest"] == f"reports/research_pipeline/{EXPERIMENT}/{RUN_ID}/manifest.json"
    assert not (tmp_path / "reports").exists()


def test_dry_run_refuses_to_overwrite_an_existing_run(tmp_path, complete, capsys):
    existing = tmp_path / "reports" / "research_pipeline" / EXPERIMENT / RUN_ID
    existing.mkdir(parents=True)
    manifest = existing / "manifest.json"
    manifest.write_bytes(b"original")
    assert pipeline.main(["dry-run", EXPERIMENT, "--run-id", RUN_ID], root=tmp_path) == 2
    assert "Run directory already exists" in capsys.readouterr().err
    assert manifest.read_bytes() == b"original"


@pytest.mark.parametrize("bad_path", [
    "data/processed/btc_daily_features.csv",
    "reports/E002_final_holdout/holdout_predictions.csv",
    f"data/research/{EXPERIMENT}/holdout/example.csv",
    f"data/research/{EXPERIMENT}/development/../../../../processed/btc_daily_features.csv",
    f"data/research/{EXPERIMENT}/development/e002_holdout.csv",
    "C:/project/data/processed/btc_daily_features.csv",
])
def test_blocks_holdout_paths_before_inspecting_them(tmp_path, complete, monkeypatch, bad_path):
    path, protocol = complete
    protocol["inputs"][0]["path"] = bad_path
    path.write_text(json.dumps(protocol), encoding="utf-8")
    original_lstat = Path.lstat

    def look_up_protocol_only(self):
        assert self in path.parents or self == path
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", look_up_protocol_only)
    with pytest.raises(pipeline.ProtocolError):
        pipeline.read_protocol(tmp_path, EXPERIMENT)


def test_rejects_a_declared_frozen_hash_under_an_allowed_name(tmp_path, complete):
    path, protocol = complete
    protocol["inputs"][0]["sha256"] = next(iter(pipeline.FROZEN_INPUTS))
    path.write_text(json.dumps(protocol), encoding="utf-8")
    with pytest.raises(pipeline.ProtocolError, match="frozen E002 input SHA-256"):
        pipeline.read_protocol(tmp_path, EXPERIMENT)


def test_rejects_an_input_hard_link_to_a_synthetic_holdout(tmp_path, complete):
    sealed = tmp_path / "data" / "processed" / "synthetic_holdout.csv"
    sealed.parent.mkdir(parents=True)
    sealed.write_bytes(SYNTHETIC_INPUT)
    alias = tmp_path / INPUT
    alias.parent.mkdir(parents=True)
    try:
        alias.hardlink_to(sealed)
    except OSError as error:
        pytest.skip(f"Hard links are unavailable: {error}")
    with pytest.raises(pipeline.ProtocolError, match="without hard links"):
        pipeline.read_protocol(tmp_path, EXPERIMENT)


@pytest.mark.parametrize("reserved_id", ["E001_funding_rate", "E002_range", "E003_range_nonlinear", "../E004_test"])
def test_rejects_reserved_ids_and_traversal(tmp_path, reserved_id):
    with pytest.raises(pipeline.ProtocolError):
        pipeline.scaffold(tmp_path, reserved_id)
    assert not (tmp_path / "experiments").exists()


def test_rejects_a_holdout_without_a_full_purge_gap(tmp_path, complete):
    path, protocol = complete
    protocol["reserved_holdout"]["start"] = "2027-07-01"
    path.write_text(json.dumps(protocol), encoding="utf-8")
    with pytest.raises(pipeline.ProtocolError, match="full purge gap"):
        pipeline.read_protocol(tmp_path, EXPERIMENT)


def test_rejects_self_asserted_approval(tmp_path, complete):
    path, protocol = complete
    protocol["approved"] = True
    path.write_text(json.dumps(protocol), encoding="utf-8")
    with pytest.raises(pipeline.ValidationError, match="Extra inputs"):
        pipeline.read_protocol(tmp_path, EXPERIMENT)


def test_rejects_duplicate_protocol_keys(tmp_path, complete):
    path, _ = complete
    path.write_bytes(path.read_bytes().replace(b'{', b'{"version": 2, ', 1))
    with pytest.raises(pipeline.ProtocolError, match="Duplicate key"):
        pipeline.read_protocol(tmp_path, EXPERIMENT)


@pytest.fixture
def synthetic_signature(tmp_path, complete):
    if shutil.which("ssh-keygen") is None:
        pytest.skip("OpenSSH is required for the signature integration test.")
    path, _ = complete
    workspace = tmp_path / "project"
    workspace.mkdir()
    (tmp_path / "experiments").rename(workspace / "experiments")
    path = workspace / path.relative_to(tmp_path)
    signer = tmp_path / "test-signer"
    signer.mkdir()
    key = signer / "ephemeral-test-key"
    # The key only exercises the signature format and is never an approval authority.
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True, capture_output=True)

    protocol, digest = pipeline.read_protocol(workspace, EXPERIMENT)
    request = signer / "approval-request"
    assert pipeline.main(["approval-request", EXPERIMENT, "--output", str(request)], root=workspace) == 0
    request_bytes = request.read_bytes()
    assert json.loads(request_bytes) == {
        "purpose": "approve-development-protocol",
        "experiment_id": EXPERIMENT,
        "protocol_version": protocol.version,
        "protocol_sha256": digest,
    }
    assert pipeline.main(["approval-request", EXPERIMENT, "--output", str(request)], root=workspace) == 2
    assert request.read_bytes() == request_bytes
    subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", pipeline.APPROVAL_NAMESPACE, str(request)],
        check=True, capture_output=True,
    )
    request.with_suffix(".sig").rename(path.with_name("approval.sig"))
    return workspace, path, key


def test_valid_signature_from_unknown_signer_cannot_authorize(synthetic_signature):
    workspace, _, _ = synthetic_signature
    protocol, digest = pipeline.read_protocol(workspace, EXPERIMENT)
    plan = pipeline.plan_run(workspace, protocol, digest)
    assert plan["signature"] == "valid"
    assert_execution_blocked(plan)


def test_substituted_home_and_fake_trust_list_cannot_authorize(synthetic_signature, monkeypatch):
    workspace, _, key = synthetic_signature
    fake_home = key.parent
    fake_list = fake_home / ".config" / "quantlab" / "allowed_signers"
    fake_list.parent.mkdir(parents=True)
    public_key = key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    fake_list.write_text(f"research-lead {public_key}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("QUANTLAB_ALLOWED_SIGNERS", str(fake_list))
    original_open = Path.open

    def reject_trust_reads(self, *args, **kwargs):
        assert self != fake_list
        return original_open(self, *args, **kwargs)

    def reject_home_lookup(cls):
        pytest.fail("Signature inspection must not consult Path.home()")

    monkeypatch.setattr(Path, "open", reject_trust_reads)
    monkeypatch.setattr(Path, "home", classmethod(reject_home_lookup))
    protocol, digest = pipeline.read_protocol(workspace, EXPERIMENT)
    plan = pipeline.plan_run(workspace, protocol, digest)
    assert plan["signature"] == "valid"
    assert_execution_blocked(plan)


@pytest.mark.parametrize("field", ["bytes", "version", "experiment_id", "namespace"])
def test_signature_rejects_mismatched_request(synthetic_signature, monkeypatch, field):
    workspace, path, _ = synthetic_signature
    protocol, digest = pipeline.read_protocol(workspace, EXPERIMENT)
    if field == "bytes":
        path.write_bytes(path.read_bytes() + b"\n")
        protocol, digest = pipeline.read_protocol(workspace, EXPERIMENT)
    elif field == "version":
        protocol = protocol.model_copy(update={"version": protocol.version + 1})
    elif field == "experiment_id":
        other_id = "E005_other"
        other_path = workspace / pipeline.experiment_directory(other_id)
        other_path.mkdir()
        shutil.copyfile(path.with_name("approval.sig"), other_path / "approval.sig")
        other_input = protocol.inputs[0].model_copy(update={
            "path": f"data/research/{other_id}/development/example.csv",
        })
        protocol = protocol.model_copy(update={"experiment_id": other_id, "inputs": [other_input]})
    else:
        monkeypatch.setattr(pipeline, "APPROVAL_NAMESPACE", "unrelated-test-namespace")

    plan = pipeline.plan_run(workspace, protocol, digest)
    assert plan["signature"] == "not_validated"
    assert_execution_blocked(plan)


def test_malformed_signature_cannot_authorize(tmp_path, complete):
    path, _ = complete
    path.with_name("approval.sig").write_bytes(b"invalid synthetic signature")
    protocol, digest = pipeline.read_protocol(tmp_path, EXPERIMENT)
    plan = pipeline.plan_run(tmp_path, protocol, digest)
    assert plan["signature"] in {"not_validated", "unavailable"}
    assert_execution_blocked(plan)


def test_missing_signature_tool_leaves_authorization_blocked(tmp_path, complete, monkeypatch):
    path, _ = complete
    path.with_name("approval.sig").write_bytes(b"synthetic signature")

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("ssh-keygen unavailable")

    monkeypatch.setattr(subprocess, "run", unavailable)
    protocol, digest = pipeline.read_protocol(tmp_path, EXPERIMENT)
    plan = pipeline.plan_run(tmp_path, protocol, digest)
    assert plan["signature"] == "unavailable"
    assert_execution_blocked(plan)


@pytest.mark.parametrize("option", ["--allowed-signers", "--trust-file", "--signature"])
def test_cli_does_not_accept_alternate_approval_paths(tmp_path, complete, option, capsys):
    with pytest.raises(SystemExit) as error:
        pipeline.main(["dry-run", EXPERIMENT, option, "untrusted-file"], root=tmp_path)
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_signature_path_cannot_point_to_an_external_file(tmp_path, complete):
    path, _ = complete
    external_file = tmp_path / "test-signature"
    external_file.write_bytes(b"synthetic signature")
    signature = path.with_name("approval.sig")
    try:
        signature.hardlink_to(external_file)
    except OSError as error:
        pytest.skip(f"Hard links are unavailable: {error}")
    protocol, digest = pipeline.read_protocol(tmp_path, EXPERIMENT)
    with pytest.raises(pipeline.ProtocolError, match="without hard links"):
        pipeline.plan_run(tmp_path, protocol, digest)
