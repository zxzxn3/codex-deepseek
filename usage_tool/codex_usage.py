#!/usr/bin/env python3
"""Read DeepSeek usage from Codex rollouts and render a terminal report.

The public entry point receives the Codex home explicitly. It does not read the
ordinary Codex home or discover other homes, which keeps the report scoped to
the selected Codex home while leaving the parser reusable. This file is
self-contained so it can be copied into another Codex home and run directly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, TextIO
from zoneinfo import ZoneInfo

PROVIDER = "deepseek"
PRICING_URL = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class Price:
    cache_hit: Decimal
    cache_miss: Decimal
    output: Decimal


@dataclass(frozen=True)
class PriceTier:
    effective_at: datetime
    prices: dict[str, Price]


@dataclass(frozen=True)
class CostEstimate:
    total: Decimal
    cache_hit: Decimal
    cache_miss: Decimal
    output: Decimal
    peak_factor: int


def _price(hit: str, miss: str, output: str) -> Price:
    return Price(Decimal(hit), Decimal(miss), Decimal(output))


OLD_FLASH = _price("0.05", "1.5", "4.5")
CURRENT_FLASH = _price("0.02", "1", "4")
PRO = _price("0.15", "4.5", "13.5")
_TIERS = (
    PriceTier(
        datetime(1970, 1, 1, tzinfo=timezone.utc),
        {
            "deepseek-flash": OLD_FLASH,
            "deepseek-v4-flash": OLD_FLASH,
            "deepseek-v4-flash-vision-exp": OLD_FLASH,
            "deepseek-v4-pro": PRO,
        },
    ),
    PriceTier(
        datetime(2026, 9, 10, 12, tzinfo=TIMEZONE),
        {
            "deepseek-flash": CURRENT_FLASH,
            "deepseek-v4-flash": CURRENT_FLASH,
            "deepseek-v4-flash-vision-exp": CURRENT_FLASH,
        },
    ),
)
_PEAK_SINCE = datetime(2026, 8, 17, 0, tzinfo=TIMEZONE)
_WEEKEND_OFFPEAK_SINCE = datetime(2026, 8, 23, 0, tzinfo=TIMEZONE)
_HOLIDAYS = frozenset({
    date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 27),
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
    date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6),
    date(2026, 10, 7),
})


def _local(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("usage timestamps must include a timezone")
    return moment.astimezone(TIMEZONE)


def price_for(model: str, when: datetime) -> Price | None:
    """Return the effective price for a model and timestamp."""
    table: dict[str, Price] = {}
    for tier in _TIERS:
        if tier.effective_at <= when:
            table.update(tier.prices)
        else:
            break
    return table.get(model)


def is_peak(when: datetime) -> bool:
    """Whether DeepSeek's doubled peak price applies at ``when``."""
    local = _local(when)
    if local < _PEAK_SINCE:
        return False
    local_day = local.date()
    if local_day in _HOLIDAYS:
        return False
    if local.weekday() >= 5 and local >= _WEEKEND_OFFPEAK_SINCE:
        return False
    minute = local.hour * 60 + local.minute
    return (9 * 60 <= minute < 12 * 60
            or 14 * 60 <= minute < 18 * 60)


def estimate_cost(
    model: str,
    when: datetime,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> CostEstimate | None:
    """Estimate one response's cost from real token usage.

    ``input_tokens`` includes cached input. ``output_tokens`` already includes
    reasoning tokens; callers must not add reasoning tokens again.
    """
    price = price_for(model, when)
    if price is None:
        return None
    cached = min(max(int(cached_input_tokens), 0), max(int(input_tokens), 0))
    cache_miss = max(int(input_tokens) - cached, 0)
    factor = 2 if is_peak(when) else 1
    divisor = Decimal(1_000_000)
    hit_cost = Decimal(cached) * price.cache_hit / divisor * factor
    miss_cost = Decimal(cache_miss) * price.cache_miss / divisor * factor
    output_cost = Decimal(max(int(output_tokens), 0)) * price.output / divisor * factor
    return CostEstimate(
        total=hit_cost + miss_cost + output_cost,
        cache_hit=hit_cost,
        cache_miss=miss_cost,
        output=output_cost,
        peak_factor=factor,
    )


CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    inode INTEGER NOT NULL,
    offset INTEGER NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    provider TEXT,
    thread_model TEXT
);
CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    model TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    response_id TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    cached_input_tokens INTEGER NOT NULL,
    cache_write_input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    reasoning_output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    legacy INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS records_timestamp ON records(timestamp_ms);
