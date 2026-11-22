"""Freeze E005 execution sources and verify a protected GitHub approval."""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from quantlab.research.pipeline import scoped_path
from scripts.e005_snapshot import CUTOFF, EXPERIMENT, PROTOCOL, PROTOCOL_SHA256, SPANS


REPO = "doomtamer/quantitative-research-lab"
WORKFLOW_PATH = ".github/workflows/e005-approval.yml"
WORKFLOW = f"{REPO}/{WORKFLOW_PATH}"
ENVIRONMENT = "e005-research-approval"
POLICY_KEY = r"SOFTWARE\QuantLab\E005"
GH = Path("C:/Program Files/GitHub CLI/gh.exe")
CODE_FILES = (
    "pyproject.toml",
    "uv.lock",
    "scripts/e005_authorization.py",
    "scripts/e005_snapshot.py",
    "scripts/run_e005_development.py",
    "src/quantlab/__init__.py",
    "src/quantlab/research/__init__.py",
    "src/quantlab/research/e005_backtest.py",
    "src/quantlab/research/e005_report.py",
    "src/quantlab/research/pipeline.py",
    PROTOCOL.as_posix(),
    "experiments/E005_trend_backtest/e005-approval.workflow.template.yml",
)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def code_files(root):
    return {name: scoped_path(root, Path(name)).read_bytes() for name in CODE_FILES}


def code_manifest(files):
    return canonical({"format": "quantlab-e005-code-v1",
                      "files": {name: sha256(content).hexdigest() for name, content in files.items()}})


def approval_request(snapshot_id, manifest_sha256, code_sha256):
    if (not re.fullmatch(r"[0-9a-f]{32}", snapshot_id)
            or any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in (manifest_sha256, code_sha256))):
        raise ValueError("Expected a registered snapshot and lowercase SHA-256 digests.")
    return {
        "purpose": "quantlab-e005-development-validation-v1",
        "experiment_id": EXPERIMENT,
        "protocol_version": "1.1",
        "protocol_sha256": PROTOCOL_SHA256,
        "manifest_sha256": manifest_sha256,
        "code_sha256": code_sha256,
        "snapshot_id": snapshot_id,
        "scope": {span.name: {"start_utc": span.start.isoformat(), "exclusive_end_utc": span.end.isoformat()}
                  for span in SPANS},
        "exclusive_cutoff_utc": CUTOFF.isoformat(),
        "funding": "funding_excluded",
        "execution": "traded_open_proxy",
        "signal_availability": "simulation_assumption_before_0100_not_historically_verified",
        "cost_scenarios_bps": [5, 8, 16],
        "strategy": {"signal": "long_flat_sma200_momentum20", "execution_time_utc": "01:00",
                     "initial_equity_usdt": 10000, "allocation_percent": 90},
        "last_candle_open_utc": {span.name: (span.end - span.delta).isoformat() for span in SPANS},
    }


def freeze(root, snapshot_id, manifest_sha256):
    sources = code_files(root)
    manifest = code_manifest(sources)
    digest = sha256(manifest).hexdigest()
    request = canonical(approval_request(snapshot_id, manifest_sha256, digest))
    directory = scoped_path(root, Path("build/e005-frozen") / digest, directory=True)
    directory.mkdir(parents=True, exist_ok=False)
    for name, content in sources.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(content)
    for name, content in (("code_manifest.json", manifest), ("approval_request.json", request)):
        with (directory / name).open("xb") as output:
            output.write(content)
    return {"directory": directory.relative_to(root).as_posix(), "code_sha256": digest,
            "approval_request_sha256": sha256(request).hexdigest()}


def verify_frozen_request(root, snapshot_id, manifest_sha256, code_sha256):
    expected_manifest = code_manifest(code_files(root))
    if (sha256(expected_manifest).hexdigest() != code_sha256
            or scoped_path(root, Path("code_manifest.json")).read_bytes() != expected_manifest):
        raise ValueError("The executing code differs from the frozen source manifest.")
    request = canonical(approval_request(snapshot_id, manifest_sha256, code_sha256))
    if scoped_path(root, Path("approval_request.json")).read_bytes() != request:
        raise ValueError("The approval request differs from the frozen inputs or scope.")
    return request


