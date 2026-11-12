# deepseek-search

An independent command for DeepSeek's native Search API. It is co-located with
`codex-deepseek`, but does not import the launcher or its modules.

The command reads `DEEPSEEK_API_KEY` when set. Otherwise it reads the Secret
Service credential stored by `codex-deepseek setup-key`:

```text
application=codex-deepseek
provider=deepseek
```

## Usage

```sh
deepseek-search "DeepSeek V4 release"
deepseek-search -n 5 "CachyOS proxy"
deepseek-search --json --need-content "some documentation"
```

`--need-content` includes full page Markdown when the API returns it. Search
requests are billed by DeepSeek per successful request.

## Tests

Run from this directory:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```
