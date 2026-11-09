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

On 2026-11-09, the four model identity sentences in the two
`instructions_template` and two `base_instructions` fields were changed from
"based on GPT-5" to "based on DeepSeek" so the prompt identifies the configured
provider. No model slugs, capabilities, context limits, or provider settings
were changed.

Local file SHA-256 at verification:

```text
4af4f46515987e75cdc2147ca00426a3e81b3ba9a89add19db44bcd37ae98689
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