CREATE INDEX IF NOT EXISTS records_model ON records(model);
"""


@dataclass(frozen=True)
class UsageRecord:
    timestamp: datetime
    source: str
    session_id: str
    turn_id: str
    response_id: str
    model: str
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int


@dataclass
class ModelUsage:
    name: str
    requests: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal(0)
    unpriced_requests: int = 0


@dataclass
class DayUsage:
    day: date
    requests: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal(0)
    unpriced_requests: int = 0


@dataclass
class UsageReport:
    start: datetime
    end: datetime
    now: datetime
    records: list[UsageRecord]
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    requests: int
    cost: Decimal
    unpriced_requests: int
    models: list[ModelUsage]
    days: list[DayUsage]

    @property
    def cache_hit_rate(self) -> float:
        if not self.input_tokens:
            return 0.0
        return self.cached_input_tokens / self.input_tokens

    @property
    def today(self) -> DayUsage:
        today = self.now.astimezone(TIMEZONE).date()
        return next((item for item in self.days if item.day == today),
                    DayUsage(today))


def _int(value: object) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _usage_values(payload: dict) -> tuple[int, int, int, int, int, int]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = payload
    input_tokens = _int(usage.get("input_tokens"))
    cached = _int(usage.get("cached_input_tokens"))
    cache_write = _int(usage.get("cache_write_input_tokens"))
    output = _int(usage.get("output_tokens"))
    reasoning = _int(usage.get("reasoning_output_tokens"))
    total = _int(usage.get("total_tokens")) or input_tokens + output
    return input_tokens, cached, cache_write, output, reasoning, total


def _record_key(session_id: str, response_id: str, source: str, line_start: int,
                turn_id: str) -> str:
    if response_id:
        return f"response:{session_id}:{response_id}"
    return f"line:{source}:{line_start}:{turn_id}"


def _row_record(row: sqlite3.Row) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime.fromtimestamp(row["timestamp_ms"] / 1000,
                                         tz=timezone.utc),
        source=row["source"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        response_id=row["response_id"],
        model=row["model"],
        input_tokens=row["input_tokens"],
        cached_input_tokens=row["cached_input_tokens"],
        cache_write_input_tokens=row["cache_write_input_tokens"],
        output_tokens=row["output_tokens"],
        reasoning_output_tokens=row["reasoning_output_tokens"],
        total_tokens=row["total_tokens"],
    )


class UsageStore:
    """Incremental SQLite index over rollout usage records."""

    def __init__(self, home: Path):
        self.home = Path(home)
        self.cache = self.home / "usage" / "usage.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        if not self.home.is_dir():
            raise ValueError(f"Codex DeepSeek home does not exist: {self.home}")
        if self.cache.is_symlink():
            raise ValueError(f"Refusing symlinked usage cache: {self.cache}")
        self.cache.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        connection = sqlite3.connect(self.cache, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(CACHE_SCHEMA)
        return connection

    def _sources(self, start: datetime | None) -> Iterable[Path]:
        files = []
        for sessions in (self.home / "sessions",
                         self.home / "archived_sessions"):
            if not sessions.is_dir() or sessions.is_symlink():
                continue
            for path in sessions.rglob("rollout-*.jsonl"):
                if path.is_symlink() or not path.is_file():
                    continue
                if start is not None:
                    try:
                        stamp = path.stat().st_mtime
                    except OSError:
                        continue
                    # Include old path dates too, in case a saved session was
                    # resumed during the requested window.
                    if (stamp < start.timestamp()
                            and not _path_date_in_window(path, start)):
                        continue
                files.append(path)
        return files

    def _scan(self, connection: sqlite3.Connection, path: Path) -> None:
        source = str(path.relative_to(self.home))
        stat = path.stat()
        row = connection.execute(
            "SELECT * FROM files WHERE path = ?", (source,)
        ).fetchone()
        offset = 0
        provider = None
        thread_model = None
        if row is not None:
            rewritten = (
                row["inode"] != stat.st_ino
                or stat.st_size < row["offset"]
                or (stat.st_size == row["offset"] and stat.st_mtime_ns != row["mtime_ns"])
            )
            if rewritten:
                connection.execute("DELETE FROM records WHERE source = ?", (source,))
            else:
                offset = row["offset"]
                provider = row["provider"]
                thread_model = row["thread_model"]

        turns: dict[str, str] = {}
        session_id = ""
        last_model = thread_model
        pending_legacy: list[dict] = []
        primary_added = False
        consumed = offset

        with path.open("rb") as handle:
            handle.seek(offset)
            for raw in handle:
                if not raw.endswith(b"\n"):
                    break
                line_start = consumed
                consumed += len(raw)
                # Skip most rollout lines without parsing their embedded
                # messages and tool output.
                if not any(token in raw for token in (
                        b'"session_meta"', b'"turn_context"',
                        b'"thread_settings_applied"', b'"token_usage_record"',
                        b'"token_count"')):
                    continue
                try:
                    event = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                kind = event.get("type")
                payload = event.get("payload")
                if not isinstance(payload, dict):
                    continue
                if kind == "session_meta":
                    provider = payload.get("model_provider") or provider
                    session_id = str(payload.get("session_id") or session_id)
                elif kind == "turn_context":
                    model = payload.get("model")
                    turn_id = payload.get("turn_id")
                    if isinstance(model, str) and model:
                        last_model = model
                        if isinstance(turn_id, str) and turn_id:
                            turns[turn_id] = model
                            connection.execute(
                                "INSERT OR REPLACE INTO turns(turn_id, model) VALUES (?, ?)",
                                (turn_id, model),
                            )
                elif kind == "event_msg" and payload.get("type") == "thread_settings_applied":
                    settings = payload.get("thread_settings")
                    if isinstance(settings, dict):
                        model = settings.get("model")
                        provider = settings.get("model_provider_id") or provider
                        if isinstance(model, str) and model:
                            thread_model = model
                            last_model = model
                elif kind == "token_usage_record":
                    moment = _timestamp(event.get("timestamp"))
                    turn_id = str(payload.get("turn_id") or "")
                    response_id = str(payload.get("response_id") or "")
                    model = turns.get(turn_id)
                    if model is None and turn_id:
                        found = connection.execute(
                            "SELECT model FROM turns WHERE turn_id = ?", (turn_id,)
                        ).fetchone()
                        model = found["model"] if found else last_model
                    model = model or thread_model
                    if not model or not _is_deepseek(model, provider):
                        continue
                    values = _usage_values(payload)
                    if not values[5]:
                        continue
                    if moment is None:
                        continue
                    sid = str(payload.get("session_id") or session_id)
                    key = _record_key(sid, response_id, source, line_start, turn_id)
                    connection.execute(
                        """INSERT OR IGNORE INTO records(
                            key, source, timestamp_ms, timestamp, session_id, turn_id,
                            response_id, model, input_tokens, cached_input_tokens,
                            cache_write_input_tokens, output_tokens,
                            reasoning_output_tokens, total_tokens, legacy
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (key, source, int(moment.timestamp() * 1000),
                         moment.isoformat(), sid, turn_id, response_id, model,
                         *values),
                    )
                    primary_added = True
                elif kind == "event_msg" and payload.get("type") == "token_count":
                    info = payload.get("info")
                    if not isinstance(info, dict):
                        continue
                    usage = info.get("last_token_usage")
                    total_usage = info.get("total_token_usage")
                    if not isinstance(usage, dict) or not isinstance(total_usage, dict):
                        continue
                    moment = _timestamp(event.get("timestamp"))
                    model = last_model or thread_model
                    if moment is None or not model or not _is_deepseek(model, provider):
                        continue
                    values = _usage_values(usage)
                    if not values[5]:
                        continue
                    digest = hashlib.sha256(
                        json.dumps(total_usage, sort_keys=True,
                                   separators=(",", ":")).encode()
                    ).hexdigest()[:20]
                    pending_legacy.append({
                        "key": (
                            f"legacy:{session_id or source}:"
                            f"{int(moment.timestamp() * 1000)}:{digest}"
                        ),
                        "session_id": session_id,
                        "turn_id": "",
                        "timestamp": moment,
                        "values": values,
                        "model": model,
                    })

        has_primary = primary_added or connection.execute(
            "SELECT 1 FROM records WHERE source = ? AND legacy = 0 LIMIT 1",
            (source,),
        ).fetchone() is not None
        if primary_added:
            connection.execute("DELETE FROM records WHERE source = ? AND legacy = 1",
                               (source,))
        if not has_primary:
            for item in pending_legacy:
                moment = item["timestamp"]
                connection.execute(
                    """INSERT OR IGNORE INTO records(
                        key, source, timestamp_ms, timestamp, session_id, turn_id,
                        response_id, model, input_tokens, cached_input_tokens,
                        cache_write_input_tokens, output_tokens,
                        reasoning_output_tokens, total_tokens, legacy
                    ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (item["key"], source, int(moment.timestamp() * 1000),
                     moment.isoformat(), item["session_id"], item["turn_id"],
                     item["model"], *item["values"]),
                )

        connection.execute(
            """INSERT INTO files(
                path, inode, offset, size, mtime_ns, provider, thread_model
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                inode = excluded.inode, offset = excluded.offset,
                size = excluded.size, mtime_ns = excluded.mtime_ns,
                provider = excluded.provider, thread_model = excluded.thread_model""",
            (source, stat.st_ino, consumed, stat.st_size, stat.st_mtime_ns,
             provider, thread_model),
        )

    def refresh(self, start: datetime | None) -> None:
        with closing(self._connect()) as connection:
            for path in self._sources(start):
                try:
                    self._scan(connection, path)
                except (OSError, sqlite3.Error):
                    connection.rollback()
                    continue
                connection.commit()

    def records(self, start: datetime, end: datetime) -> list[UsageRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT * FROM records
                   WHERE timestamp_ms >= ? AND timestamp_ms < ?
                   ORDER BY timestamp_ms, legacy, key""",
                (int(start.timestamp() * 1000), int(end.timestamp() * 1000)),
            ).fetchall()
        records = []
        legacy_seen = set()
        for row in rows:
            if row["legacy"]:
                # Older cache versions keyed legacy records by source path.
                # Deduplicate semantic copies when sessions and archives
                # contain the same rollout.
                signature = (
                    row["session_id"], row["timestamp_ms"], row["model"],
                    row["input_tokens"], row["cached_input_tokens"],
                    row["cache_write_input_tokens"], row["output_tokens"],
                    row["reasoning_output_tokens"], row["total_tokens"],
                )
                if signature in legacy_seen:
                    continue
                legacy_seen.add(signature)
            records.append(_row_record(row))
        return records


def _is_deepseek(model: str, provider: str | None) -> bool:
    return model.startswith("deepseek") or provider == PROVIDER


def _path_date_in_window(path: Path, start: datetime) -> bool:
    parts = path.parts
    try:
        index = parts.index("sessions")
        year, month, day = (int(parts[index + 1]), int(parts[index + 2]),
                            int(parts[index + 3]))
        return date(year, month, day) >= start.date() - timedelta(days=1)
    except (ValueError, IndexError):
        return True


def _local_midnight(moment: datetime) -> datetime:
    local = moment.astimezone(TIMEZONE)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def build_report(records: list[UsageRecord], start: datetime, end: datetime,
                 now: datetime) -> UsageReport:
    totals = {
        "input": 0, "cached": 0, "output": 0, "requests": 0,
        "cost": Decimal(0), "unpriced": 0,
    }
    models: dict[str, ModelUsage] = {}
    days: dict[date, DayUsage] = {}
    for record in records:
        local_day = record.timestamp.astimezone(TIMEZONE).date()
        model = models.setdefault(record.model, ModelUsage(record.model))
        day = days.setdefault(local_day, DayUsage(local_day))
        estimate = estimate_cost(
            record.model, record.timestamp, record.input_tokens,
            record.cached_input_tokens, record.output_tokens,
        )
        totals["input"] += record.input_tokens
        totals["cached"] += min(record.cached_input_tokens, record.input_tokens)
        totals["output"] += record.output_tokens
        totals["requests"] += 1
        model.input_tokens += record.input_tokens
        model.cached_input_tokens += min(record.cached_input_tokens,
                                         record.input_tokens)
        model.output_tokens += record.output_tokens
        day.input_tokens += record.input_tokens
        day.cached_input_tokens += min(record.cached_input_tokens,
                                       record.input_tokens)
        day.output_tokens += record.output_tokens
        day.requests += 1
        model.requests += 1
        if estimate is None:
            totals["unpriced"] += 1
            model.unpriced_requests += 1
            day.unpriced_requests += 1
        else:
            totals["cost"] += estimate.total
            model.cost += estimate.total
            day.cost += estimate.total

    # Keep empty days in the chart so gaps do not move the timeline.
    start_day = start.astimezone(TIMEZONE).date()
    day_end = end
    local_end = end.astimezone(TIMEZONE)
    if end > start and local_end.time() == time.min:
        day_end -= timedelta(microseconds=1)
    end_day = day_end.astimezone(TIMEZONE).date()
    day_list = []
    while start_day <= end_day:
        day_list.append(days.get(start_day, DayUsage(start_day)))
        start_day += timedelta(days=1)
    return UsageReport(
        start=start, end=end, now=now, records=records,
        input_tokens=totals["input"],
        cached_input_tokens=totals["cached"],
        output_tokens=totals["output"],
        requests=totals["requests"],
        cost=totals["cost"],
        unpriced_requests=totals["unpriced"],
        models=sorted(models.values(), key=lambda item: item.name),
        days=day_list,
    )


def collect_records(home: Path, start: datetime, end: datetime) -> list[UsageRecord]:
    store = UsageStore(home)
    store.refresh(start)
    return store.records(start, end)


def _format_tokens(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _format_cost(value: Decimal) -> str:
    if value == 0:
        return "¥0"
    if value < Decimal("0.01"):
        return f"¥{value:.6f}"
    if value < Decimal("1"):
        return f"¥{value:.4f}"
    return f"¥{value:,.2f}"


def _style(text: str, code: str, out: TextIO) -> str:
    if (out.isatty() and "NO_COLOR" not in os.environ
            and os.environ.get("TERM") != "dumb"):
        return f"\033[{code}m{text}\033[0m"
    return text


def _render_chart(days: list[DayUsage], out: TextIO) -> None:
    if not days:
        return
    visible = days[-60:]
    maximum = max((day.cost for day in visible), default=Decimal(0))
    width = max(8, min(36, shutil.get_terminal_size((80, 24)).columns - 30))
    print(_style("Daily estimated cost", "1", out), file=out)
    for day in visible:
        if maximum <= 0:
            bar = "·"
        else:
            filled = round(float(day.cost / maximum) * width)
            bar = "█" * filled + "░" * (width - filled)
        print(f"{day.day.isoformat()}  {_format_cost(day.cost):>10}  {bar}",
              file=out)
    if len(days) > len(visible):
        print("(chart limited to the latest 60 days)", file=out)


def render_report(report: UsageReport, *, chart: bool, out: TextIO) -> None:
    start = report.start.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M")
    end = report.end.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M")
    print(_style("DeepSeek usage · estimated", "1", out), file=out)
    print(f"Period  {start} → {end}  ({TIMEZONE.key})", file=out)
    print(
        f"Today   {_format_cost(report.today.cost)}"
        f"   IN {_format_tokens(report.today.input_tokens)}"
        f"   CACHE {report.today.cached_input_tokens / report.today.input_tokens:.1%}"
        if report.today.input_tokens
        else f"Today   {_format_cost(report.today.cost)}",
        file=out,
    )
    print(
        f"Period  {_format_cost(report.cost)}"
        f"   IN {_format_tokens(report.input_tokens)}"
        f"   CACHE {report.cache_hit_rate:.1%}"
        f"   OUT {_format_tokens(report.output_tokens)}"
        f"   REQUESTS {report.requests}",
        file=out,
    )
    if report.unpriced_requests:
        print(f"Warning: {report.unpriced_requests} responses use an unknown model "
              "and are not included in cost.", file=out)
    if report.models:
        print(file=out)
        print(_style("Models", "1", out), file=out)
        for model in report.models:
            print(
                f"  {model.name:<19} {_format_cost(model.cost):>10}"
                f"  requests {model.requests:>5}"
                f"  IN {_format_tokens(model.input_tokens):>8}"
                f"  OUT {_format_tokens(model.output_tokens):>8}",
                file=out,
            )
    if chart:
        print(file=out)
        _render_chart(report.days, out)
    print(file=out)
    print(f"Source: {PRICING_URL}", file=out)
    print("Estimate only; billed amounts on platform.deepseek.com are authoritative.",
          file=out)


def _json_report(report: UsageReport, home: Path) -> dict:
    def model_item(item: ModelUsage) -> dict:
        return {
            "model": item.name,
            "requests": item.requests,
            "input_tokens": item.input_tokens,
            "cached_input_tokens": item.cached_input_tokens,
            "cache_miss_tokens": max(item.input_tokens - item.cached_input_tokens, 0),
            "output_tokens": item.output_tokens,
            "cost_cny": str(item.cost),
            "unpriced_requests": item.unpriced_requests,
        }

    return {
        "home": str(home),
        "timezone": TIMEZONE.key,
        "start": report.start.isoformat(),
        "end": report.end.isoformat(),
        "today": {
            "date": report.today.day.isoformat(),
            "requests": report.today.requests,
            "input_tokens": report.today.input_tokens,
            "cached_input_tokens": report.today.cached_input_tokens,
            "output_tokens": report.today.output_tokens,
            "cost_cny": str(report.today.cost),
        },
        "totals": {
            "requests": report.requests,
            "input_tokens": report.input_tokens,
            "cached_input_tokens": report.cached_input_tokens,
            "cache_miss_tokens": max(report.input_tokens - report.cached_input_tokens, 0),
            "output_tokens": report.output_tokens,
            "cost_cny": str(report.cost),
            "unpriced_requests": report.unpriced_requests,
        },
        "models": [model_item(item) for item in report.models],
        "days": [
            {
                "date": day.day.isoformat(),
                "requests": day.requests,
                "input_tokens": day.input_tokens,
                "cached_input_tokens": day.cached_input_tokens,
                "output_tokens": day.output_tokens,
                "cost_cny": str(day.cost),
            }
            for day in report.days
        ],
        "pricing_source": PRICING_URL,
    }


def _positive_integer(value: str, label: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{label} must be an integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError(f"{label} must be at least 1")
    return number


def _positive_days(value: str) -> int:
    return _positive_integer(value, "days")


def _positive_hours(value: str) -> int:
    return _positive_integer(value, "hours")


def _positive_minutes(value: str) -> int:
    return _positive_integer(value, "minutes")


def _window_boundary(value: str, *, is_end: bool) -> datetime:
    text = value.strip()
    try:
        day = date.fromisoformat(text)
    except ValueError:
        try:
            moment = datetime.fromisoformat(text[:-1] + "+00:00"
                                            if text.endswith("Z") else text)
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                "window time must be YYYY-MM-DD or an ISO date-time") from error
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=TIMEZONE)
        return moment.astimezone(timezone.utc)
    moment = datetime.combine(day, time.min, tzinfo=TIMEZONE)
    if is_end:
        moment += timedelta(days=1)
    return moment.astimezone(timezone.utc)


def _window_start(value: str) -> datetime:
    return _window_boundary(value, is_end=False)


def _window_end(value: str) -> datetime:
    return _window_boundary(value, is_end=True)


def _looks_like_home(path: Path) -> bool:
    return (path / "sessions").is_dir() or (path / "config.toml").is_file()


def _default_home() -> Path:
    directory = Path(__file__).resolve().parent
    if _looks_like_home(directory):
        return directory
    project_home = directory.parent / ".codex"
    if _looks_like_home(project_home):
        return project_home
    return directory


def run(args: list[str], *, home: Path | None = None, out: TextIO | None = None,
        now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codex_usage.py",
        description="Show token usage and estimated DeepSeek cost from this "
                    "selected Codex home.",
    )
    parser.add_argument("--days", type=_positive_days,
                        help="report calendar-day window; default 14")
    parser.add_argument("--hours", type=_positive_hours,
                        help="report a rolling window ending now, in hours")
    parser.add_argument("--minutes", type=_positive_minutes,
                        help="report a rolling window ending now, in minutes")
    parser.add_argument(
        "--start", type=_window_start,
        help="window start in Asia/Shanghai; accepts date or ISO date-time")
    parser.add_argument(
        "--end", type=_window_end,
        help="window end in Asia/Shanghai; a date-only value includes that day")
    parser.add_argument("--all", action="store_true",
                        help="summarize all indexed rollout history")
    parser.add_argument("--home", type=Path,
                        help="Codex home to read; defaults to the launcher "
                             "home or this script's directory")
    parser.add_argument("--json", action="store_true",
                        help="print machine-readable JSON")
    parser.add_argument("--no-chart", action="store_true",
                        help="omit the daily terminal chart")
    options = parser.parse_args(args)
    windows = [name for name, value in (
        ("--days", options.days),
        ("--hours", options.hours),
        ("--minutes", options.minutes),
    ) if value is not None]
    if len(windows) > 1:
        parser.error(f"{', '.join(windows)} are mutually exclusive")
    if options.all and windows:
        parser.error(f"--all and {windows[0]} are mutually exclusive")
    if (options.start is None) != (options.end is None):
        parser.error("--start and --end must be used together")
    explicit_window = options.start is not None
    if explicit_window and (options.all or windows):
        parser.error("--start/--end cannot be combined with another window option")
    if explicit_window and options.end <= options.start:
        parser.error("--end must be after --start")
    output = out or sys.stdout
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    report_now = current
    target_home = options.home or home
    if target_home is None:
        target_home = _default_home()
    target_home = Path(target_home)
    if options.all:
        start = datetime(1970, 1, 1, tzinfo=timezone.utc)
        end = current
    elif explicit_window:
        start, end = options.start, options.end
    elif options.hours is not None:
        start = end = current
        start -= timedelta(hours=options.hours)
    elif options.minutes is not None:
        start = end = current
        start -= timedelta(minutes=options.minutes)
    else:
        days = options.days or 14
        start = _local_midnight(current) - timedelta(days=days - 1)
        start = start.astimezone(timezone.utc)
        end = current
    records = collect_records(target_home, start, end)
    if options.all and records:
        start = min(record.timestamp for record in records)
    elif options.all:
        start = end
    report = build_report(records, start, end, report_now)
    if options.json:
        json.dump(_json_report(report, target_home), output, indent=2,
                  ensure_ascii=False)
        print(file=output)
    elif not records:
        print(f"No DeepSeek usage found in this range ({target_home}).", file=output)
    else:
        render_report(report, chart=not options.no_chart, out=output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\ncodex_usage: cancelled", file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError) as error:
        print(f"codex_usage: {error}", file=sys.stderr)
        raise SystemExit(1)
