"""Offline tests for rollout usage parsing, pricing and terminal rendering."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "usage_tool"))
import codex_usage
from codex_usage import TIMEZONE, estimate_cost, is_peak


NOW = datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)  # 14:00 in Shanghai.


def event(kind: str, payload: dict, moment: str) -> dict:
    return {"timestamp": moment, "type": kind, "payload": payload}


def usage_record(response_id: str, *, provider: str = "deepseek",
                 model: str = "deepseek-flash", timestamp: str =
                 "2026-11-09T05:00:00Z", input_tokens: int = 1000,
                 cached: int = 800, output: int = 100,
                 reasoning: int = 50) -> list[dict]:
    turn_id = f"turn-{response_id}"
    return [
        event("session_meta", {"session_id": "session", "model_provider": provider},
              "2026-11-09T01:59:00Z"),
        event("turn_context", {"turn_id": turn_id, "model": model},
              "2026-11-09T01:59:30Z"),
        event("token_usage_record", {
            "session_id": "session", "turn_id": turn_id,
            "response_id": response_id,
            "usage": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached,
                "cache_write_input_tokens": 0,
                "output_tokens": output,
                "reasoning_output_tokens": reasoning,
                "total_tokens": input_tokens + output,
            },
        }, timestamp),
    ]


def write_rollout(home: Path, lines: list[dict], name: str = "rollout-fixture.jsonl") -> Path:
    directory = home / "sessions/2026/11/09"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("".join(json.dumps(item) + "\n" for item in lines))
    return path


class PricingTest(unittest.TestCase):
    def test_peak_and_off_peak(self):
        self.assertTrue(is_peak(datetime(2026, 11, 9, 10, 0, tzinfo=TIMEZONE)))
        self.assertFalse(is_peak(datetime(2026, 11, 9, 13, 0, tzinfo=TIMEZONE)))
        self.assertFalse(is_peak(datetime(2026, 11, 7, 10, 0, tzinfo=TIMEZONE)))
        self.assertFalse(is_peak(datetime(2026, 10, 1, 10, 0, tzinfo=TIMEZONE)))

    def test_cost_uses_hit_miss_and_output_only(self):
        estimate = estimate_cost(
            "deepseek-flash",
            datetime(2026, 11, 9, 13, 0, tzinfo=TIMEZONE),
            input_tokens=1000,
            cached_input_tokens=800,
            output_tokens=100,
        )
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate.total, Decimal("0.000616"))
        self.assertEqual(estimate.cache_hit, Decimal("0.000016"))
        self.assertEqual(estimate.cache_miss, Decimal("0.0002"))
        self.assertEqual(estimate.output, Decimal("0.0004"))

    def test_peak_doubles_the_estimate(self):
        estimate = estimate_cost(
            "deepseek-flash",
            datetime(2026, 11, 9, 10, 0, tzinfo=TIMEZONE),
            input_tokens=1000,
            cached_input_tokens=0,
            output_tokens=100,
        )
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate.peak_factor, 2)
        self.assertEqual(estimate.total, Decimal("0.0028"))


class UsageParsingTest(unittest.TestCase):
    def collect(self, home: Path) -> list[codex_usage.UsageRecord]:
        return codex_usage.collect_records(
            home, NOW - timedelta(days=1), NOW + timedelta(days=1))

    def test_records_are_scoped_and_duplicate_response_is_ignored(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_rollout(home, usage_record("same"), "rollout-a.jsonl")
            write_rollout(home, usage_record("other-provider", provider="openai",
                                             model="gpt-5"), "rollout-other.jsonl")
            path = home / "sessions/2026/11/09/rollout-a.jsonl"
            with path.open("a") as stream:
                stream.write(json.dumps(usage_record("same")[2]) + "\n")
            records = self.collect(home)
        self.assertEqual([record.response_id for record in records], ["same"])
        self.assertEqual(records[0].model, "deepseek-flash")
        self.assertEqual(records[0].output_tokens, 100)
        self.assertEqual(records[0].reasoning_output_tokens, 50)

    def test_incremental_scan_adds_appended_response(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = write_rollout(home, usage_record("one"))
            self.assertEqual(len(self.collect(home)), 1)
            with path.open("a") as stream:
                for item in usage_record("two")[1:]:
                    stream.write(json.dumps(item) + "\n")
            records = self.collect(home)
        self.assertEqual([record.response_id for record in records], ["one", "two"])

    def test_report_keeps_reasoning_inside_output_not_separately_billed(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_rollout(home, usage_record("one"))
            records = self.collect(home)
            report = codex_usage.build_report(
                records,
                NOW - timedelta(days=1),
                NOW + timedelta(days=1),
                NOW,
            )
        self.assertEqual(report.output_tokens, 100)
        self.assertEqual(report.cost, Decimal("0.000616"))
        self.assertEqual(report.today.output_tokens, 100)

    def test_terminal_report_and_json_are_plain_text(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_rollout(home, usage_record("one"))
            records = self.collect(home)
            report = codex_usage.build_report(
                records,
                NOW - timedelta(days=1),
                NOW + timedelta(days=1),
                NOW,
            )
            output = io.StringIO()
            codex_usage.render_report(report, chart=True, out=output)
            terminal = output.getvalue()
            self.assertIn("DeepSeek usage", terminal)
            self.assertIn("0.000616", terminal)
            self.assertIn("█", terminal)
            self.assertNotIn("\033[", terminal)

    def test_run_json(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_rollout(home, usage_record("one"))
            output = io.StringIO()
            self.assertEqual(
                codex_usage.run(["--json"], home=home, out=output, now=NOW), 0)
            data = json.loads(output.getvalue())
        self.assertEqual(data["totals"]["requests"], 1)
        self.assertEqual(data["totals"]["output_tokens"], 100)
        self.assertEqual(data["totals"]["cost_cny"], "0.000616")

    def test_standalone_copy_and_explicit_other_home(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "other-home"
            write_rollout(
                home,
                usage_record("standalone", timestamp="2026-11-08T05:00:00Z"),
            )
            copied = home / "codex_usage.py"
            shutil.copyfile(Path(__file__).parents[1] / "usage_tool/codex_usage.py",
                            copied)
            env = os.environ.copy()
            env.pop("CODEX_HOME", None)
            result = subprocess.run(
                [sys.executable, str(copied), "--json"],
                cwd=root, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["totals"]["requests"], 1)

            elsewhere = root / "elsewhere/codex_usage.py"
            elsewhere.parent.mkdir()
            shutil.copyfile(copied, elsewhere)
            result = subprocess.run(
                [sys.executable, str(elsewhere), "--json", "--home", str(home)],
                cwd=root, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["home"], str(home))


if __name__ == "__main__":
    unittest.main()
