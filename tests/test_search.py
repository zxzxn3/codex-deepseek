"""Offline tests for the bundled DeepSeek search helper."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from search_tool import deepseek_search


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class FakeOpener:
    def __init__(self, payload: dict):
        self.payload = payload
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout):
        self.request = request
        self.timeout = timeout
        return FakeResponse(self.payload)


class SearchTest(unittest.TestCase):
    def test_json_payload_and_output(self):
        opener = FakeOpener({
            "results": [{
                "title": "Example",
                "url": "https://example.com",
                "summary": "summary",
                "snippet": "snippet",
                "content": "content",
                "rerank_score": 2.4,
            }],
        })
        output = io.StringIO()
        with patch.object(deepseek_search, "system_proxy", return_value=None), \
             patch.object(deepseek_search.urllib.request, "build_opener",
                          return_value=opener), \
             contextlib.redirect_stdout(output):
            code = deepseek_search.main(
                ["--json", "-n", "2", "--need-content", "DeepSeek", "V4"],
                key_reader=lambda: "test-key",
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["results"][0]["title"], "Example")
        self.assertEqual(opener.request.headers["Authorization"], "Bearer test-key")
        self.assertEqual(opener.timeout, 60)
        self.assertEqual(json.loads(opener.request.data), {
            "query": "DeepSeek V4",
            "count": 2,
            "need_content": True,
        })

    def test_text_output_and_api_error(self):
        opener = FakeOpener({
            "results": [{
                "title": "Example",
                "url": "https://example.com",
                "summary": "summary",
                "snippet": "snippet",
                "content": "",
                "rerank_score": 2.4,
            }],
        })
        output = io.StringIO()
        with patch.object(deepseek_search, "system_proxy", return_value=None), \
             patch.object(deepseek_search.urllib.request, "build_opener",
                          return_value=opener), \
             contextlib.redirect_stdout(output):
            self.assertEqual(
                deepseek_search.main(["DeepSeek"], key_reader=lambda: "key"),
                0,
            )
        self.assertIn("Example", output.getvalue())
        self.assertIn("https://example.com", output.getvalue())

        error = urllib.error.HTTPError(
            "https://api.deepseek.com/v1/tools/search",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"error":{"message":"mock failure"}}'),
        )
        stderr = io.StringIO()
        with patch.object(deepseek_search, "system_proxy", return_value=None), \
             patch.object(deepseek_search.urllib.request, "build_opener") as build, \
             contextlib.redirect_stderr(stderr):
            build.return_value.open.side_effect = error
            self.assertEqual(
                deepseek_search.main(["fail"], key_reader=lambda: "key"),
                1,
            )
        self.assertIn("mock failure", stderr.getvalue())

    def test_help_and_invalid_args_do_not_read_the_key(self):
        called = False

        def reader():
            nonlocal called
            called = True
            return "key"

        with contextlib.redirect_stdout(io.StringIO()), \
             self.assertRaises(SystemExit) as caught:
            deepseek_search.main(["--help"], key_reader=reader)
        self.assertEqual(caught.exception.code, 0)
        self.assertFalse(called)

        with contextlib.redirect_stderr(io.StringIO()), \
             self.assertRaises(SystemExit) as caught:
            deepseek_search.main(["query", "-n", "51"], key_reader=reader)
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