def policy():
    """Read administrator-enrolled authority from the native Windows machine policy."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, POLICY_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            reviewer_text, reviewer_type = winreg.QueryValueEx(key, "ReviewerId")
            signer, signer_type = winreg.QueryValueEx(key, "WorkflowCommit")
        if (reviewer_type != winreg.REG_SZ or not re.fullmatch(r"[1-9][0-9]{0,19}", reviewer_text)
                or signer_type != winreg.REG_SZ or not re.fullmatch(r"[0-9a-f]{40}", signer)):
            raise ValueError("Invalid machine policy")
        return int(reviewer_text), signer
    except (ImportError, OSError, ValueError, TypeError) as error:
        raise PermissionError("Independent E005 machine policy is absent or invalid.") from error


def gh_json(arguments, directory):
    # Use the independent operator profile, without token, host, config or proxy overrides.
    allowed = {"SYSTEMROOT", "WINDIR", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP"}
    environment = {name: value for name, value in os.environ.items() if name.upper() in allowed}
    environment["GH_PROMPT_DISABLED"] = "1"
    process = subprocess.run([str(GH), *arguments], cwd=directory, env=environment,
                             capture_output=True, timeout=60, check=False)
    if process.returncode != 0:
        raise PermissionError("GitHub rejected the E005 verification request.")
    return json.loads(process.stdout)


def check_review(run, reviews, run_id, reviewer_id, signer, request_digest):
    if (type(run["id"]) is not int or str(run["id"]) != run_id
            or run["path"] != f"{WORKFLOW_PATH}@main" or run["event"] != "workflow_dispatch"
            or run["head_branch"] != "main" or run["head_sha"] != signer
            or run["repository"]["full_name"] != REPO or run["head_repository"]["full_name"] != REPO
            or type(run["run_attempt"]) is not int or run["run_attempt"] != 1
            or run["status"] != "completed" or run["conclusion"] != "success"):
        raise PermissionError("Wrong GitHub run, workflow revision, attempt or status.")
    for actor in (run["actor"], run["triggering_actor"]):
        if actor["type"] != "User" or type(actor["id"]) is not int or actor["id"] <= 0 or actor["id"] == reviewer_id:
            raise PermissionError("E005 requires separate dispatcher and reviewer identities.")
    if not isinstance(reviews, list):
        raise ValueError("Unexpected GitHub review history")
    reviews = [review for review in reviews if any(item["name"] == ENVIRONMENT for item in review["environments"])]
    if len(reviews) != 1:
        raise PermissionError("Expected exactly one decision for the protected E005 environment.")
    review = reviews[0]
    if (review["state"] != "approved" or review["user"]["type"] != "User"
            or type(review["user"]["id"]) is not int or review["user"]["id"] != reviewer_id
            or review["comment"] != f"E005 approve sha256:{request_digest}"):
        raise PermissionError("E005 decision lacks the enrolled reviewer's explicit approval of this request.")


def require_independent_authorization(request, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", run_id):
        raise PermissionError("E005 requires the numeric --approval-run-id.")
    reviewer_id, signer = policy()
    if not GH.is_file():
        raise PermissionError("Install the official GitHub CLI for the independent E005 verifier.")
    digest = sha256(request).hexdigest()
    try:
        with TemporaryDirectory(prefix="e005-attestation-") as directory:
            api = ["api", "--hostname", "github.com", "-H", "Accept: application/vnd.github+json"]
            endpoint = f"/repos/{REPO}/actions/runs/{run_id}"
            run = gh_json([*api, endpoint], directory)
            reviews = gh_json([*api, endpoint + "/approvals"], directory)
            check_review(run, reviews, run_id, reviewer_id, signer, digest)
            subject = Path(directory) / "e005-decision.txt"
            subject.write_bytes(f"quantlab-e005-decision-v1\n{run_id}\n{digest}\n".encode("ascii"))
            verified = gh_json(
                ["attestation", "verify", str(subject), "--hostname", "github.com", "--repo", REPO,
                 "--signer-workflow", WORKFLOW, "--signer-digest", signer, "--source-ref", "refs/heads/main",
                 "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
                 "--deny-self-hosted-runners", "--format", "json"],
                directory,
            )
    except PermissionError:
        raise
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        raise PermissionError("Independent GitHub approval could not be verified.") from error
    if not isinstance(verified, list) or not verified or not all(
        isinstance(result, dict) and result.get("verificationResult") for result in verified
    ):
        raise PermissionError("No verified approval from the protected E005 GitHub workflow.")
    return {"run_id": run_id, "reviewer_id": reviewer_id, "workflow_commit": signer,
            "request_sha256": digest, "decision": "approved"}
