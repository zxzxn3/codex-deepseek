# Model catalog provenance

`models.json` contains the two-model catalog published in DeepSeek’s official
[Codex integration guide](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/codex/).
The guide includes the complete JSON and links to its
[setup script](https://cdn.deepseek.com/api-docs/codex-deepseek-setup.sh).

## Verification

On 2026-10-15, the local JSON was parsed and compared with the complete JSON
code block in the official guide. Both model objects matched field for field:
`deepseek-flash` and `deepseek-v4-pro`. This includes `base_instructions` and
`model_messages`, not just the model names and context limits.

Local file SHA-256 at verification:

```text
bce20f679495809f4fa6e48672b6dcbab84b6adff5251890b6e6a21eddb9c12f
```

The setup script identifies itself as version 1.4.0. No script was executed;
verification read the official guide and script only. Remote content can change,
so these results describe the content retrieved on that date.

## Redistribution status

The inspected guide and setup-script header do not supply an explicit
redistribution license for this catalog. A matching public example establishes
provenance, not permission to redistribute it under an arbitrary project license.
No ownership or independent authorship of this catalog is claimed.

Before publishing a repository containing the catalog, resolve its redistribution
terms. An alternative is to have users obtain it from the official source during
installation, but this project has not implemented such a download workflow.
The existing catalog and runtime behavior have not been changed by this review.
