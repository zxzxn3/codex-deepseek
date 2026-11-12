---
name: deepseek-search
description: Run DeepSeek-backed web searches when current or external information is needed.
---

# DeepSeek search

Use the installed `deepseek-search` command for web search through DeepSeek's
Search API. Keep searches focused on the user's question.

```sh
deepseek-search "query"
deepseek-search -n 5 "query"
deepseek-search --need-content "query"
```

Use the normal text output to answer and cite the returned URLs. Use `--json`
when structured processing is useful, and `--need-content` only when result
summaries are insufficient.

Do not invent results or claim pages were read when the command did not return
their content. Search requests are billed by DeepSeek, so do not broaden or
repeat searches without a reason.

If the command is unavailable, report the installation problem. If credential
lookup fails, ask the user to run `codex-deepseek setup-key` or unlock the
desktop keyring.
