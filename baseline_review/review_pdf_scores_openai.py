#!/usr/bin/env python3
"""Review benchmark PDFs with the OpenAI or OpenRouter API.

Provider-specific API keys are read from environment variables, from the
repository-local ignored key files, or from hidden interactive input. Keys are
never written to output files.
"""

from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import getpass
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from build_iclr_review_prompt import (
    DEFAULT_TEMPLATE_NAME,
    available_prompt_templates,
    get_review_prompt_template,
    validate_review,
)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    base_url_env: str
    api_key_env: str
    api_key_filename: str
    default_model: str


PROVIDERS = {
    "openai": ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        base_url_env="OPENAI_BASE_URL",
        api_key_env="OPENAI_API_KEY",
        api_key_filename="openai_api",
        default_model="gpt-5.5",
    ),
    "openrouter": ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        base_url_env="OPENROUTER_BASE_URL",
        api_key_env="OPENROUTER_API_KEY",
        api_key_filename="openrouter_api",
        default_model="openai/gpt-5-mini",
    ),
}
DEFAULT_PROVIDER = "openai"
OPENROUTER_PDF_ENGINES = ("auto", "cloudflare-ai", "mistral-ocr", "native")
DEFAULT_PDF_GLOB = "*/original.pdf"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF_DIR = str(REPO_ROOT / "papers")
DEFAULT_METADATA = str(REPO_ROOT / "data" / "meta.json")
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "results" / "baseline_review"


class FatalAPIError(RuntimeError):
    """An API error that will not improve by retrying later documents."""


