"""Check Git changes for alterations to historical research artifacts."""

import argparse
import subprocess
import sys


PROTECTED_DIRECTORIES = (
    "experiments/E001_funding_rate/",
    "experiments/E002_range/",
    "experiments/E003_range_nonlinear/",
    "reports/E001_funding_rate/",
    "reports/E002_range/",
    "reports/E002_final_holdout/",
    "reports/E003_range_nonlinear/",
    "reports/E001_E003_synthesis/",
    "reports/pre_holdout_audit/",
)
PROTECTED_FILES = {
    "config/research_protocol.yaml",
    "reports/data_download_report.json",
    "reports/data_download_report.md",
    "reports/data_quality_report.json",
}


def protected_changes(diff: bytes) -> set[tuple[str, str]]:
    """Filter NUL-delimited Git name-status output with rename detection disabled."""
    fields = diff.split(b"\0")
    if fields.pop() != b"" or len(fields) % 2:
        raise ValueError("Malformed Git name-status output.")

    violations = set()
    for status, raw_path in zip(fields[::2], fields[1::2], strict=True):
        if status not in (b"A", b"D", b"M", b"T", b"U", b"X", b"B") or not raw_path:
            raise ValueError("Unexpected Git change record.")
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if path in PROTECTED_FILES or path.startswith(PROTECTED_DIRECTORIES):
            violations.add((path, status.decode("ascii")))
    return violations


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def check_changes(base: str, head: str | None) -> set[tuple[str, str]]:
    base_commit = git("rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}")
    base_sha = base_commit.decode("ascii").strip()
    diff_args = (
        "diff", "--name-status", "-z", "--no-renames", "--no-relative",
        "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
    )
    if head is not None:
        head_commit = git("rev-parse", "--verify", "--end-of-options", f"{head}^{{commit}}")
        return protected_changes(git(*diff_args, base_sha, head_commit.decode("ascii").strip(), "--"))

    # Check the index separately in case an unstaged edit masks a staged change.
    staged = protected_changes(git(*diff_args, "--cached", base_sha, "--"))
    working_tree = protected_changes(git(*diff_args, base_sha, "--"))
    return staged | working_tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="main", help="base Git revision (default: main)")
    parser.add_argument("--head", help="candidate Git revision (default: index and tracked working tree)")
    args = parser.parse_args(argv)

    try:
        violations = check_changes(args.base, args.head)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        print(f"Research Safety Guard could not read the Git comparison: {detail}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"Research Safety Guard could not check changes: {error}", file=sys.stderr)
        return 2

    if violations:
        print("Research Safety Guard blocked changes to historical artifacts:", file=sys.stderr)
        for path, status in sorted(violations):
            print(f"  {status} {ascii(path)}", file=sys.stderr)
        return 1

    print("Research Safety Guard passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
