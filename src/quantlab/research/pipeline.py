"""Scaffold, validate and plan new research experiments without executing them."""

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError


APPROVAL_NAMESPACE = "quantlab-research-approval-v1"
EXPERIMENT_ID = re.compile(r"E([0-9]{3})_[a-z][a-z0-9_]{0,47}")
RUN_ID = re.compile(r"[a-f0-9]{32}")
DATA_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\.(?:csv|parquet)")
# SHA-256 of the local data inputs listed in the frozen E002 manifest.
FROZEN_INPUTS = {
    "8fdea00914b36b8afff0677371cef1298557b90e1f1caaf600e8b530102d9c47",
    "1bd35658cae6d4cef6b05eb48fbf2c08b824097a1e696dd34f8393b8bf71b387",
    "4328ccef9a76ae271ff9c36a50950796bf3c855fb22edd5ac898aeb49a374072",
}
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Texts = Annotated[list[Text], Field(min_length=1)]
PositiveInt = Annotated[int, Field(gt=0)]


class ProtocolError(ValueError):
    pass


class ProtocolSection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Period(ProtocolSection):
    start: date
    end: date


class DevelopmentInput(ProtocolSection):
    path: Text
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    provenance: Text


class Protocol(ProtocolSection):
    experiment_id: Text
    version: PositiveInt
    question: Text
    rationale: Text
    h0: Text
    h1: Text
    instrument: Text
    forecast_time_utc: Text
    target: Text
    horizon_days: PositiveInt
    features: Texts
    feature_availability: Text
    benchmarks: Texts
    models: Texts
    tuning: Text
    primary_metric: Text
    secondary_metrics: Texts
    success_criteria: Text
    walk_forward_folds: Annotated[int, Field(ge=2)]
    purge_days: PositiveInt
    development: Period
    reserved_holdout: Period
    inputs: Annotated[list[DevelopmentInput], Field(min_length=1)]
    random_seed: Annotated[int, Field(ge=0)]
    stability_analysis: Text
    leakage_audit: Text


def experiment_directory(experiment_id: str) -> Path:
    match = EXPERIMENT_ID.fullmatch(experiment_id)
    if match is None or int(match[1]) < 4:
        raise ProtocolError("Use a new experiment ID such as E004_example. E001–E003 are reserved.")
    return Path("experiments", experiment_id)


def scoped_path(root: Path, relative: Path, *, directory: bool = False) -> Path:
    """Check fixed project paths without following links or junctions."""
    path = root
    for index, part in enumerate(relative.parts):
        path /= part
        try:
            info = path.lstat()
        except FileNotFoundError:
            break
        # Windows name-surrogate reparse points redirect to another filesystem name.
        redirects = getattr(info, "st_reparse_tag", 0) & 0x20000000
        if stat.S_ISLNK(info.st_mode) or redirects:
            raise ProtocolError(f"Links and junctions are forbidden: {relative.as_posix()}")
        is_directory = directory or index < len(relative.parts) - 1
        if is_directory and not stat.S_ISDIR(info.st_mode):
            raise ProtocolError(f"Expected a directory: {path.relative_to(root).as_posix()}")
        if not is_directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ProtocolError(f"Expected a regular file without hard links: {relative.as_posix()}")
    return root / relative


def scaffold(root: Path, experiment_id: str) -> Path:
    relative = experiment_directory(experiment_id)
    directory = scoped_path(root, relative, directory=True)
    directory.mkdir(parents=True, exist_ok=False)
    protocol = dict.fromkeys(Protocol.model_fields)
    protocol.update(
        experiment_id=experiment_id,
        version=1,
        horizon_days=1,
        purge_days=1,
        walk_forward_folds=5,
        random_seed=2026,
        development={"start": None, "end": None},
        reserved_holdout={"start": None, "end": None},
        features=[],
        benchmarks=[],
        models=[],
        secondary_metrics=[],
        inputs=[{
            "path": f"data/research/{experiment_id}/development/snapshot.csv",
            "sha256": None,
            "provenance": None,
        }],
    )
    path = directory / "protocol.json"
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(protocol, output, indent=2)
        output.write("\n")
    return relative / path.name


def development_path(root: Path, experiment_id: str, name: str) -> Path:
    prefix = f"data/research/{experiment_id}/development/"
    filename = name.removeprefix(prefix)
    if not name.startswith(prefix) or not DATA_NAME.fullmatch(filename):
        raise ProtocolError(f"Development inputs must be CSV or Parquet files directly under {prefix}")
    if any(marker in filename for marker in ("holdout", "e002", "btc_daily_features", "btc_daily_raw")):
        raise ProtocolError("Holdout and historical snapshot paths are forbidden.")
    return scoped_path(root, Path(name))


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("Duplicate key in protocol JSON.")
        result[key] = value
    return result


