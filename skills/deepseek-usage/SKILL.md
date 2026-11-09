---
name: deepseek-usage
description: Report estimated DeepSeek API usage and cost from a local codex-deepseek installation. Use when the user asks how much DeepSeek cost recently, token usage, request count, daily spend, or "最近 DeepSeek 花了多少钱".
---

# DeepSeek usage

Use the bundled wrapper. It resolves `usage_tool/codex_usage.py` from the
installation that contains this skill, so custom install directories work.

Do not depend on a personal command alias, and do not use
`codex-deepseek usage`; that is not the reporter.

## Commands

```sh
python3 scripts/usage.py
python3 scripts/usage.py --days 7 --no-chart
python3 scripts/usage.py --all
python3 scripts/usage.py --json
python3 scripts/usage.py --home /path/to/codex-home
```

The default window is 14 calendar days. `--days N` changes the window,
`--all` covers all indexed history, and `--json` is for machine-readable
output. `--home` selects another Codex home.

## Reporting

- Report the period, estimated CNY cost, input/output/cache tokens, request
  count, and model split when useful.
- Mention the cache hit rate when it explains the cost.
- State that this is a local estimate from recorded usage. Official billing at
  `platform.deepseek.com` is authoritative.
- Search/Fetch and other separately billed usage are not included.
- If the wrapper cannot find the tool or reports a schema/read error, report
  the installation problem and do not invent numbers.
