#!/usr/bin/env python3
"""Run the science-core branch of SciCore with OpenAI or OpenRouter.

The scientific-content record is saved as an intermediate result. All model
calls use the selected provider API.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import tempfile
import os
import re
import sys
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVIEW_DIR = REPO_ROOT / "baseline_review"
if str(BASELINE_REVIEW_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_REVIEW_DIR))

import review_pdf_scores_openai as provider_api  # type: ignore[import-not-found]  # noqa: E402
from build_iclr_review_prompt import (  # type: ignore[import-not-found]  # noqa: E402
    validate_review,
)


PROMPT_PATH = Path(__file__).with_name("scientific_content_prompt.md")
SCICORE_REVIEW_PROMPT_PATH = Path(__file__).with_name(
    "scientific_core_review_prompt.md"
)
DEFAULT_PDF_DIR = REPO_ROOT / "papers"
DEFAULT_PDF_GLOB = "*/original.pdf"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "results" / "scicore_branch"
DEFAULT_MODELS = {
    "openai": "gpt-5.5",
    "openrouter": "anthropic/claude-sonnet-5",
}
T = TypeVar("T")


@dataclass(frozen=True)
class ModelText:
    text: str
    response_id: str | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="*", type=Path, help="Specific PDF files.")
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        help=f"Directory scanned when no positional PDFs are supplied (default: {DEFAULT_PDF_DIR}).",
    )
    parser.add_argument("--pdf-glob", default=DEFAULT_PDF_GLOB)
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum PDFs to process; 0 means all matching PDFs (default: 1).",
    )
    parser.add_argument(
        "--provider",
        choices=sorted(provider_api.PROVIDERS),
        default="openai",
        help="API provider used for the complete workflow (default: openai).",
    )
    parser.add_argument("--base-url", help="Override the provider API base URL.")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument(
        "--model",
        help="One model used for both PDF extraction and content review.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Output root (default: {DEFAULT_OUTPUT_ROOT}).",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high"),
        help="Applied to extraction and review; omitted preserves provider defaults.",
    )
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument(
        "--extract-max-output-tokens",
        type=int,
        help="Optional override; omitted uses provider defaults.",
    )
    parser.add_argument(
        "--review-max-output-tokens",
        type=int,
        help="Optional override; omitted uses provider defaults.",
    )
    parser.add_argument(
        "--openrouter-pdf-engine",
        choices=provider_api.OPENROUTER_PDF_ENGINES,
        default="auto",
    )
    parser.add_argument("--openrouter-http-referer")
    parser.add_argument("--openrouter-app-title")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate the intermediate scientific content and all requested reviews.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the resolved plan without reading a key or calling an API.",
    )
    return parser.parse_args(argv)


def safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "unnamed"


def resolve_base_url(provider: str, override: str | None) -> str:
    config = provider_api.PROVIDERS[provider]
    candidate = override or os.environ.get(config.base_url_env)
    return provider_api.normalized_base_url(candidate or config.base_url)


def select_pdfs(
    positional: list[Path], pdf_dir: Path | None, pdf_glob: str, limit: int
) -> list[Path]:
    if limit < 0:
        raise ValueError("--limit cannot be negative.")
    if positional:
        candidates = positional
    else:
        directory = pdf_dir or DEFAULT_PDF_DIR
        if not directory.is_dir():
            raise FileNotFoundError(f"PDF directory not found: {directory}")
        candidates = sorted(directory.glob(pdf_glob))

    selected: list[Path] = []
    seen: set[Path] = set()
    seen_ids: set[str] = set()
    for path in candidates:
        if path.name.startswith("._"):
            continue
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        if not resolved.is_file():
            raise FileNotFoundError(f"PDF not found: {path}")
        if resolved.suffix.lower() != ".pdf":
            raise ValueError(f"Input is not a PDF: {path}")
        provider_api.paper_id_from_pdf(resolved)
        provider_api.variant_from_pdf(resolved)
        pdf_id = provider_api.pdf_identity(resolved)
        if pdf_id in seen_ids:
            raise ValueError(f"Different files share the same PDF identity: {pdf_id}")
        seen_ids.add(pdf_id)
        seen.add(resolved)
        selected.append(resolved)
    selected.sort(
        key=lambda path: (
            int(provider_api.paper_id_from_pdf(path)),
            provider_api.variant_from_pdf(path),
        )
    )
    if limit:
        selected = selected[:limit]
    if not selected:
        raise RuntimeError("No PDF files selected.")
    return selected


def load_extraction_prompt() -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not prompt:
        raise RuntimeError(f"Scientific-content prompt is empty: {PROMPT_PATH}")
    return prompt


def get_robust_review_prompt(template_name: str = "science_core") -> str:
    if template_name != "science_core":
        raise ValueError(
            "The released SciCore branch uses the science-core review prompt."
        )
    prompt = SCICORE_REVIEW_PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not prompt:
        raise RuntimeError(
            f"SciCore review prompt is empty: {SCICORE_REVIEW_PROMPT_PATH}"
        )
    return prompt


def prompt_variant(template_name: str) -> str:
    return "scientific-content-only"


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def build_run_configuration(
    *,
    provider: str,
    model: str,
    base_url: str,
    reasoning_effort: str | None,
    extraction_prompt: str,
    extract_max_output_tokens: int | None,
    review_max_output_tokens: int | None,
    openrouter_pdf_engine: str,
    template_name: str = "science_core",
) -> dict[str, Any]:
    """Identify the review settings independently of any PDF or API outcome."""
    return {
        "protocol_version": 1,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "reasoning_effort": reasoning_effort,
        "pdf_engine": openrouter_pdf_engine if provider == "openrouter" else None,
        "extract_max_output_tokens": extract_max_output_tokens,
        "extraction_prompt_sha256": prompt_sha256(extraction_prompt),
        "review_max_output_tokens": review_max_output_tokens,
        "review_template_sha256": prompt_sha256(get_robust_review_prompt(template_name)),
        "prompt_template": template_name,
    }


def pdf_payload(
    path: Path,
    provider: str,
    model: str,
    prompt: str,
    file_id: str | None,
    pdf_engine: str,
    max_output_tokens: int | None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    if provider == "openai":
        if not file_id:
            raise ValueError("OpenAI PDF payload requires a file id.")
        return {
            "model": model,
            **({"reasoning": {"effort": reasoning_effort}} if reasoning_effort else {}),
            **(
                {"max_output_tokens": max_output_tokens}
                if max_output_tokens is not None
                else {}
            ),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_file", "file_id": file_id},
                    ],
                }
            ],
        }
    if provider == "openrouter":
        encoded_pdf = base64.b64encode(path.read_bytes()).decode("ascii")
        payload: dict[str, Any] = {
            "model": model,
            **(
                {"max_tokens": max_output_tokens}
                if max_output_tokens is not None
                else {}
            ),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "file",
                            "file": {
                                "filename": "paper.pdf",
                                "file_data": f"data:application/pdf;base64,{encoded_pdf}",
                            },
                        },
                    ],
                }
            ],
        }
        if pdf_engine != "auto":
            payload["plugins"] = [{"id": "file-parser", "pdf": {"engine": pdf_engine}}]
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        return payload
    raise ValueError(f"Unsupported provider: {provider}")


def text_payload(
    provider: str,
    model: str,
    prompt: str,
    max_output_tokens: int | None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    if provider == "openai":
        return {
            "model": model,
            **({"reasoning": {"effort": reasoning_effort}} if reasoning_effort else {}),
            **(
                {"max_output_tokens": max_output_tokens}
                if max_output_tokens is not None
                else {}
            ),
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
        }
    if provider != "openrouter":
        raise ValueError(f"Unsupported provider: {provider}")
    payload = {
        "model": model,
        **({"max_tokens": max_output_tokens} if max_output_tokens is not None else {}),
        "messages": [{"role": "user", "content": prompt}],
    }
    if provider == "openrouter" and reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    return payload


def response_text(provider: str, response: Any) -> ModelText:
    if provider not in provider_api.PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    if not isinstance(response, dict):
        raise RuntimeError(f"{provider} response is not a JSON object.")
    if provider == "openai":
        checked = provider_api.require_openai_response(response)
        text = provider_api.extract_output_text(checked).strip()
    else:
        checked = provider_api.require_chat_response(response)
        text = provider_api.extract_chat_output_text(checked).strip()
    if not text:
        raise RuntimeError(f"{provider} returned an empty text response.")
    response_id = response.get("id")
    return ModelText(text=text, response_id=str(response_id) if response_id else None)


def call_pdf_model(
    path: Path,
    *,
    provider: str,
    model: str,
    prompt: str,
    api_key_value: str,
    base_url: str,
    max_output_tokens: int | None,
    openrouter_pdf_engine: str,
    openrouter_http_referer: str | None,
    openrouter_app_title: str | None,
    reasoning_effort: str | None = None,
) -> ModelText:
    if provider not in provider_api.PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    if provider == "openrouter":
        payload = pdf_payload(
            path,
            provider,
            model,
            prompt,
            None,
            openrouter_pdf_engine,
            max_output_tokens,
            reasoning_effort,
        )
        response = provider_api.request_json(
            "POST",
            f"{base_url}/chat/completions",
            api_key_value,
            payload,
            extra_headers=provider_api.openrouter_headers(
                openrouter_http_referer,
                openrouter_app_title,
            ),
        )
        return response_text(provider, response)

    file_id = provider_api.upload_file(
        path, api_key_value, base_url, purpose="user_data"
    )
    try:
        payload = pdf_payload(
            path,
            provider,
            model,
            prompt,
            file_id,
            openrouter_pdf_engine,
            max_output_tokens,
            reasoning_effort,
        )
        response = provider_api.request_json(
            "POST",
            f"{base_url}/responses",
            api_key_value,
            payload,
        )
        return response_text(provider, response)
    finally:
        provider_api.delete_file(file_id, api_key_value, base_url)


def call_text_model(
    *,
    provider: str,
    model: str,
    prompt: str,
    api_key_value: str,
    base_url: str,
    max_output_tokens: int | None,
    openrouter_http_referer: str | None,
    openrouter_app_title: str | None,
    reasoning_effort: str | None = None,
) -> ModelText:
    endpoint = "responses" if provider == "openai" else "chat/completions"
    kwargs: dict[str, Any] = {}
    if provider == "openrouter":
        kwargs["extra_headers"] = provider_api.openrouter_headers(
            openrouter_http_referer,
            openrouter_app_title,
        )
    response = provider_api.request_json(
        "POST",
        f"{base_url}/{endpoint}",
        api_key_value,
        text_payload(provider, model, prompt, max_output_tokens, reasoning_effort),
        **kwargs,
    )
    return response_text(provider, response)


def retry_text_call(
    call: Callable[[], T], max_retries: int, api_key_value: str = ""
) -> T:
    last_error = ""
    for attempt in range(1, max_retries + 1):
        http_error: urllib.error.HTTPError | None = None
        try:
            return call()
        except urllib.error.HTTPError as exc:
            last_error = provider_api.safe_error(exc, api_key_value)
            scope = provider_api.http_error_scope(exc)
            if scope == "fatal":
                raise provider_api.FatalAPIError(last_error) from exc
            if scope == "document":
                raise provider_api.DocumentAPIError(last_error) from exc
            http_error = exc
        except provider_api.FatalAPIError:
            raise
        except Exception as exc:
            last_error = provider_api.safe_error(exc, api_key_value)
        if attempt < max_retries:
            time.sleep(provider_api.retry_delay(attempt, http_error))
        elif http_error is not None and http_error.code == 429:
            raise provider_api.FatalAPIError(
                f"HTTP 429: rate limit persisted after {max_retries} attempts"
            ) from http_error
    raise RuntimeError(last_error or "model call failed without an error message")


def build_review_input(template_name: str, scientific_content: str) -> str:
    template = get_robust_review_prompt(template_name).rstrip()
    return (
        f"{template}\n\n"
        "Scientific Core\n\n"
        "The following is the complete scientific-content record available for "
        "this review. It is a structured scientific core, not the full paper "
        "text. Review only this record and do not infer outside evidence.\n\n"
        f"{scientific_content.strip()}\n"
    )


def extractor_directory(
    output_root: Path, path: Path, provider: str, model: str
) -> Path:
    extractor = f"{safe_component(provider)}__{safe_component(model)}"
    document = safe_component(provider_api.pdf_identity(path).replace("/", "__"))
    return output_root / document / extractor


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def matching_successful_review(
    path: Path,
    pdf_hash: str,
    configuration_fingerprint: str,
) -> bool:
    """Keep the last completed score while retrying the same input and settings."""
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(previous, dict)
        and previous.get("status") == "ok"
        and previous.get("pdf_sha256") == pdf_hash
        and previous.get("configuration_fingerprint") == configuration_fingerprint
    )


def preserve_review_content_before_replace(
    content_path: Path,
    paper_dir: Path,
    templates: list[str],
    pdf_hash: str,
    run_configurations: dict[str, dict[str, Any]],
) -> None:
    """Keep the exact core referenced by a successful review during reruns."""
    if not content_path.is_file():
        return
    snapshot_path: Path | None = None
    for template_name in templates:
        review_path = paper_dir / "reviews" / f"{safe_component(template_name)}.json"
        configuration_fingerprint = provider_api.fingerprint(
            run_configurations[template_name]
        )
        if not matching_successful_review(
            review_path, pdf_hash, configuration_fingerprint
        ):
            continue
        previous = json.loads(review_path.read_text(encoding="utf-8"))
        if previous.get("scientific_content_path") != str(content_path):
            continue
        if snapshot_path is None:
            original = content_path.read_bytes()
            digest = hashlib.sha256(original).hexdigest()
            snapshot_path = content_path.with_name(f"scientific_content.{digest}.md")
            if (
                not snapshot_path.is_file()
                or provider_api.pdf_sha256(snapshot_path) != digest
            ):
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        dir=paper_dir,
                        prefix="scientific_content.",
                        delete=False,
                    ) as handle:
                        temporary = Path(handle.name)
                        handle.write(original)
                    temporary.replace(snapshot_path)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        previous["scientific_content_path"] = str(snapshot_path)
        write_json(review_path, previous)


CORE_HEADINGS = [
    "Problem and setting",
    "Method and assumptions",
    "Experiments and reported results",
    "Reproducibility information",
    "Author-stated limitations",
]


def validate_scientific_content(content: str) -> None:
    headings = list(re.finditer(r"^## (.+)$", content, re.MULTILINE))
    if [item.group(1).strip() for item in headings] != CORE_HEADINGS:
        raise ValueError(
            "Scientific core must contain exactly the five required sections"
        )
    if content[: headings[0].start()].strip():
        raise ValueError("Scientific core must start with its first required section")
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        if not content[heading.end() : end].strip():
            raise ValueError(
                f"Scientific core section is empty: {CORE_HEADINGS[index]}"
            )


def call_after_hook(
    hook: Callable[[], None] | None, call: Callable[[], ModelText]
) -> ModelText:
    """Run an optional request-start hook immediately before an API call."""
    if hook is not None:
        hook()
    return call()


def process_pdf(
    path: Path,
    *,
    provider: str,
    model: str,
    templates: list[str],
    output_root: Path,
    api_key_value: str,
    base_url: str,
    extraction_prompt: str,
    max_retries: int,
    extract_max_output_tokens: int | None,
    review_max_output_tokens: int | None,
    openrouter_pdf_engine: str,
    openrouter_http_referer: str | None,
    openrouter_app_title: str | None,
    force: bool,
    before_call: Callable[[], None] | None = None,
    reasoning_effort: str | None = None,
) -> tuple[int, int]:
    paper_dir = extractor_directory(output_root, path, provider, model)
    paper_id = int(provider_api.paper_id_from_pdf(path))
    variant = provider_api.variant_from_pdf(path)
    pdf_id = provider_api.pdf_identity(path)
    content_path = paper_dir / "scientific_content.md"
    content_meta_path = paper_dir / "scientific_content.meta.json"
    extraction_prompt_hash = prompt_sha256(extraction_prompt)
    pdf_hash = provider_api.pdf_sha256(path)
    extraction_configuration = {
        "protocol_version": 1,
        "pdf_sha256": pdf_hash,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "reasoning_effort": reasoning_effort,
        "pdf_engine": openrouter_pdf_engine if provider == "openrouter" else None,
        "max_output_tokens": extract_max_output_tokens,
        "prompt_sha256": extraction_prompt_hash,
    }
    extraction_fingerprint = provider_api.fingerprint(extraction_configuration)
    run_configurations = {
        template_name: build_run_configuration(
            provider=provider,
            model=model,
            base_url=base_url,
            reasoning_effort=reasoning_effort,
            extraction_prompt=extraction_prompt,
            extract_max_output_tokens=extract_max_output_tokens,
            review_max_output_tokens=review_max_output_tokens,
            openrouter_pdf_engine=openrouter_pdf_engine,
            template_name=template_name,
        )
        for template_name in templates
    }

    try:
        content_meta = json.loads(content_meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        content_meta = {}
    if not isinstance(content_meta, dict):
        content_meta = {}
    reusable_content = (
        content_path.is_file()
        and content_path.stat().st_size > 0
        and content_meta.get("cache_fingerprint") == extraction_fingerprint
        and content_meta.get("content_sha256") == provider_api.pdf_sha256(content_path)
    )
    if reusable_content and not force:
        scientific_content = content_path.read_text(encoding="utf-8", errors="replace")
        validate_scientific_content(scientific_content)
        print(f"  reuse intermediate: {content_path}", flush=True)
    else:
        # Keep a completed result for this input and configuration until the
        # replacement finishes. Changed inputs must invalidate stale scores.
        preserve_review_content_before_replace(
            content_path, paper_dir, templates, pdf_hash, run_configurations
        )
        content_meta_path.unlink(missing_ok=True)
        for template_name in templates:
            review_path = paper_dir / "reviews" / f"{safe_component(template_name)}.json"
            configuration_fingerprint = provider_api.fingerprint(
                run_configurations[template_name]
            )
            if not matching_successful_review(
                review_path, pdf_hash, configuration_fingerprint
            ):
                write_json(
                    review_path,
                    {
                        "status": "failed",
                        "error": "Extraction/review not completed",
                        "paper_id": paper_id,
                        "variant": variant,
                        "pdf_id": pdf_id,
                        "provider": provider,
                        "model": model,
                        "reasoning_effort": reasoning_effort,
                        "prompt_template": template_name,
                        "pdf_sha256": pdf_hash,
                        "run_configuration": run_configurations[template_name],
                        "configuration_fingerprint": configuration_fingerprint,
                    },
                )
        print("  read PDF and save scientific-content intermediate", flush=True)

        def extract_and_validate() -> ModelText:
            candidate = call_after_hook(
                before_call,
                lambda: call_pdf_model(
                    path,
                    provider=provider,
                    model=model,
                    prompt=extraction_prompt,
                    api_key_value=api_key_value,
                    base_url=base_url,
                    max_output_tokens=extract_max_output_tokens,
                    openrouter_pdf_engine=openrouter_pdf_engine,
                    openrouter_http_referer=openrouter_http_referer,
                    openrouter_app_title=openrouter_app_title,
                    reasoning_effort=reasoning_effort,
                ),
            )
            validate_scientific_content(candidate.text)
            return candidate

        extracted = retry_text_call(extract_and_validate, max_retries, api_key_value)
        paper_dir.mkdir(parents=True, exist_ok=True)
        content_path.write_text(extracted.text.rstrip() + "\n", encoding="utf-8")
        write_json(
            content_meta_path,
            {
                "schema_version": 1,
                "paper_id": paper_id,
                "variant": variant,
                "pdf_id": pdf_id,
                "pdf_filename": path.name,
                "provider": provider,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "pdf_engine": openrouter_pdf_engine
                if provider == "openrouter"
                else None,
                "response_id": extracted.response_id,
                "extraction_prompt_sha256": extraction_prompt_hash,
                "pdf_sha256": pdf_hash,
                "cache_fingerprint": extraction_fingerprint,
                "run_configuration": extraction_configuration,
                "content_sha256": provider_api.pdf_sha256(content_path),
            },
        )
        scientific_content = extracted.text

    ok_count = 0
    failed_count = 0
    for template_name in templates:
        review_path = paper_dir / "reviews" / f"{safe_component(template_name)}.json"
        review_input = build_review_input(template_name, scientific_content)
        review_prompt_hash = prompt_sha256(review_input)
        run_configuration = run_configurations[template_name]
        configuration_fingerprint = provider_api.fingerprint(run_configuration)
        review_fingerprint = provider_api.fingerprint(
            {
                "extraction_fingerprint": extraction_fingerprint,
                "review_prompt_sha256": review_prompt_hash,
                "max_output_tokens": review_max_output_tokens,
            }
        )
        if review_path.is_file() and not force:
            try:
                existing = json.loads(review_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            if not isinstance(existing, dict):
                existing = {}
            if (
                existing.get("status") == "ok"
                and existing.get("cache_fingerprint") == review_fingerprint
                and not validate_review(existing.get("review"))
            ):
                print(f"  review {template_name}: reuse {review_path}", flush=True)
                ok_count += 1
                continue

        if not matching_successful_review(
            review_path, pdf_hash, configuration_fingerprint
        ):
            write_json(
                review_path,
                {
                    "status": "failed",
                    "error": "Review not completed",
                    "paper_id": paper_id,
                    "variant": variant,
                    "pdf_id": pdf_id,
                    "provider": provider,
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                    "prompt_template": template_name,
                    "pdf_sha256": pdf_hash,
                    "configuration_fingerprint": configuration_fingerprint,
                    "run_configuration": run_configuration,
                },
            )
        print(
            f"  review {template_name}: continue with saved scientific content",
            flush=True,
        )
        try:

            def call_and_validate_review() -> tuple[ModelText, dict[str, Any]]:
                reviewed_result = call_after_hook(
                    before_call,
                    lambda: call_text_model(
                        provider=provider,
                        model=model,
                        prompt=review_input,
                        api_key_value=api_key_value,
                        base_url=base_url,
                        max_output_tokens=review_max_output_tokens,
                        openrouter_http_referer=openrouter_http_referer,
                        openrouter_app_title=openrouter_app_title,
                        reasoning_effort=reasoning_effort,
                    ),
                )
                parsed_review = provider_api.parse_review(reviewed_result.text)
                validation_errors = validate_review(parsed_review)
                if validation_errors:
                    raise ValueError(
                        "Review JSON failed schema validation: "
                        + "; ".join(validation_errors)
                    )
                return reviewed_result, parsed_review

            # Retry format/schema failures as well as transient HTTP failures.
            # The original method prompt is reused unchanged on every attempt.
            reviewed, review = retry_text_call(
                call_and_validate_review, max_retries, api_key_value
            )
            result = {
                "schema_version": 1,
                "status": "ok",
                "paper_id": paper_id,
                "variant": variant,
                "pdf_id": pdf_id,
                "pdf_filename": path.name,
                "scientific_content_path": str(content_path),
                "provider": provider,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "prompt_template": template_name,
                "prompt_variant": prompt_variant(template_name),
                "review_prompt_sha256": review_prompt_hash,
                "cache_fingerprint": review_fingerprint,
                "configuration_fingerprint": configuration_fingerprint,
                "run_configuration": run_configuration,
                "pdf_sha256": pdf_hash,
                "response_id": reviewed.response_id,
                "review": review,
            }
            ok_count += 1
        except provider_api.FatalAPIError:
            raise
        except Exception as exc:
            result = {
                "schema_version": 1,
                "status": "failed",
                "paper_id": paper_id,
                "variant": variant,
                "pdf_id": pdf_id,
                "pdf_filename": path.name,
                "scientific_content_path": str(content_path),
                "provider": provider,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "prompt_template": template_name,
                "prompt_variant": prompt_variant(template_name),
                "review_prompt_sha256": review_prompt_hash,
                "cache_fingerprint": review_fingerprint,
                "configuration_fingerprint": configuration_fingerprint,
                "run_configuration": run_configuration,
                "pdf_sha256": pdf_hash,
                "error": provider_api.safe_error(exc, api_key_value),
            }
            failed_count += 1
        write_json(review_path, result)
    return ok_count, failed_count


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    templates = ["science_core"]
    model = args.model or DEFAULT_MODELS[args.provider]

    if args.max_retries < 1:
        print("ERROR: --max-retries must be at least 1.", file=sys.stderr)
        return 2
    if not math.isfinite(args.sleep) or args.sleep < 0:
        print("ERROR: --sleep cannot be negative.", file=sys.stderr)
        return 2
    if any(
        value is not None and value < 1
        for value in (args.extract_max_output_tokens, args.review_max_output_tokens)
    ):
        print("ERROR: output token limits must be positive.", file=sys.stderr)
        return 2

    try:
        selected = select_pdfs(args.pdfs, args.pdf_dir, args.pdf_glob, args.limit)
        base_url = resolve_base_url(args.provider, args.base_url)
        extraction_prompt = load_extraction_prompt()
        run_configuration = build_run_configuration(
            provider=args.provider,
            model=model,
            base_url=base_url,
            reasoning_effort=args.reasoning_effort,
            extraction_prompt=extraction_prompt,
            extract_max_output_tokens=args.extract_max_output_tokens,
            review_max_output_tokens=args.review_max_output_tokens,
            openrouter_pdf_engine=args.openrouter_pdf_engine,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    plan = {
        "dry_run": args.dry_run,
        "provider": args.provider,
        "base_url": base_url,
        "model": model,
        "same_model_for_complete_workflow": True,
        "reasoning_effort": args.reasoning_effort,
        "review_templates": templates,
        "selected_count": len(selected),
        "selected_pdfs": [str(path) for path in selected],
        "output_dir": str(args.output_dir.resolve()),
        "extract_max_output_tokens": args.extract_max_output_tokens,
        "review_max_output_tokens": args.review_max_output_tokens,
        "pdf_engine": args.openrouter_pdf_engine
        if args.provider == "openrouter"
        else None,
        "workflow": "pdf -> saved scientific_content.md -> review",
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    try:
        key = provider_api.api_key(args.provider, args.api_key_file)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    total_ok = 0
    total_failed = 0
    for index, path in enumerate(selected, 1):
        print(
            f"[{index}/{len(selected)}] {provider_api.pdf_identity(path)}", flush=True
        )
        error_path = (
            extractor_directory(args.output_dir, path, args.provider, model)
            / "extraction_error.json"
        )
        try:
            ok_count, failed_count = process_pdf(
                path,
                provider=args.provider,
                model=model,
                templates=templates,
                output_root=args.output_dir,
                api_key_value=key,
                base_url=base_url,
                extraction_prompt=extraction_prompt,
                max_retries=args.max_retries,
                extract_max_output_tokens=args.extract_max_output_tokens,
                review_max_output_tokens=args.review_max_output_tokens,
                openrouter_pdf_engine=args.openrouter_pdf_engine,
                openrouter_http_referer=args.openrouter_http_referer,
                openrouter_app_title=args.openrouter_app_title,
                force=args.force,
                reasoning_effort=args.reasoning_effort,
            )
        except Exception as exc:
            failure = {
                "schema_version": 1,
                "status": "failed",
                "paper_id": int(provider_api.paper_id_from_pdf(path)),
                "variant": provider_api.variant_from_pdf(path),
                "pdf_id": provider_api.pdf_identity(path),
                "pdf_filename": path.name,
                "provider": args.provider,
                "model": model,
                "reasoning_effort": args.reasoning_effort,
                "prompt_template": "science_core",
                "configuration_fingerprint": provider_api.fingerprint(run_configuration),
                "run_configuration": run_configuration,
                "error": provider_api.safe_error(exc, key),
            }
            write_json(error_path, failure)
            write_json(error_path.parent / "reviews/science_core.json", failure)
            print(f"ERROR: {failure['error']}", file=sys.stderr, flush=True)
            total_failed += len(templates)
            if isinstance(exc, provider_api.FatalAPIError):
                return 1
        else:
            total_ok += ok_count
            total_failed += failed_count
            if error_path.is_file():
                error_path.unlink()
        if args.sleep and index < len(selected):
            time.sleep(args.sleep)

    print(
        json.dumps(
            {
                "pdf_count": len(selected),
                "review_ok_count": total_ok,
                "review_failed_count": total_failed,
                "output_dir": str(args.output_dir.resolve()),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    # Partial batches remain usable; failures are retained as missing cells.
    return 0 if total_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