class DocumentAPIError(RuntimeError):
    """An API rejection limited to the current manuscript."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDERS),
        default=DEFAULT_PROVIDER,
        help="API provider (default: openai).",
    )
    parser.add_argument(
        "--base-url",
        help="Override the selected provider's API base URL.",
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        help="Override the selected provider's local API key file.",
    )
    parser.add_argument("--pdf-dir", default=DEFAULT_PDF_DIR)
    parser.add_argument(
        "--pdf-glob",
        default=DEFAULT_PDF_GLOB,
        help=f"Filename glob within --pdf-dir (default: {DEFAULT_PDF_GLOB}).",
    )
    parser.add_argument("--metadata", default=DEFAULT_METADATA)
    parser.add_argument(
        "--output-dir",
        help="Output directory. Defaults to results/baseline_review/<provider>/<model>/<template>.",
    )
    parser.add_argument(
        "--model",
        help="Provider model ID. When omitted, uses a provider-specific default.",
    )
    parser.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE_NAME,
        choices=available_prompt_templates(),
        help="Review prompt template from review_prompt_bank.md.",
    )
    parser.add_argument(
        "--limit", type=int, default=1, help="Maximum PDFs; 0 means all."
    )
    parser.add_argument("--seed", type=int, default=202506)
    parser.add_argument("--only-id", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high"),
        help="Explicit reasoning effort; omitted preserves provider defaults.",
    )
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--openrouter-pdf-engine",
        choices=OPENROUTER_PDF_ENGINES,
        default="auto",
        help="OpenRouter PDF parser (default: auto uses provider defaults).",
    )
    parser.add_argument(
        "--openrouter-http-referer",
        help="Optional OpenRouter HTTP-Referer attribution header.",
    )
    parser.add_argument(
        "--openrouter-app-title",
        help="Optional OpenRouter X-OpenRouter-Title attribution header.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Independent review calls per PDF (default: 1); when greater than 1, numeric review fields are averaged.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and show resolved configuration without reading a key or calling an API.",
    )
    return parser.parse_args(argv)


def validate_http_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(char) < 33 for char in value)
    ):
        raise ValueError(
            "API URL must have a hostname and no credentials, query, fragment, or whitespace."
        )
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError(
            "API URLs require HTTPS; HTTP is allowed only for loopback testing."
        )
    return value


def normalized_base_url(value: str) -> str:
    return validate_http_url(value.strip().rstrip("/"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an API credential or manuscript to a redirected endpoint.
        raise FatalAPIError(
            "API redirects are not followed; use the final HTTPS base URL."
        )


HTTP_OPENER = urllib.request.build_opener(NoRedirect())


def open_api_request(request: urllib.request.Request, timeout: float):
    validate_http_url(request.full_url)
    return HTTP_OPENER.open(request, timeout=timeout)


def safe_error(exc: Exception, api_key_value: str = "") -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}: API request failed"
    message = str(exc)
    if api_key_value:
        message = message.replace(api_key_value, "[redacted]")
    for config in PROVIDERS.values():
        key = os.environ.get(config.api_key_env)
        if key:
            message = message.replace(key, "[redacted]")
    message = re.sub(r"(?i)Bearer\s+\S+", "Bearer [redacted]", message)
    message = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[redacted]", message)
    return f"{type(exc).__name__}: {message[:500]}"


def http_error_scope(exc: urllib.error.HTTPError) -> str:
    """Classify an HTTP failure without exposing the provider response body."""
    if exc.code in {401, 402, 403}:
        return "fatal"
    if exc.code not in {400, 404, 413, 422}:
        return "retry"
    try:
        body = exc.read(16_384).decode("utf-8", errors="replace")
    except OSError:
        body = ""
    try:
        payload = json.loads(body)
    except ValueError:
        payload = {}
    error = payload.get("error", payload) if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        error = {}
    details = body.lower() if not error else " ".join(
        str(error.get(field) or "").lower()
        for field in ("code", "type", "param", "message", "metadata")
    )
    if any(
        marker in details
        for marker in (
            "invalid_api_key", "invalid api key", "model_not_found",
            "invalid_model", "unknown model", "unsupported model",
            "insufficient_quota", "billing", "authentication",
        )
    ):
        return "fatal"
    if exc.code == 413:
        return "document"
    if any(
        marker in details
        for marker in (
            "context_length", "context length", "too many tokens",
            "input tokens", "file_too_large", "file too large",
            "invalid_file", "file_not_found", "invalid_pdf", "pdf", "document",
            "page limit", "payload too large", "request too large",
        )
    ):
        return "document"
    return "fatal"


def retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    if not value:
        return None
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
    except ValueError:
        pass
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def retry_delay(attempt: int, exc: urllib.error.HTTPError | None = None) -> float:
    if exc is not None and exc.code == 429:
        advised = retry_after_seconds(exc)
        if advised is not None:
            return advised
        base = min(5 * 2 ** (attempt - 1), 60)
        return base + random.uniform(0, base / 4)
    return min(2**attempt, 20)


def provider_failure(error: Any) -> None:
    code = error.get("code") if isinstance(error, dict) else None
    if str(code) in {
        "400",
        "401",
        "402",
        "403",
        "404",
        "422",
        "invalid_api_key",
        "model_not_found",
        "insufficient_quota",
    }:
        raise FatalAPIError(f"API rejected the request (code {code})")
    raise RuntimeError("API returned an error response")


def require_openai_response(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise RuntimeError("Responses API returned a non-object response")
    if response.get("error"):
        provider_failure(response["error"])
    if response.get("status") != "completed":
        raise RuntimeError("Responses API did not complete the response")
    for item in response.get("output", []):
        if not isinstance(item, dict):
            raise RuntimeError("Responses API returned invalid output")
        if item.get("status") not in {None, "completed"}:
            raise RuntimeError("Responses API returned incomplete output")
        for part in item.get("content", []):
            if not isinstance(part, dict) or part.get("type") == "refusal":
                raise RuntimeError("Responses API refused or returned invalid content")
    return response


def fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def pdf_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "model"


def api_key(provider: str, key_file: Path | None = None) -> str:
    config = PROVIDERS[provider]
    key = os.environ.get(config.api_key_env, "").strip()
    if key:
        if any(character.isspace() for character in key):
            raise RuntimeError("API key must not contain whitespace.")
        return key

    resolved_key_file = key_file or (REPO_ROOT / config.api_key_filename)
    try:
        key = resolved_key_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        key = ""
    except OSError as exc:
        raise RuntimeError(
            f"Cannot read API key file {resolved_key_file}: {exc}"
        ) from exc
    if key:
        if any(character.isspace() for character in key):
            raise RuntimeError(
                f"{resolved_key_file} must contain only one API key with no internal whitespace."
            )
        return key

    if not sys.stdin.isatty():
        raise RuntimeError(
            f"{config.api_key_env} is not set and {resolved_key_file} is empty; "
            "add the key to either source before running a live review."
        )
    key = getpass.getpass(f"{config.api_key_env}: ").strip()
    if not key:
        raise RuntimeError(f"{config.api_key_env} is required.")
    return key


def paper_id_from_pdf(path: Path) -> str:
    """Read the numeric paper ID from papers/<id>/... paths."""
    parent = path.parent.parent if path.parent.name == "rewrites" else path.parent
    if (
        not parent.name.isdigit()
        or str(int(parent.name)) != parent.name
        or int(parent.name) < 1
    ):
        raise ValueError(f"Cannot extract a numeric paper ID from PDF path: {path}")
    return parent.name


def variant_from_pdf(path: Path) -> str:
    if path.name == "original.pdf" and path.parent.name != "rewrites":
        return "original"
    if path.parent.name == "rewrites" and re.fullmatch(
        r"condition_(?:0[1-9]|1[0-9]|20)\.pdf", path.name
    ):
        return path.stem
    raise ValueError(f"PDF does not follow the benchmark layout: {path}")


def pdf_identity(path: Path) -> str:
    return f"{paper_id_from_pdf(path)}/{variant_from_pdf(path)}"


def load_metadata(path: Path) -> dict[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        papers = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSONL in {path} at line {line_number}: {exc}"
                ) from exc
            if isinstance(item, dict):
                papers.append(item)
    else:
        if isinstance(value, list):
            papers = value
        elif isinstance(value, dict) and isinstance(value.get("papers"), list):
            papers = value["papers"]
        elif isinstance(value, dict) and "arxiv_id" in value:
            papers = [value]
        elif isinstance(value, dict) and all(
            isinstance(item, dict) for item in value.values()
        ):
            papers = list(value.values())
        else:
            raise ValueError(
                f"Metadata in {path} must be a JSON array, object map, or JSONL records."
            )

    invalid = [
        index
        for index, paper in enumerate(papers)
        if not isinstance(paper, dict)
        or "paper_id" not in paper
        or "arxiv_id" not in paper
    ]
    if invalid:
        raise ValueError(
            f"Metadata in {path} contains records without paper_id or arxiv_id at indexes: {invalid[:10]}"
        )
    result = {}
    for paper in papers:
        paper_id = paper["paper_id"]
        if type(paper_id) is not int or paper_id <= 0 or str(paper_id) in result:
            raise ValueError("Metadata requires unique positive integer paper IDs")
        result[str(paper_id)] = paper
    return result


def metadata_score(
    paper: dict[str, Any],
    aggregate_keys: tuple[str, ...],
    review_key: str,
) -> float:
    for key in aggregate_keys:
        value = number(paper.get(key))
        if value is not None:
            return value
    reviews = paper.get("reviews")
    if isinstance(reviews, list):
        values = [
            value
            for review in reviews
            if isinstance(review, dict)
            for value in [number(review.get(review_key))]
            if value is not None
        ]
        if values:
            return sum(values) / len(values)
    keys = ", ".join(aggregate_keys)
    raise ValueError(
        f"Metadata record {paper.get('arxiv_id')} lacks {keys} and review field {review_key}."
    )


def select_pdfs(
    pdf_dir: Path,
    metadata: dict[str, dict[str, Any]],
    limit: int,
    seed: int,
    only_ids: list[str],
    pdf_glob: str = DEFAULT_PDF_GLOB,
) -> list[Path]:
    candidates = [
        path
        for path in pdf_dir.glob(pdf_glob)
        if path.is_file() and not path.name.startswith("._")
    ]
    unknown = [path for path in candidates if paper_id_from_pdf(path) not in metadata]
    if unknown:
        raise ValueError(f"Selected PDFs have no metadata: {unknown[:5]}")
    pdfs = candidates
    pdfs.sort(key=lambda path: (int(paper_id_from_pdf(path)), variant_from_pdf(path)))
    if only_ids:
        wanted = set(only_ids)
        selected = [
            path
            for path in pdfs
            if paper_id_from_pdf(path) in wanted
            or str(metadata[paper_id_from_pdf(path)]["arxiv_id"]) in wanted
        ]
        found = {
            requested
            for path in selected
            for requested in (
                paper_id_from_pdf(path),
                str(metadata[paper_id_from_pdf(path)]["arxiv_id"]),
            )
        }
        missing = sorted(wanted - found)
        if missing:
            raise RuntimeError("Requested IDs not found: " + ", ".join(missing))
        return selected if limit == 0 else selected[:limit]
    if limit == 0 or len(pdfs) <= limit:
        return pdfs
    return sorted(
        sorted(
            pdfs,
            key=lambda path: hashlib.sha256(
                f"{seed}:{pdf_identity(path)}".encode()
            ).digest(),
        )[:limit],
        key=lambda path: (int(paper_id_from_pdf(path)), variant_from_pdf(path)),
    )


def request_json(
    method: str,
    url: str,
    api_key_value: str,
    payload: dict[str, Any] | None = None,
    *,
    extra_headers: dict[str, str] | None = None,
    timeout: float = 300,
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key_value}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )
    with open_api_request(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def upload_file(
    path: Path,
    api_key_value: str,
    base_url: str,
    *,
    purpose: str = "user_data",
) -> str:
    boundary = f"----robustreview-{time.time_ns()}"
    body_parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        body_parts.append(f"--{boundary}\r\n".encode())
        body_parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        body_parts.append(value.encode())
        body_parts.append(b"\r\n")

    def add_file(name: str, file_path: Path) -> None:
        # Keep local paper IDs out of the remote filename for every reviewer
        # workflow that reuses this shared upload helper.
        body_parts.append(f"--{boundary}\r\n".encode())
        body_parts.append(
            (
                f'Content-Disposition: form-data; name="{name}"; filename="paper.pdf"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode()
        )
        body_parts.append(file_path.read_bytes())
        body_parts.append(b"\r\n")

    if not purpose:
        raise ValueError("OpenAI file uploads require a purpose.")
    add_field("purpose", purpose)
    add_file("file", path)
    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    endpoint = f"{base_url}/files"
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key_value}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    with open_api_request(request, timeout=300) as response:
        data = json.loads(response.read().decode("utf-8"))
    file_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
        raise RuntimeError(f"Upload to {endpoint} succeeded but returned no file id.")
    return str(file_id)


def delete_file(file_id: str, api_key_value: str, base_url: str) -> None:
    request = urllib.request.Request(
        f"{base_url}/files/{urllib.parse.quote(file_id, safe='')}",
        method="DELETE",
        headers={"Authorization": f"Bearer {api_key_value}"},
    )
    try:
        with open_api_request(request, timeout=60):
            pass
    except (OSError, RuntimeError, ValueError):
        print("WARNING: temporary provider file cleanup failed.", file=sys.stderr)


def extract_output_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    text = response.get("output_text")
    return text if isinstance(text, str) else ""


def extract_chat_output_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        text = part.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "\n".join(chunks)


def require_chat_response(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise RuntimeError("Chat completion response is not a JSON object.")
    if response.get("error"):
        provider_failure(response["error"])
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("Chat completion response has no choices.")
    first_choice = choices[0]
    if first_choice.get("error"):
        provider_failure(first_choice["error"])
    if first_choice.get("finish_reason") != "stop":
        raise RuntimeError(
            "Chat completion did not finish normally (truncated, refused, or tool output)"
        )
    message = first_choice.get("message")
    if (
        not isinstance(message, dict)
        or message.get("refusal")
        or message.get("tool_calls")
    ):
        raise RuntimeError("Chat completion refused or returned unexpected tool output")
    return response


def openrouter_headers(
    http_referer: str | None, app_title: str | None
) -> dict[str, str]:
    headers: dict[str, str] = {}
    resolved_referer = (
        http_referer
        if http_referer is not None
        else (os.environ.get("OPENROUTER_HTTP_REFERER") or "")
    ).strip()
    resolved_title = (
        app_title
        if app_title is not None
        else (os.environ.get("OPENROUTER_APP_TITLE") or "")
    ).strip()
    if resolved_referer:
        headers["HTTP-Referer"] = resolved_referer
    if resolved_title:
        headers["X-OpenRouter-Title"] = resolved_title
    return headers


def build_openai_payload(
    model: str, prompt_template: str, file_id: str, reasoning_effort: str | None = None
) -> dict[str, Any]:
    return {
        "model": model,
        **({"reasoning": {"effort": reasoning_effort}} if reasoning_effort else {}),
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt_template},
                    {"type": "input_text", "text": "Paper PDF for review."},
                    {"type": "input_file", "file_id": file_id},
                ],
            }
        ],
    }


def build_openrouter_payload(
    path: Path,
    model: str,
    prompt_template: str,
    pdf_engine: str,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    encoded_pdf = base64.b64encode(path.read_bytes()).decode("ascii")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_template},
                    {"type": "text", "text": "Paper PDF for review."},
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
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    if pdf_engine != "auto":
        payload["plugins"] = [{"id": "file-parser", "pdf": {"engine": pdf_engine}}]
    return payload


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON field: {key}")
        value[key] = item
    return value


def parse_review(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text, object_pairs_hook=unique_json_object)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0), object_pairs_hook=unique_json_object)
    if not isinstance(value, dict):
        raise ValueError("Model response JSON is not an object.")
    return value


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            parsed = float(value)
        except (ValueError, OverflowError):
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def review_pdf(
    path: Path,
    arxiv_id: str,
    model: str,
    prompt_template: str,
    api_key_value: str,
    *,
    provider: str = DEFAULT_PROVIDER,
    base_url: str | None = None,
    openrouter_pdf_engine: str = "auto",
    openrouter_http_referer: str | None = None,
    openrouter_app_title: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    del arxiv_id  # The remote filename is intentionally neutral for blinded review.
    config = PROVIDERS[provider]
    resolved_base_url = normalized_base_url(base_url or config.base_url)

    if provider == "openrouter":
        payload = build_openrouter_payload(
            path, model, prompt_template, openrouter_pdf_engine, reasoning_effort
        )
        response = request_json(
            "POST",
            f"{resolved_base_url}/chat/completions",
            api_key_value,
            payload,
            extra_headers=openrouter_headers(
                openrouter_http_referer, openrouter_app_title
            ),
        )
        response = require_chat_response(response)
        text = extract_chat_output_text(response).strip()
    else:
        file_id = upload_file(
            path, api_key_value, resolved_base_url, purpose="user_data"
        )
        try:
            payload = build_openai_payload(
                model, prompt_template, file_id, reasoning_effort
            )
            response = request_json(
                "POST",
                f"{resolved_base_url}/responses",
                api_key_value,
                payload,
            )
            response = require_openai_response(response)
            text = extract_output_text(response).strip()
        finally:
            delete_file(file_id, api_key_value, resolved_base_url)

    if not text:
        raise RuntimeError(f"{provider} returned an empty text response.")
    review = parse_review(text)
    validation_errors = validate_review(review)
    if validation_errors:
        raise ValueError(
            "Review JSON failed schema validation: " + "; ".join(validation_errors)
        )
    return {
        "status": "ok",
        "review": review,
        "raw_text": text,
        "response_id": response.get("id"),
    }


def with_retries(
    path: Path,
    arxiv_id: str,
    model: str,
    prompt_template: str,
    api_key_value: str,
    max_retries: int,
    *,
    provider: str = DEFAULT_PROVIDER,
    base_url: str | None = None,
    openrouter_pdf_engine: str = "auto",
    openrouter_http_referer: str | None = None,
    openrouter_app_title: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, max_retries + 1):
        http_error: urllib.error.HTTPError | None = None
        try:
            return review_pdf(
                path,
                arxiv_id,
                model,
                prompt_template,
                api_key_value,
                provider=provider,
                base_url=base_url,
                openrouter_pdf_engine=openrouter_pdf_engine,
                openrouter_http_referer=openrouter_http_referer,
                openrouter_app_title=openrouter_app_title,
                reasoning_effort=reasoning_effort,
            )
        except urllib.error.HTTPError as exc:
            last_error = safe_error(exc, api_key_value)
            scope = http_error_scope(exc)
            if scope == "fatal":
                raise FatalAPIError(last_error) from exc
            if scope == "document":
                return {"status": "failed", "error": last_error}
            http_error = exc
        except FatalAPIError:
            raise
        except Exception as exc:
            last_error = safe_error(exc, api_key_value)
        if attempt < max_retries:
            time.sleep(retry_delay(attempt, http_error))
        elif http_error is not None and http_error.code == 429:
            raise FatalAPIError(
                f"HTTP 429: rate limit persisted after {max_retries} attempts"
            ) from http_error
    return {"status": "failed", "error": last_error}


def average_review_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok_results = [
        result
        for result in results
        if result.get("status") == "ok" and isinstance(result.get("review"), dict)
    ]
    if not ok_results:
        return (
            results[-1]
            if results
            else {"status": "failed", "error": "no review attempts"}
        )

    if len(results) == 1:
        return results[0]

    if len(ok_results) != len(results):
        return {
            "status": "failed",
            "error": "Not all requested repeats succeeded",
            "repeated_results": results,
            "repeat_ok_count": len(ok_results),
            "repeat_count": len(results),
        }

    averaged: dict[str, Any] = dict(ok_results[0]["review"])
    for key in ("rating", "soundness", "presentation", "contribution", "confidence"):
        values: list[float] = []
        for result in ok_results:
            review = result.get("review")
            if not isinstance(review, dict):
                continue
            value = number(review.get(key))
            if value is not None:
                values.append(value)
        if values:
            averaged[key] = sum(values) / len(values)

    first = ok_results[0]
    return {
        "status": "ok",
        "review": averaged,
        "raw_text": first.get("raw_text"),
        "response_id": first.get("response_id"),
        "repeated_results": results,
        "repeat_ok_count": len(ok_results),
        "repeat_count": len(results),
    }


def row_template_name(item: dict[str, Any]) -> str:
    return str(item.get("prompt_template") or DEFAULT_TEMPLATE_NAME)


def row_provider_name(item: dict[str, Any]) -> str:
    return str(item.get("provider") or DEFAULT_PROVIDER)


def latest_attempt_row(
    previous: dict[str, Any] | None, candidate: dict[str, Any]
) -> dict[str, Any]:
    """An interrupted retry does not erase a matching completed success."""
    if (
        previous is not None
        and previous.get("status") == "ok"
        and candidate.get("status") == "pending"
        and all(
            previous.get(field) is not None
            and previous.get(field) == candidate.get(field)
            for field in ("pdf_sha256", "configuration_fingerprint")
        )
        and (
            not candidate.get("cache_fingerprint")
            or previous.get("cache_fingerprint") == candidate["cache_fingerprint"]
        )
    ):
        return previous
    return candidate


def load_done(
    jsonl_path: Path,
    prompt_template_name: str,
    provider: str,
    model: str,
    expected_fingerprints: dict[str, str],
) -> set[str]:
    # Completed failures supersede successes; interrupted matching retries do not.
    latest: dict[str, dict[str, Any]] = {}
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("Review log contains a non-object record")
            if (
                row_template_name(item) == prompt_template_name
                and row_provider_name(item) == provider
                and str(item.get("model")) == model
            ):
                key = str(item.get("pdf_id") or "")
                latest[key] = latest_attempt_row(latest.get(key), item)
    return {
        key
        for key, item in latest.items()
        if key in expected_fingerprints
        and item.get("status") == "ok"
        and item.get("cache_fingerprint") == expected_fingerprints[key]
        and number(item.get("model_rating")) is not None
    }


def load_result_rows(
    jsonl_path: Path,
    allowed_paper_ids: set[str] | None = None,
    prompt_template_name: str = DEFAULT_TEMPLATE_NAME,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
) -> list[dict[str, Any]]:
    if not jsonl_path.exists():
        return []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for line in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        arxiv_id = str(item.get("arxiv_id", ""))
        paper_id = str(item.get("paper_id", ""))
        if not arxiv_id or not paper_id:
            continue
        if allowed_paper_ids is not None and paper_id not in allowed_paper_ids:
            continue
        if row_template_name(item) != prompt_template_name:
            continue
        if row_provider_name(item) != provider:
            continue
        if model is not None and str(item.get("model")) != model:
            continue
        key = (arxiv_id, str(item.get("pdf_id") or item.get("pdf_filename") or ""))
        if key not in by_key:
            order.append(key)
        by_key[key] = latest_attempt_row(by_key.get(key), item)
    return [by_key[key] for key in order]


def write_summary(rows: list[dict[str, Any]], output_dir: Path) -> None:
    csv_path = output_dir / "summary.csv"
    fields = [
        "paper_id",
        "variant",
        "pdf_id",
        "arxiv_id",
        "pdf_filename",
        "title",
        "label",
        "provider",
        "model",
        "prompt_template",
        "reasoning_effort",
        "configuration_fingerprint",
        "actual_average_overall_assessment",
        "model_rating",
        "rating_gap",
        "rating_abs_gap",
        "actual_mean_soundness",
        "model_soundness",
        "soundness_gap",
        "soundness_abs_gap",
        "actual_mean_contribution",
        "model_contribution",
        "contribution_gap",
        "contribution_abs_gap",
        "actual_mean_presentation",
        "model_presentation",
        "presentation_gap",
        "presentation_abs_gap",
        "actual_mean_confidence",
        "model_confidence",
        "confidence_gap",
        "confidence_abs_gap",
        "status",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})

    ok_rows = [
        row
        for row in rows
        if row.get("status") == "ok" and row.get("rating_abs_gap") is not None
    ]
    metrics: dict[str, Any] = {"count": len(rows), "ok_count": len(ok_rows)}
    if ok_rows:
        for field in (
            "rating",
            "soundness",
            "presentation",
            "contribution",
            "confidence",
        ):
            gap_key = f"{field}_gap"
            abs_key = f"{field}_abs_gap"
            field_rows = [row for row in ok_rows if row.get(abs_key) is not None]
            if not field_rows:
                continue
            signed = [float(row[gap_key]) for row in field_rows]
            absolute = [float(row[abs_key]) for row in field_rows]
            metrics[f"{field}_mean_signed_gap"] = sum(signed) / len(signed)
            metrics[f"{field}_mean_absolute_gap"] = sum(absolute) / len(absolute)
            metrics[f"{field}_max_absolute_gap"] = max(absolute)
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = PROVIDERS[args.provider]
    model = args.model or config.default_model
    try:
        base_url = normalized_base_url(
            args.base_url or os.environ.get(config.base_url_env) or config.base_url
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.limit < 0:
        print("ERROR: --limit cannot be negative.", file=sys.stderr)
        return 2
    if args.max_retries < 1:
        print("ERROR: --max-retries must be at least 1.", file=sys.stderr)
        return 2
    if args.repeats < 1:
        print("ERROR: --repeats must be at least 1.", file=sys.stderr)
        return 2
    if not math.isfinite(args.sleep) or args.sleep < 0:
        print("ERROR: --sleep cannot be negative.", file=sys.stderr)
        return 2

    pdf_dir = Path(args.pdf_dir)
    metadata_path = Path(args.metadata)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else DEFAULT_OUTPUT_ROOT
        / args.provider
        / safe_path_component(model)
        / args.template
    )
    try:
        if not pdf_dir.is_dir():
            raise FileNotFoundError(f"PDF directory not found: {pdf_dir}")
        if not metadata_path.is_file():
            raise FileNotFoundError(f"Metadata file not found: {metadata_path}")
        metadata = load_metadata(metadata_path)
        selected = select_pdfs(
            pdf_dir, metadata, args.limit, args.seed, args.only_id, args.pdf_glob
        )
        if not selected:
            raise RuntimeError(
                f"No metadata-matched PDFs found in {pdf_dir} with glob {args.pdf_glob!r}."
            )
        prompt_template = get_review_prompt_template(args.template)
        for path in selected:
            paper = metadata[paper_id_from_pdf(path)]
            metadata_score(
                paper,
                ("average_overall_assessment", "actual_average_overall_assessment"),
                "overall_assessment",
            )
            for field in ("soundness", "presentation", "contribution", "confidence"):
                metadata_score(paper, (f"actual_mean_{field}",), field)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    run_configuration = {
        "provider": args.provider,
        "model": model,
        "base_url": base_url,
        "reasoning_effort": args.reasoning_effort,
        "repeats": args.repeats,
        "pdf_engine": args.openrouter_pdf_engine
        if args.provider == "openrouter"
        else None,
        "prompt_template": args.template,
        "prompt_sha256": hashlib.sha256(prompt_template.encode()).hexdigest(),
    }
    configuration_fingerprint = fingerprint(run_configuration)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "run_configuration": run_configuration,
                    "provider": args.provider,
                    "base_url": base_url,
                    "model": model,
                    "reasoning_effort": args.reasoning_effort,
                    "pdf_dir": str(pdf_dir),
                    "pdf_glob": args.pdf_glob,
                    "metadata": str(metadata_path),
                    "output_dir": str(output_dir),
                    "prompt_template": args.template,
                    "selected_count": len(selected),
                    "selected_pdfs": [pdf_identity(path) for path in selected],
                },
                indent=2,
            )
        )
        return 0

    try:
        key = api_key(args.provider, args.api_key_file)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "reviews.jsonl"
    pdf_hashes = {pdf_identity(path): pdf_sha256(path) for path in selected}
    fingerprints = {
        pdf_id: fingerprint(
            {
                "pdf_sha256": digest,
                "configuration_fingerprint": configuration_fingerprint,
            }
        )
        for pdf_id, digest in pdf_hashes.items()
    }
    done = (
        set()
        if args.force
        else load_done(jsonl_path, args.template, args.provider, model, fingerprints)
    )
    failed_count = 0
    fatal_error = False

    rows: list[dict[str, Any]] = []
    with jsonl_path.open("a", encoding="utf-8") as jsonl:
        for index, path in enumerate(selected, 1):
            paper_id = paper_id_from_pdf(path)
            variant = variant_from_pdf(path)
            pdf_id = pdf_identity(path)
            paper = metadata[paper_id]
            arxiv_id = str(paper["arxiv_id"])
            if pdf_id in done:
                print(f"[{index}/{len(selected)}] skip {pdf_id}", flush=True)
                continue

            print(f"[{index}/{len(selected)}] review {pdf_id} ({arxiv_id})", flush=True)
            jsonl.write(
                json.dumps(
                    {
                        "status": "pending",
                        "paper_id": int(paper_id),
                        "variant": variant,
                        "pdf_id": pdf_id,
                        "arxiv_id": arxiv_id,
                        "model_rating": None,
                        "provider": args.provider,
                        "model": model,
                        "prompt_template": args.template,
                        "reasoning_effort": args.reasoning_effort,
                        "configuration_fingerprint": configuration_fingerprint,
                        "cache_fingerprint": fingerprints[pdf_id],
                        "run_configuration": run_configuration,
                        "pdf_sha256": pdf_hashes[pdf_id],
                    }
                )
                + "\n"
            )
            jsonl.flush()
            repeat_results = []
            repeat_count = max(args.repeats, 1)
            for repeat_index in range(1, repeat_count + 1):
                if repeat_count > 1:
                    print(f"  repeat {repeat_index}/{repeat_count}", flush=True)
                try:
                    repeat_results.append(
                        with_retries(
                            path,
                            arxiv_id,
                            model,
                            prompt_template,
                            key,
                            args.max_retries,
                            provider=args.provider,
                            base_url=base_url,
                            openrouter_pdf_engine=args.openrouter_pdf_engine,
                            openrouter_http_referer=args.openrouter_http_referer,
                            openrouter_app_title=args.openrouter_app_title,
                            reasoning_effort=args.reasoning_effort,
                        )
                    )
                except FatalAPIError as exc:
                    print(f"FATAL: {exc}", file=sys.stderr, flush=True)
                    fatal_error = True
                    repeat_results.append({"status": "failed", "error": str(exc)})
                    break
                if args.sleep and repeat_index < repeat_count:
                    time.sleep(args.sleep)
            result = average_review_results(repeat_results)
            if result.get("status") != "ok":
                failed_count += 1
            result_review = result.get("review")
            review: dict[str, Any] = (
                result_review if isinstance(result_review, dict) else {}
            )
            actual = metadata_score(
                paper,
                ("average_overall_assessment", "actual_average_overall_assessment"),
                "overall_assessment",
            )
            actual_soundness = metadata_score(
                paper, ("actual_mean_soundness",), "soundness"
            )
            actual_presentation = metadata_score(
                paper, ("actual_mean_presentation",), "presentation"
            )
            actual_contribution = metadata_score(
                paper, ("actual_mean_contribution",), "contribution"
            )
            actual_confidence = metadata_score(
                paper, ("actual_mean_confidence",), "confidence"
            )
            model_rating = number(review.get("rating"))
            model_soundness = number(review.get("soundness"))
            model_presentation = number(review.get("presentation"))
            model_contribution = number(review.get("contribution"))
            model_confidence = number(review.get("confidence"))
            rating_gap = None if model_rating is None else model_rating - actual
            soundness_gap = (
                None if model_soundness is None else model_soundness - actual_soundness
            )
            presentation_gap = (
                None
                if model_presentation is None
                else model_presentation - actual_presentation
            )
            contribution_gap = (
                None
                if model_contribution is None
                else model_contribution - actual_contribution
            )
            confidence_gap = (
                None
                if model_confidence is None
                else model_confidence - actual_confidence
            )
            row = {
                "paper_id": int(paper_id),
                "variant": variant,
                "pdf_id": pdf_id,
                "arxiv_id": arxiv_id,
                "pdf": str(path),
                "pdf_filename": path.name,
                "title": paper.get("title"),
                "label": paper.get("label"),
                "actual_average_overall_assessment": actual,
                "provider": args.provider,
                "model": model,
                "reasoning_effort": args.reasoning_effort,
                "pdf_sha256": pdf_hashes[pdf_id],
                "cache_fingerprint": fingerprints[pdf_id],
                "configuration_fingerprint": configuration_fingerprint,
                "run_configuration": run_configuration,
                "prompt_template": args.template,
                "model_rating": model_rating,
                "rating_gap": rating_gap,
                "rating_abs_gap": None if rating_gap is None else abs(rating_gap),
                "actual_mean_soundness": actual_soundness,
                "model_soundness": model_soundness,
                "soundness_gap": soundness_gap,
                "soundness_abs_gap": None
                if soundness_gap is None
                else abs(soundness_gap),
                "actual_mean_presentation": actual_presentation,
                "model_presentation": model_presentation,
                "presentation_gap": presentation_gap,
                "presentation_abs_gap": None
                if presentation_gap is None
                else abs(presentation_gap),
                "actual_mean_contribution": actual_contribution,
                "model_contribution": model_contribution,
                "contribution_gap": contribution_gap,
                "contribution_abs_gap": None
                if contribution_gap is None
                else abs(contribution_gap),
                "actual_mean_confidence": actual_confidence,
                "model_confidence": model_confidence,
                "confidence_gap": confidence_gap,
                "confidence_abs_gap": None
                if confidence_gap is None
                else abs(confidence_gap),
                **result,
            }
            jsonl.write(json.dumps(row, ensure_ascii=False) + "\n")
            jsonl.flush()
            rows.append(row)
            if fatal_error:
                break
            if args.sleep:
                time.sleep(args.sleep)

    rows = load_result_rows(
        jsonl_path, set(metadata), args.template, args.provider, model
    )
    rows = [
        row
        for row in rows
        if str(row.get("pdf_id")) in fingerprints
        and row.get("cache_fingerprint") == fingerprints[str(row.get("pdf_id"))]
    ]
    write_summary(rows, output_dir)
    print(f"wrote {jsonl_path}", flush=True)
    print(f"wrote {output_dir / 'summary.csv'}", flush=True)
    print(f"wrote {output_dir / 'metrics.json'}", flush=True)
    print(
        json.dumps(
            {
                "selected_count": len(selected),
                "cached_count": len(done),
                "failed_count": failed_count,
            }
        ),
        flush=True,
    )
    # Partial batches remain usable; failures are retained as missing cells.
    return 1 if fatal_error or not any(row.get("status") == "ok" for row in rows) else 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {safe_error(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
