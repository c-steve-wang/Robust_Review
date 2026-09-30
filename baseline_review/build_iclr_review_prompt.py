#!/usr/bin/env python3
"""Build and validate an ICLR-style review prompt without PDF/API review.

This script does not call the OpenAI API, upload PDFs, or inspect PDF files. It
only prints a reusable reviewer prompt and optionally validates a completed
review JSON object against the requested schema.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_TEMPLATE = """Please serve as an expert reviewer for a top-tier AI conference with an acceptance rate of about 30%.
Please evaluate the paper critically and assign scores according to the criteria below.

Review Form

1. Summary
Briefly summarize the paper and its contributions.
This is not the place to critique the paper; the authors should generally agree with a well-written summary.

2. Soundness, Presentation, Contribution
Use a 1-4 scale:
1 = poor
2 = fair
3 = good
4 = excellent

Soundness:
1 = The main claims are unsupported, technically flawed, or contradicted by the evidence.
2 = The work is plausible but has important technical gaps, missing justification, weak validation, or limitations that affect the main claims.
3 = The work is mostly technically sound, with only moderate or non-central concerns.
4 = The work is technically rigorous, well justified, and thoroughly validated.

Presentation:
1 = The paper is difficult to understand, poorly organized, or missing essential details.
2 = The paper is understandable but has clarity, organization, or completeness issues.
3 = The paper is clearly written overall, with only moderate presentation issues.
4 = The paper is very clear, well organized, and easy to follow.

Contribution:
1 = The contribution is minor, mostly incremental, already known, or of limited relevance.
2 = The contribution is somewhat useful but limited in novelty, significance, generality, or impact.
3 = The contribution is clear, meaningful, and relevant to the field.
4 = The contribution is strong, novel, and likely to have substantial impact.

3. Strengths
List the strong points of the paper.

4. Weaknesses
List the weak points of the paper.

5. Questions
List questions for the authors that would help clarify your understanding.

6. Flag For Ethics Review
If there are ethical issues, describe them.
Otherwise state: "No ethics review needed."

7. Rating
Please provide an overall score for this submission.
The rating must be one of the following values only: 1, 3, 5, 6, 8, or 10.

Rating scale:
1 = Strong Reject
A paper with fundamental problems such as well-known or trivial results, serious technical flaws, unsupported central claims, invalid evaluation, or unaddressed ethical concerns.

3 = Reject
A paper that is not competitive for a top-tier AI conference due to meaningful weaknesses in novelty, technical soundness, evaluation, reproducibility, clarity, significance, or positioning.
A paper can receive 3 even if it is understandable, technically plausible, or has some strengths, if the overall contribution or evidence is insufficient.

5 = Marginally below the acceptance threshold
A technically solid paper with some positive qualities, but where the reasons for a lower score slightly outweigh the reasons for a higher score.
Typical reasons include limited novelty, incomplete evaluation, weak or missing baselines, insufficient ablations, unclear significance, narrow scope, limited reproducibility, or claims that are stronger than the evidence.
Please use sparingly.

6 = Marginally above the acceptance threshold
A technically solid paper where the reasons for a higher score clearly outweigh the weaknesses.
A rating of 6 requires concrete positive evidence that the paper is competitive for a top-tier AI conference, such as a clear contribution, convincing evaluation, appropriate baselines, and sufficient support for the main claims.
Do not assign 6 merely because the paper is coherent, plausible, or has some positive results.
Please use sparingly.

8 = Accept
A strong paper with a clear and meaningful contribution, convincing technical quality, good-to-excellent evaluation, appropriate comparisons, sufficient reproducibility, and clear relevance to the field.
The paper should have high impact on at least one sub-area of AI or moderate-to-high impact on more than one area of AI.
Minor weaknesses are acceptable, but there should be no major unresolved issues in soundness, evaluation, novelty, or ethics.

10 = Strong Accept
An exceptional paper with groundbreaking impact on one or more areas of AI, technically excellent work, exceptionally strong evaluation, strong reproducibility and resources, and no unaddressed ethical considerations.
This rating should be reserved for rare submissions that are clearly among the best papers in the venue.

8. Confidence
Use a 1-5 scale:
1 = educated guess
2 = willing to defend but likely missed central parts
3 = fairly confident
4 = confident but not absolutely certain
5 = absolutely certain, checked details carefully

Output Format

You MUST output your review as a single valid JSON object with exactly the fields shown below.
Do NOT output any text outside the JSON object.
Do NOT use markdown fences, preamble, or commentary.
Use numeric values, not strings, for soundness, presentation, contribution, rating, and confidence.

