#!/usr/bin/env python3
"""Compute the seven RobustReview metrics from completed review outputs.

The input may be a baseline ``reviews.jsonl`` file, a SciCore fused JSONL
file, or a science-core output directory containing ``science_core.json``
reviews. The script reads scores only; it does not call a model or read PDFs.

For every included paper, ``original`` is the reference presentation and
``condition_01`` through ``condition_20`` are its matched rhetorical rewrites.
Missing and failed scores are rejected by default. Declare a subset with
--paper-id-file or --paper-id. Use --allow-incomplete for descriptive metrics
from observed pairs. ICC and discriminability use complete paper blocks only;
metrics without enough observations are null.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVIEW_DIR = REPO_ROOT / "baseline_review"
if str(BASELINE_REVIEW_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_REVIEW_DIR))

from review_pdf_scores_openai import latest_attempt_row  # noqa: E402

DEFAULT_METADATA = REPO_ROOT / "data" / "meta.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results" / "evaluation"
RATING_FIELDS = (
    "auto",
    "model_rating",
    "robust_review_rating",
    "review.rating",
    "rating",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "reviews",
        nargs="+",
        type=Path,
        help=(
            "Review JSONL/JSON files or directories. Directories are searched "
            "for reviews.jsonl and reviews/science_core.json files."
        ),
    )
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--provider", help="Keep rows from one API provider.")
    parser.add_argument("--model", help="Keep rows from one model ID.")
    parser.add_argument("--template", help="Keep rows from one prompt template.")
    parser.add_argument(
        "--rating-field",
        choices=RATING_FIELDS,
        default="auto",
        help=(
            "Score field to evaluate. auto prefers robust_review_rating, then "
            "model_rating, review.rating, and rating."
        ),
    )
    parser.add_argument(
        "--paper-id",
        action="append",
        type=int,
        default=[],
        help="Restrict evaluation to a paper ID; repeat for multiple papers.",
    )
    parser.add_argument(
        "--paper-id-file",
        type=Path,
        help="JSON array of expected paper IDs; cannot combine with --paper-id.",
    )
    parser.set_defaults(allow_incomplete=False)
    coverage = parser.add_mutually_exclusive_group()
    coverage.add_argument(
        "--allow-incomplete",
        action="store_true",
        help=(
            "Calculate descriptive metrics from available scores; ICC and "
            "discriminability continue to use complete 21-presentation blocks."
        ),
    )
    coverage.add_argument(
        "--require-complete",
        dest="allow_incomplete",
        action="store_false",
        help="Reject missing scores (default; paper-style evaluation).",
    )
    return parser.parse_args(argv)


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        converted = float(value)
    elif isinstance(value, str):
        try:
            converted = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return converted if math.isfinite(converted) else None


def load_metadata(path: Path) -> tuple[dict[int, dict[str, Any]], list[str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("papers"), list):
        raise ValueError(f"{path} must contain a papers array")
    if not isinstance(value.get("rewrite_conditions"), list):
        raise ValueError(f"{path} must contain a rewrite_conditions array")

    papers: dict[int, dict[str, Any]] = {}
    for row in value["papers"]:
        if not isinstance(row, dict):
            raise ValueError(f"{path} contains a non-object paper record")
        paper_id = row.get("paper_id")
        if type(paper_id) is not int or paper_id <= 0:
            raise ValueError("Metadata paper_id must be a positive integer")
        if paper_id in papers:
            raise ValueError(f"duplicate paper_id in {path}: {paper_id}")
        papers[paper_id] = row

    if any(
        not isinstance(row, dict) or not isinstance(row.get("condition_id"), str)
        for row in value["rewrite_conditions"]
    ):
        raise ValueError("Invalid rewrite_conditions metadata")
    variants = [row["condition_id"] for row in value["rewrite_conditions"]]
    if set(variants) != {f"condition_{i:02}" for i in range(1, 21)}:
        raise ValueError(
            "Benchmark metadata must define exactly condition_01 through condition_20"
        )
    if len(variants) != len(set(variants)):
        raise ValueError(f"duplicate condition_id in {path}")
    return papers, variants


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        value["__source_file"] = str(path)
        rows.append(value)
    return rows


def read_json(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise ValueError(f"{path} must contain a JSON object or an array of objects")


def discover_inputs(paths: Iterable[Path]) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for supplied in paths:
        path = supplied.expanduser().resolve()
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(path.rglob("reviews.jsonl"))
            candidates.extend(sorted(path.rglob("reviews/science_core.json")))
        else:
            raise FileNotFoundError(f"review input not found: {supplied}")
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                discovered.append(resolved)
    if not discovered:
        raise RuntimeError("no review JSON or JSONL files were found")
    return discovered


def read_review_rows(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[Path]]:
    rows: list[dict[str, Any]] = []
    inputs = discover_inputs(paths)
    for path in inputs:
        if path.suffix.lower() == ".jsonl":
            rows.extend(read_jsonl(path))
        elif path.suffix.lower() == ".json":
            rows.extend({**row, "__source_file": str(path)} for row in read_json(path))
        else:
            raise ValueError(f"unsupported review file type: {path}")
    return rows, inputs


def paper_id_from_row(row: dict[str, Any]) -> int | None:
    value = row.get("paper_id")
    if value is None:
        pdf_id = str(row.get("pdf_id") or "")
        value = pdf_id.split("/", 1)[0] if "/" in pdf_id else None
    if value is None or isinstance(value, bool) or isinstance(value, float):
        return None
    try:
        paper_id = int(value)
    except (TypeError, ValueError):
        return None
    return paper_id if paper_id > 0 else None


def variant_from_row(row: dict[str, Any]) -> str | None:
    value = row.get("variant")
    if value is None:
        pdf_id = str(row.get("pdf_id") or "")
        value = pdf_id.split("/", 1)[1] if "/" in pdf_id else None
    return str(value) if value is not None else None


def rating_from_row(row: dict[str, Any], requested: str) -> tuple[float | None, str]:
    nested_review = row.get("review")
    nested_rating = (
        nested_review.get("rating") if isinstance(nested_review, dict) else None
    )
    values = {
        "robust_review_rating": row.get("robust_review_rating"),
        "model_rating": row.get("model_rating"),
        "review.rating": nested_rating,
        "rating": row.get("rating"),
    }
    if requested != "auto":
        return finite_number(values[requested]), requested

    # Select by schema presence, not by whether a particular row succeeded.
    # Failed baseline/science-core records still belong to the same configuration
    # as successful records even though their score is absent.
    if "robust_review_rating" in row:
        source = "robust_review_rating"
    elif "model_rating" in row:
        source = "model_rating"
    elif isinstance(nested_review, dict) and "rating" in nested_review:
        source = "review.rating"
    elif "rating" in row:
        source = "rating"
    elif (
        "scientific_content_path" in row or row.get("prompt_template") == "science_core"
    ):
        source = "review.rating"
    else:
        source = "model_rating"
    return finite_number(values[source]), source


def row_matches(row: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.provider is not None and str(row.get("provider") or "") != args.provider:
        return False
    if args.model is not None and str(row.get("model") or "") != args.model:
        return False
    if (
        args.template is not None
        and str(row.get("prompt_template") or "") != args.template
    ):
        return False
    return True


def configuration_identity(row: dict[str, Any], rating_source: str) -> tuple[str, ...]:
    template = str(row.get("prompt_template") or "")
    if rating_source == "robust_review_rating":
        template = "fused"
    return (
        str(row.get("provider") or ""),
        str(row.get("model") or ""),
        template,
        str(row.get("reasoning_effort") or ""),
        rating_source,
        str(row.get("configuration_fingerprint") or ""),
    )


def collect_scores(
    rows: list[dict[str, Any]],
    variants: list[str],
    args: argparse.Namespace,
) -> tuple[dict[tuple[int, str], float | None], tuple[str, ...]]:
    allowed_variants = {"original", *variants}
    latest: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        if not row_matches(row, args):
            continue
        paper_id = paper_id_from_row(row)
        variant = variant_from_row(row)
        if paper_id is None or variant not in allowed_variants:
            raise ValueError("Review row has an invalid paper_id or benchmark variant")
        if row.get("pdf_id") and row["pdf_id"] != f"{paper_id}/{variant}":
            raise ValueError("Review row pdf_id disagrees with paper_id/variant")
        key = (paper_id, variant)
        previous = latest.get(key)
        if previous is not None and previous.get("__source_file") != row.get(
            "__source_file"
        ):
            raise ValueError(f"Duplicate paper/variant in multiple input files: {key}")
        latest[key] = latest_attempt_row(previous, row)

    if not latest:
        raise RuntimeError("no review rows matched the requested filters")

    scores: dict[tuple[int, str], float | None] = {}
    identities: set[tuple[str, ...]] = set()
    fingerprints: set[str] = set()
    for key, row in latest.items():
        rating, source = rating_from_row(row, args.rating_field)
        identity = configuration_identity(row, source)
        failed = row.get("status") not in {None, "ok"}
        identities.add(identity[:-1])
        # Older failed attempts omitted this field. They contribute no score,
        # so an unknown fingerprint must not conflict with the scored panel.
        # Still check every row's provider/model/prompt/reasoning, and reject
        # any known fingerprint conflict, including one on a failed attempt.
        if not failed or identity[-1]:
            fingerprints.add(identity[-1])
        if failed:
            rating = None
        elif rating is None or not 1 <= rating <= 10:
            raise ValueError(f"Invalid or missing successful OA score for {key}")
        scores[key] = rating
    if len(identities) != 1 or len(fingerprints) > 1:
        raise ValueError(
            "Review panel contains mixed configurations; use one provider/model/"
            "prompt/reasoning/settings per output directory or filter the input."
        )
    return scores, (*next(iter(identities)), next(iter(fingerprints), ""))


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean requires at least one value")
    return statistics.fmean(values)


def population_variance(values: list[float]) -> float:
    center = mean(values)
    return mean([(value - center) ** 2 for value in values])


def average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = average_rank
        start = end
    return ranks


def pearson(first: list[float], second: list[float]) -> float | None:
    if len(first) != len(second):
        raise ValueError("Correlation inputs must have equal lengths")
    if len(first) < 2:
        return None
    first_mean = mean(first)
    second_mean = mean(second)
    first_centered = [value - first_mean for value in first]
    second_centered = [value - second_mean for value in second]
    denominator = math.sqrt(
        sum(value * value for value in first_centered)
        * sum(value * value for value in second_centered)
    )
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(first_centered, second_centered)) / denominator


def spearman(first: list[float], second: list[float]) -> float | None:
    return pearson(average_ranks(first), average_ranks(second))


def icc_a1(values: list[list[float]]) -> float | None:
    """Two-way mixed-effects, absolute-agreement, single-measure ICC(A,1).

    Return None when the ICC denominator is zero, as specified in the paper.
    """

    paper_count = len(values)
    presentation_count = len(values[0]) if values else 0
    if paper_count < 2 or presentation_count < 2:
        return None
    if any(len(row) != presentation_count for row in values):
        raise ValueError("ICC matrix is ragged")

    grand = mean([value for row in values for value in row])
    paper_means = [mean(row) for row in values]
    presentation_means = [
        mean([row[column] for row in values]) for column in range(presentation_count)
    ]
    ms_paper = (
        presentation_count
        * sum((value - grand) ** 2 for value in paper_means)
        / (paper_count - 1)
    )
    ms_presentation = (
        paper_count
        * sum((value - grand) ** 2 for value in presentation_means)
        / (presentation_count - 1)
    )
    residual_sum = 0.0
    for paper_index, row in enumerate(values):
        for column, value in enumerate(row):
            residual = (
                value - paper_means[paper_index] - presentation_means[column] + grand
            )
            residual_sum += residual * residual
    ms_error = residual_sum / ((paper_count - 1) * (presentation_count - 1))
    denominator = (
        ms_paper
        + (presentation_count - 1) * ms_error
        + presentation_count * (ms_presentation - ms_error) / paper_count
    )
    if denominator == 0:
        return None
    return (ms_paper - ms_error) / denominator


def exact_discriminability(values: list[list[float]]) -> float | None:
    """Probability that a within-paper distance is smaller than a between-paper distance."""

    paper_count = len(values)
    presentation_count = len(values[0]) if values else 0
    if paper_count < 2 or presentation_count < 2:
        return None
    numerator = 0.0
    denominator = 0
    for paper_index, row in enumerate(values):
        other_scores = [
            score
            for other_index, other_row in enumerate(values)
            if other_index != paper_index
            for score in other_row
        ]
        for presentation_index, anchor in enumerate(row):
            within = [
                round(abs(anchor - score), 12)
                for index, score in enumerate(row)
                if index != presentation_index
            ]
            between = sorted(round(abs(anchor - score), 12) for score in other_scores)
            for distance in within:
                left = bisect.bisect_left(between, distance)
                right = bisect.bisect_right(between, distance)
                numerator += len(between) - right
                numerator += 0.5 * (right - left)
                denominator += len(between)
    return numerator / denominator if denominator else None


def human_score(row: dict[str, Any]) -> float | None:
    aggregate = finite_number(row.get("average_overall_assessment"))
    if aggregate is not None:
        return aggregate
    reviews = row.get("reviews")
    if not isinstance(reviews, list):
        return None
    values = [
        score
        for review in reviews
        if isinstance(review, dict)
        for score in [finite_number(review.get("overall_assessment"))]
        if score is not None
    ]
    return mean(values) if values else None


def evaluate(
    scores: dict[tuple[int, str], float | None],
    papers: dict[int, dict[str, Any]],
    variants: list[str],
    requested_papers: list[int],
    allow_incomplete: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    observed_papers = {paper_id for paper_id, _variant in scores}
    if requested_papers:
        selected = sorted(set(requested_papers))
    else:
        selected = sorted(papers)
    if not selected:
        raise RuntimeError("no papers were selected")
    unknown = [
        paper_id
        for paper_id in set(selected) | observed_papers
        if paper_id not in papers
    ]
    if unknown:
        raise ValueError(f"paper IDs are absent from metadata: {unknown}")

    missing: list[str] = []
    paper_rows: list[dict[str, Any]] = []
    complete_matrices: list[list[float]] = []
    complete_ids: list[int] = []
    for paper_id in selected:
        row: dict[str, Any] = {
            "paper_id": paper_id,
            "arxiv_id": papers[paper_id].get("arxiv_id"),
            "human_overall_assessment": human_score(papers[paper_id]),
        }
        presentation_scores: list[float] = []
        complete = True
        for variant in ["original", *variants]:
            value = scores.get((paper_id, variant))
            row[variant] = value
            if value is None:
                complete = False
                missing.append(f"{paper_id}/{variant}")
            else:
                presentation_scores.append(value)
        row["complete"] = complete
        paper_rows.append(row)
        if complete:
            complete_ids.append(paper_id)
            complete_matrices.append(presentation_scores)

    if missing and not allow_incomplete:
        preview = ", ".join(missing[:20])
        suffix = "" if len(missing) <= 20 else f", ... ({len(missing)} missing cells)"
        raise RuntimeError(
            "incomplete review panel; every included paper requires original plus all "
            f"rewrite scores. Missing: {preview}{suffix}"
        )

    all_deltas: list[float] = []
    paired_originals: dict[int, float] = {}
    for variant in variants:
        for paper_id in selected:
            baseline = scores.get((paper_id, "original"))
            rewrite = scores.get((paper_id, variant))
            if baseline is None or rewrite is None:
                continue
            paired_originals[paper_id] = baseline
            all_deltas.append(rewrite - baseline)
    paired_count = len(all_deltas)

    human_original: list[float] = []
    human_reference: list[float] = []
    for paper_id in selected:
        original = scores.get((paper_id, "original"))
        human = human_score(papers[paper_id])
        if original is not None and human is not None:
            human_original.append(original)
            human_reference.append(human)

    spr = None
    if all_deltas:
        # Count each original paper once in the signal, even when different
        # numbers of its rewrite scores are available.
        signal = population_variance(list(paired_originals.values()))
        perturbation_mse = mean([delta * delta for delta in all_deltas])
        spr_denominator = signal + perturbation_mse
        spr = 0.0 if spr_denominator == 0 else signal / spr_denominator
    expected_pairs = len(selected) * len(variants)
    human_spearman = spearman(human_original, human_reference)
    human_spearman_undefined_reason = None
    if len(human_original) < 2:
        human_spearman_undefined_reason = "fewer_than_two_paired_originals"
    elif len(set(human_original)) == 1 and len(set(human_reference)) == 1:
        human_spearman_undefined_reason = "constant_model_and_human_scores"
    elif len(set(human_original)) == 1:
        human_spearman_undefined_reason = "constant_model_scores"
    elif len(set(human_reference)) == 1:
        human_spearman_undefined_reason = "constant_human_scores"
    metrics: dict[str, Any] = {
        "mad": mean([abs(delta) for delta in all_deltas]) if all_deltas else None,
        "drift_sd": math.sqrt(population_variance(all_deltas)) if all_deltas else None,
        "icc_a1": icc_a1(complete_matrices),
        "spr": spr,
        "discriminability": exact_discriminability(complete_matrices),
        "human_mae": (
            mean(
                [
                    abs(model - human)
                    for model, human in zip(human_original, human_reference)
                ]
            )
            if human_original
            else None
        ),
        "human_spearman": human_spearman,
        "human_spearman_undefined_reason": human_spearman_undefined_reason,
        "paper_count": len(selected),
        "complete_paper_blocks": len(complete_ids),
        "presentation_count": 1 + len(variants),
        "paired_score_count": paired_count,
        "paired_paper_count": len(paired_originals),
        "expected_pair_count": expected_pairs,
        "missing_pair_count": expected_pairs - paired_count,
        "missing_score_count": len(missing),
        "missing_paper_ids": sorted(set(selected) - observed_papers),
        "human_comparison_count": len(human_original),
    }
    return metrics, paper_rows


def write_outputs(
    output_dir: Path,
    result: dict[str, Any],
    paper_rows: list[dict[str, Any]],
    variants: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metric_row = {**result["configuration"], **result["metrics"]}
    with (output_dir / "metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metric_row))
        writer.writeheader()
        writer.writerow(metric_row)

    fields = [
        "paper_id",
        "arxiv_id",
        "human_overall_assessment",
        "original",
        *variants,
        "complete",
    ]
    with (output_dir / "paper_scores.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in paper_rows:
            writer.writerow({field: row.get(field) for field in fields})


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    papers, variants = load_metadata(args.metadata.expanduser().resolve())
    if args.paper_id_file:
        if args.paper_id:
            raise ValueError("Use only one of --paper-id-file and --paper-id")
        ids = json.loads(args.paper_id_file.read_text(encoding="utf-8"))
        if (
            not isinstance(ids, list)
            or not ids
            or any(type(i) is not int or i <= 0 for i in ids)
        ):
            raise ValueError(
                "--paper-id-file must contain a nonempty JSON array of positive integers"
            )
        args.paper_id = ids
    rows, input_paths = read_review_rows(args.reviews)
    scores, identity = collect_scores(rows, variants, args)
    metrics, paper_rows = evaluate(
        scores,
        papers,
        variants,
        args.paper_id,
        args.allow_incomplete,
    )
    configuration = {
        "provider": identity[0] or None,
        "model": identity[1] or None,
        "prompt_template": identity[2] or None,
        "reasoning_effort": identity[3] or None,
        "rating_source": identity[4],
        "configuration_fingerprint": identity[5] or None,
    }
    result = {
        "schema_version": 1,
        "drift_sd_definition": "population SD over all available signed original/rewrite differences (ddof=0)",
        "expected_paper_ids": sorted(set(args.paper_id) if args.paper_id else papers),
        "configuration": configuration,
        "metrics": metrics,
        "input_files": [str(path) for path in input_paths],
        "metadata": str(args.metadata.expanduser().resolve()),
        "missing_policy": (
            "observed pairs for MAD, Drift SD, and rewrite MSE; SPR signal uses unique paired originals; ICC and discriminability use complete blocks"
            if args.allow_incomplete
            else "complete 21-presentation blocks required"
        ),
    }
    output_dir = args.output_dir.expanduser().resolve()
    write_outputs(output_dir, result, paper_rows, variants)
    print(json.dumps({"output_dir": str(output_dir), **metrics}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
