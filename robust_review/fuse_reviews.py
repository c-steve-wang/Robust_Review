#!/usr/bin/env python3
"""Fuse manuscript-Strict and science-core ratings with equal weights."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVIEW_DIR = REPO_ROOT / "baseline_review"
if str(BASELINE_REVIEW_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_REVIEW_DIR))

from review_pdf_scores_openai import latest_attempt_row  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-reviews",
        type=Path,
        required=True,
        help="reviews.jsonl produced by baseline_review with --template strict.",
    )
    parser.add_argument(
        "--science-core-dir",
        type=Path,
        default=REPO_ROOT / "results" / "scicore_branch",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "results" / "scicore_fused.jsonl",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Reject unmatched or failed branch records; default emits missing scores.",
    )
    return parser.parse_args(argv)


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and 1 <= value <= 10 else None
    return None


def review_rating(row: dict[str, Any]) -> float | None:
    review = row.get("review")
    return number(review.get("rating")) if isinstance(review, dict) else None


def reviewer_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("provider") or ""),
        str(row.get("model") or ""),
        str(row.get("reasoning_effort") or ""),
    )


def add_row(
    rows: dict[str, dict[str, Any]],
    value: Any,
    source: str,
    template: str,
    *,
    history: bool = False,
) -> None:
    if not isinstance(value, dict) or value.get("prompt_template") != template:
        raise ValueError(f"{source}: expected {template} review record")
    pdf_id = str(value.get("pdf_id") or "")
    if not pdf_id or not all(reviewer_identity(value)[:2]):
        raise ValueError(f"{source}: missing pdf_id, provider or model")
    paper_id = value.get("paper_id")
    variant = value.get("variant")
    if (
        type(paper_id) is not int
        or paper_id < 1
        or not isinstance(variant, str)
        or not re.fullmatch(r"original|condition_(?:0[1-9]|1[0-9]|20)", variant)
        or pdf_id != f"{paper_id}/{variant}"
    ):
        raise ValueError(f"{source}: inconsistent paper_id, variant, or pdf_id")
    previous = rows.get(pdf_id)
    if previous is not None:
        if not history:
            raise ValueError(f"{source}: duplicate/conflicting record for {pdf_id}")
    # A completed failure invalidates an old success; a matching interrupted
    # attempt does not.
    rows[pdf_id] = latest_attempt_row(previous, value) if history else value


def load_strict_reviews(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        add_row(rows, value, f"{path}:{line_number}", "strict", history=True)
    return rows


def load_science_core_reviews(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("**/reviews/science_core.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        add_row(rows, value, str(path), "science_core")
    return rows


def fuse(
    strict_rows: dict[str, dict[str, Any]],
    core_rows: dict[str, dict[str, Any]],
    *,
    require_complete: bool = False,
) -> list[dict[str, Any]]:
    if not strict_rows and not core_rows:
        raise ValueError("At least one branch must contain review records")
    missing_core = sorted(set(strict_rows) - set(core_rows))
    missing_strict = sorted(set(core_rows) - set(strict_rows))
    if require_complete and (missing_core or missing_strict):
        raise ValueError(
            f"Unmatched records: missing science core={missing_core}; "
            f"missing manuscript Strict={missing_strict}"
        )
    identities = {
        reviewer_identity(row) for row in [*strict_rows.values(), *core_rows.values()]
    }
    if len(identities) != 1 or not all(next(iter(identities))[:2]):
        raise ValueError(
            f"Branches contain mixed provider/model/reasoning configurations: {sorted(identities)}"
        )
    for branch in (strict_rows, core_rows):
        configurations = {
            row.get("configuration_fingerprint") for row in branch.values()
            if row.get("status") == "ok" or row.get("configuration_fingerprint")
        }
        if len(configurations) > 1:
            raise ValueError("A branch contains mixed inference/prompt configurations")
    pdf_ids = sorted(set(strict_rows) | set(core_rows))
    fused: list[dict[str, Any]] = []
    for pdf_id in pdf_ids:
        strict = strict_rows.get(pdf_id, {})
        core = core_rows.get(pdf_id, {})
        strict_rating = review_rating(strict)
        core_rating = review_rating(core)
        for row, rating in ((strict, strict_rating), (core, core_rating)):
            if row.get("status") != "ok":
                continue
            if rating is None:
                raise ValueError(f"Invalid successful branch score for {pdf_id}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("pdf_sha256") or "")):
                raise ValueError(
                    f"Missing or invalid PDF fingerprint for {pdf_id}; regenerate branch reviews"
                )
        if (strict.get("pdf_sha256") and core.get("pdf_sha256")
                and strict["pdf_sha256"] != core["pdf_sha256"]):
            raise ValueError(f"PDF content mismatch for {pdf_id}")
        missing_branches = [
            name for name, row in (("manuscript_strict", strict), ("science_core", core))
            if row.get("status") != "ok"
        ]
        if missing_branches:
            if require_complete:
                raise ValueError(f"Failed or missing branch score for {pdf_id}")
            source = strict or core
            provider, model, reasoning_effort = reviewer_identity(source)
            fused.append({
                "paper_id": source.get("paper_id"),
                "arxiv_id": source.get("arxiv_id"),
                "variant": source.get("variant"),
                "pdf_id": pdf_id,
                "provider": provider,
                "model": model,
                "reasoning_effort": reasoning_effort or None,
                "status": "missing",
                "missing_branches": missing_branches,
                "manuscript_strict_rating": strict_rating if strict.get("status") == "ok" else None,
                "science_core_rating": core_rating if core.get("status") == "ok" else None,
                "robust_review_rating": None,
                "manuscript_configuration": strict.get("configuration_fingerprint"),
                "science_core_configuration": core.get("configuration_fingerprint"),
                "configuration_fingerprint": None,
                "manuscript_weight": 0.5,
                "science_core_weight": 0.5,
            })
            continue
        strict_config = strict.get("run_configuration") or {}
        core_config = core.get("run_configuration") or {}
        for field in ("base_url", "pdf_engine"):
            if strict_config.get(field) != core_config.get(field):
                raise ValueError(f"Branch {field} mismatch for {pdf_id}")
        for field in ("paper_id", "variant"):
            if str(strict.get(field)) != str(core.get(field)):
                raise ValueError(f"{field} mismatch for {pdf_id}")
        if reviewer_identity(strict) != reviewer_identity(core):
            raise ValueError(
                f"Reviewer mismatch for {pdf_id}: manuscript Strict uses "
                f"{reviewer_identity(strict)}, science core uses {reviewer_identity(core)}"
            )
        provider, model, reasoning_effort = reviewer_identity(strict)
        fused.append(
            {
                "paper_id": strict.get("paper_id") or core.get("paper_id"),
                "arxiv_id": strict.get("arxiv_id"),
                "variant": strict.get("variant") or core.get("variant"),
                "pdf_id": pdf_id,
                "pdf_filename": strict.get("pdf_filename") or core.get("pdf_filename"),
                "provider": provider,
                "model": model,
                "reasoning_effort": reasoning_effort or None,
                "pdf_sha256": strict.get("pdf_sha256"),
                "manuscript_configuration": strict.get("configuration_fingerprint"),
                "science_core_configuration": core.get("configuration_fingerprint"),
                "configuration_fingerprint": (
                    str(strict.get("configuration_fingerprint") or "")
                    + ":"
                    + str(core.get("configuration_fingerprint") or "")
                ),
                "status": "ok",
                "manuscript_strict_rating": strict_rating,
                "science_core_rating": core_rating,
                "robust_review_rating": 0.5 * strict_rating + 0.5 * core_rating,
                "manuscript_weight": 0.5,
                "science_core_weight": 0.5,
            }
        )
    return fused


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    strict_rows = load_strict_reviews(args.strict_reviews)
    core_rows = load_science_core_reviews(args.science_core_dir)
    rows = fuse(strict_rows, core_rows, require_complete=args.require_complete)
    ok_count = sum(row["status"] == "ok" for row in rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "strict_review_count": len(strict_rows),
                "science_core_review_count": len(core_rows),
                "fused_review_count": ok_count,
                "missing_review_count": len(rows) - ok_count,
                "record_count": len(rows),
                "output": str(args.output),
            }
        )
    )
    return 0 if ok_count else 1


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
