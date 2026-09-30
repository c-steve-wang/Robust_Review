#!/usr/bin/env python3
"""Check the separately distributed PDF dataset against its release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--papers-dir", type=Path, default=ROOT / "papers")
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "data/dataset_manifest.json"
    )
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        expected = {row["path"]: row for row in manifest["files"]}
        if not expected or len(expected) != len(manifest["files"]):
            raise ValueError("Manifest must contain unique, nonempty file paths")
        observed = {
            path.relative_to(args.papers_dir).as_posix()
            for path in args.papers_dir.rglob("*.pdf")
            if not path.name.startswith("._")
        }
        errors = [f"missing: {path}" for path in sorted(set(expected) - observed)]
        errors += [f"unexpected: {path}" for path in sorted(observed - set(expected))]
        for relative in sorted(set(expected) & observed):
            path = args.papers_dir / relative
            if not path.resolve().is_relative_to(args.papers_dir.resolve()):
                raise ValueError(f"Path escapes dataset root: {relative}")
            row = expected[relative]
            if path.stat().st_size != row["size_bytes"]:
                errors.append(f"size mismatch: {relative}")
                continue
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != row["sha256"]:
                errors.append(f"SHA-256 mismatch: {relative}")
        print(
            json.dumps(
                {
                    "expected_files": len(expected),
                    "observed_files": len(observed),
                    "errors": errors,
                },
                indent=2,
            )
        )
        return 1 if errors else 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