def read_protocol(root: Path, experiment_id: str) -> tuple[Protocol, str]:
    path = scoped_path(root, experiment_directory(experiment_id) / "protocol.json")
    raw = path.read_bytes()
    json.loads(raw, object_pairs_hook=unique_object)
    protocol = Protocol.model_validate_json(raw)
    if protocol.experiment_id != experiment_id:
        raise ProtocolError("Protocol experiment_id must match its directory.")
    periods = (protocol.development, protocol.reserved_holdout)
    if any(period.start > period.end for period in periods):
        raise ProtocolError("Each date range must be chronological.")
    if protocol.purge_days < protocol.horizon_days:
        raise ProtocolError("The purge must cover the full target horizon.")
    if (protocol.reserved_holdout.start - protocol.development.end).days <= protocol.purge_days:
        raise ProtocolError("Reserve separate holdout dates after a full purge gap.")
    if any(feature.lower().startswith("target_") for feature in protocol.features):
        raise ProtocolError("Features must exclude target columns.")
    if len({item.path for item in protocol.inputs}) != len(protocol.inputs):
        raise ProtocolError("List each input path only once.")
    for item in protocol.inputs:
        if item.sha256 in FROZEN_INPUTS:
            raise ProtocolError("A frozen E002 input SHA-256 is forbidden.")
        development_path(root, experiment_id, item.path)
    return protocol, sha256(raw).hexdigest()


def approval_request(protocol: Protocol, digest: str) -> bytes:
    request = {
        "purpose": "approve-development-protocol",
        "experiment_id": protocol.experiment_id,
        "protocol_version": protocol.version,
        "protocol_sha256": digest,
    }
    return (json.dumps(request, indent=2) + "\n").encode("ascii")


def inspect_signature(root: Path, protocol: Protocol, digest: str) -> str:
    """Check the signature against the request using the key embedded in the signature."""
    relative = experiment_directory(protocol.experiment_id) / "approval.sig"
    signature = scoped_path(root, relative)
    if not signature.is_file():
        return "missing"
    try:
        inspection = subprocess.run(
            ["ssh-keygen", "-Y", "check-novalidate", "-n", APPROVAL_NAMESPACE, "-s", str(signature)],
            input=approval_request(protocol, digest),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return "valid" if inspection.returncode == 0 else "not_validated"


def plan_run(root: Path, protocol: Protocol, digest: str, run_id: str | None = None) -> dict:
    run_id = uuid4().hex if run_id is None else run_id
    if not RUN_ID.fullmatch(run_id):
        raise ProtocolError("Run ID must contain 32 lowercase hexadecimal characters.")
    directory = Path("reports", "research_pipeline", protocol.experiment_id, run_id)
    if scoped_path(root, directory, directory=True).exists():
        raise ProtocolError(f"Run directory already exists: {directory.as_posix()}")
    return {
        "mode": "dry-run",
        "experiment_id": protocol.experiment_id,
        "protocol_version": protocol.version,
        "protocol_sha256": digest,
        "signature": inspect_signature(root, protocol, digest),
        "authorization": {
            "status": "unverified",
            "reason": "independent_verifier_not_configured",
        },
        "execution_allowed": False,
        "scope": "development-only",
        "target": protocol.target,
        "models": protocol.models,
        "benchmarks": protocol.benchmarks,
        "primary_metric": protocol.primary_metric,
        "random_seed": protocol.random_seed,
        "walk_forward": {
            "method": "expanding-window",
            "folds": protocol.walk_forward_folds,
            "purge_days": protocol.purge_days,
            "development": protocol.development.model_dump(mode="json"),
        },
        "inputs": [
            {
                "path": item.path,
                "expected_sha256": item.sha256,
                "present": development_path(root, protocol.experiment_id, item.path).is_file(),
            }
            for item in protocol.inputs
        ],
        "run_id": run_id,
        "artifacts": {
            "directory": directory.as_posix(),
            "manifest": (directory / "manifest.json").as_posix(),
            "report": (directory / "report.md").as_posix(),
        },
        "planned_steps": [
            "Verify approval and development-only data provenance and hashes.",
            "Reserve an exclusive run directory and record the manifest.",
            "Fit fold-local transforms and models, then evaluate on development folds.",
            "Write an aggregate report for independent review.",
        ],
    }


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("scaffold", "validate", "approval-request", "dry-run"):
        subparser = commands.add_parser(command)
        subparser.add_argument("experiment_id")
        if command == "approval-request":
            subparser.add_argument("--output", type=Path, help="new request file outside the repository")
        elif command == "dry-run":
            subparser.add_argument("--run-id")
    args = parser.parse_args(argv)
    root = Path.cwd() if root is None else root

    try:
        if args.command == "scaffold":
            path = scaffold(root, args.experiment_id)
            print(f"Created draft: {path.as_posix()}")
            return 0
        protocol, digest = read_protocol(root, args.experiment_id)
        if args.command == "validate":
            print(f"Valid protocol v{protocol.version}, SHA-256 {digest}")
        elif args.command == "approval-request":
            request = approval_request(protocol, digest)
            if args.output is None:
                sys.stdout.buffer.write(request)
            else:
                if args.output.resolve().is_relative_to(root.resolve()):
                    raise ProtocolError("Write the approval request outside the repository.")
                with args.output.open("xb") as output:
                    output.write(request)
        else:
            print(json.dumps(plan_run(root, protocol, digest, args.run_id), indent=2))
        return 0
    except ValidationError as error:
        for issue in error.errors(include_input=False, include_context=False, include_url=False):
            location = ".".join(map(str, issue["loc"]))
            print(f"Protocol {location}: {issue['msg']}", file=sys.stderr)
    except json.JSONDecodeError as error:
        print(f"Invalid protocol JSON at line {error.lineno}, column {error.colno}.", file=sys.stderr)
    except FileExistsError:
        print("The destination already exists. Nothing was overwritten.", file=sys.stderr)
    except (OSError, ValueError) as error:
        print(f"Research pipeline: {error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