{
  "summary": "<text>",
  "soundness": <num>,
  "presentation": <num>,
  "contribution": <num>,
  "strengths": ["<text>", "<text>"],
  "weaknesses": ["<text>", "<text>"],
  "questions": ["<text>"],
  "ethics_flag": "No ethics review needed.",
  "rating": <num>,
  "confidence": <num>
}"""


DEFAULT_TEMPLATE_NAME = "standard"
PROMPT_BANK_PATH = Path(__file__).with_name("review_prompt_bank.md")


SCHEMA_KEYS = [
    "summary",
    "soundness",
    "presentation",
    "contribution",
    "strengths",
    "weaknesses",
    "questions",
    "ethics_flag",
    "rating",
    "confidence",
]


def normalize_template_name(name: str) -> str:
    key = name.strip().lower().replace("_", "-")
    key = re.sub(r"\s+", "-", key)
    if key.endswith("-prompt"):
        key = key.removesuffix("-prompt")
    return key


def load_prompt_bank(path: Path = PROMPT_BANK_PATH) -> dict[str, str]:
    templates = {DEFAULT_TEMPLATE_NAME: DEFAULT_TEMPLATE}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return templates

    pattern = re.compile(
        r"^##\s+(.+?)\s*$\n\s*```text\n(.*?)\n```", re.MULTILINE | re.DOTALL
    )
    for match in pattern.finditer(text):
        name = normalize_template_name(match.group(1))
        body = match.group(2).strip()
        if name and body:
            templates[name] = body
    return templates


def available_prompt_templates() -> list[str]:
    return sorted(load_prompt_bank())


def get_review_prompt_template(template_name: str = DEFAULT_TEMPLATE_NAME) -> str:
    templates = load_prompt_bank()
    key = normalize_template_name(template_name)
    try:
        return templates[key]
    except KeyError as exc:
        available = ", ".join(sorted(templates))
        raise ValueError(
            f"Unknown review prompt template '{template_name}'. Available templates: {available}"
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE_NAME,
        choices=available_prompt_templates(),
        help="Review prompt template to print or use with --paper-text.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print the review prompt.",
    )
    parser.add_argument(
        "--paper-text",
        type=Path,
        help="Optional plain-text/Markdown paper content to append after the prompt.",
    )
    parser.add_argument(
        "--validate-json",
        type=Path,
        help="Validate a completed review JSON file. Use '-' to read stdin.",
    )
    return parser.parse_args()


def build_prompt(
    paper_text: str | None = None, template_name: str = DEFAULT_TEMPLATE_NAME
) -> str:
    parts = [get_review_prompt_template(template_name)]
    if paper_text:
        parts.append("Paper Content\n\n" + paper_text.strip())
    return "\n\n".join(parts).rstrip() + "\n"


def read_json_input(path: Path) -> Any:
    try:
        if str(path) == "-":
            return json.loads(sys.stdin.read())
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Review JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Review JSON is not valid JSON: {exc}") from exc


def require_int(
    value: Any, field: str, minimum: int, maximum: int, errors: list[str]
) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(f"{field} must be an integer JSON number.")
    elif not minimum <= value <= maximum:
        errors.append(f"{field} must be between {minimum} and {maximum}.")


def require_text_list(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{field} must be a non-empty list.")
        return
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field}[{index}] must be a non-empty string.")


def validate_review(review: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(review, dict):
        return ["Review must be a JSON object."]

    keys = list(review.keys())
    if keys != SCHEMA_KEYS:
        missing = [key for key in SCHEMA_KEYS if key not in review]
        extra = [key for key in keys if key not in SCHEMA_KEYS]
        if missing:
            errors.append("Missing fields: " + ", ".join(missing))
        if extra:
            errors.append("Unexpected fields: " + ", ".join(extra))

    if (
        not isinstance(review.get("summary"), str)
        or not review.get("summary", "").strip()
    ):
        errors.append("summary must be a non-empty string.")
    require_int(review.get("soundness"), "soundness", 1, 4, errors)
    require_int(review.get("presentation"), "presentation", 1, 4, errors)
    require_int(review.get("contribution"), "contribution", 1, 4, errors)
    require_text_list(review.get("strengths"), "strengths", errors)
    require_text_list(review.get("weaknesses"), "weaknesses", errors)
    require_text_list(review.get("questions"), "questions", errors)
    if (
        not isinstance(review.get("ethics_flag"), str)
        or not review.get("ethics_flag", "").strip()
    ):
        errors.append("ethics_flag must be a non-empty string.")
    if type(review.get("rating")) is not int or review["rating"] not in {
        1,
        3,
        5,
        6,
        8,
        10,
    }:
        errors.append("rating must be one of 1, 3, 5, 6, 8, 10.")
    require_int(review.get("confidence"), "confidence", 1, 5, errors)
    return errors


def main() -> int:
    args = parse_args()
    did_work = False

    if args.print or not args.validate_json:
        paper_text = None
        if args.paper_text:
            paper_text = args.paper_text.read_text(encoding="utf-8", errors="replace")
        sys.stdout.write(build_prompt(paper_text, args.template))
        did_work = True

    if args.validate_json:
        try:
            review = read_json_input(args.validate_json)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        errors = validate_review(review)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("OK: review JSON matches the expected schema.", file=sys.stderr)
        did_work = True

    return 0 if did_work else 2


if __name__ == "__main__":
    raise SystemExit(main())
