#!/usr/bin/env python3
"""Search the web through DeepSeek's native Search API."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable

from _proxy import system_proxy

DEFAULT_BASE_URL = "https://api.deepseek.com"
KEY_ATTRIBUTES = ["application", "codex-deepseek", "provider", "deepseek"]
MAX_TIMEOUT = 120


def bounded_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("count must be an integer") from None
    if not 1 <= count <= 50:
        raise argparse.ArgumentTypeError("count must be between 1 and 50")
    return count


def timeout_value(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a number") from None
    if not 0 < seconds <= MAX_TIMEOUT:
        raise argparse.ArgumentTypeError(f"timeout must be between 0 and {MAX_TIMEOUT}")
    return seconds


def default_key_reader() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    secret_tool = shutil.which("secret-tool")
    if not secret_tool:
        raise RuntimeError("DEEPSEEK_API_KEY is not set and secret-tool is unavailable")
    try:
        result = subprocess.run(
            [secret_tool, "lookup", *KEY_ATTRIBUTES],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "desktop keyring lookup timed out; unlock your keyring and retry"
        ) from None
    key = result.stdout.strip()
    if result.returncode or not key or any(char.isspace() for char in key):
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not set; unlock your keyring or run "
            "codex-deepseek setup-key"
        )
    return key


def api_error_message(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
        message = payload["error"]["message"]
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return f"HTTP {error.code}"
    finally:
        error.close()
    return f"HTTP {error.code}: {message}"


def search(args: argparse.Namespace, key_reader: Callable[[], str]) -> dict:
    query = " ".join(args.query).strip()
    if not query:
        raise RuntimeError("query must not be empty")
    if len(query) > 128:
        raise RuntimeError("query must be at most 128 characters")

    payload = {
        "query": query,
        "count": args.count,
        "need_content": args.need_content,
    }
    if args.ori_question:
        payload["ori_question"] = args.ori_question
    if args.localization:
        payload["localization"] = args.localization

    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/v1/tools/search",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key_reader()}",
            "Content-Type": "application/json",
            "User-Agent": "deepseek-search/1.0",
        },
    )
    proxy = system_proxy()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy} if proxy else {}
        )
    )
    try:
        with opener.open(request, timeout=args.timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(api_error_message(error)) from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"request failed: {error.reason}") from None
    except TimeoutError:
        raise RuntimeError("request timed out") from None

    try:
        result = json.loads(body.decode("utf-8"))
        results = result["results"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise RuntimeError("invalid response from DeepSeek Search API") from None
    if not isinstance(results, list):
        raise TypeError("invalid results in DeepSeek Search API response")
    return {"results": results}


def print_text(results: list[dict]) -> None:
    if not results:
        print("No results.")
        return
    for index, result in enumerate(results, 1):
        print(f"{index}. {result.get('title') or '(untitled)'}")
        print(f"   {result.get('url') or ''}")
        details = []
        if result.get("site_name"):
            details.append(str(result["site_name"]))
        if result.get("date"):
            details.append(str(result["date"]))
        if result.get("rerank_score") is not None:
            details.append(f"score {result['rerank_score']}")
        if details:
            print("   " + " | ".join(details))
        summary = result.get("summary") or result.get("snippet")
        if summary:
            print(f"   {summary}")
        if index != len(results):
            print()


def main(
    argv: list[str] | None = None,
    *,
    key_reader: Callable[[], str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="deepseek-search",
        description=__doc__,
    )
    parser.add_argument("query", nargs="+", help="search query (1-128 characters)")
    parser.add_argument("-n", "--count", type=bounded_count, default=10)
    parser.add_argument(
        "--need-content",
        action="store_true",
        help="include full page Markdown in each result",
    )
    parser.add_argument("--ori-question", help="original user question for intent")
    parser.add_argument("--localization", help="IP address for localized results")
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--timeout", type=timeout_value, default=60)
    args = parser.parse_args(argv)

    reader = key_reader or default_key_reader
    try:
        result = search(args, reader)
    except (RuntimeError, TypeError) as error:
        print(f"deepseek-search: {error}", file=sys.stderr)
        return 1

    if args.json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_text(result["results"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
