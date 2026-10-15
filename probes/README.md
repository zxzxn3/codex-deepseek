# Live probes

Run commands below from the project root. The runtime entry point remains
`launcher.py`; these tools are not part of ordinary startup. Installation,
credentials and backup procedures live in the [root README](../README.md).

Offline checks live in [`../tests/`](../tests/README.md).

## Opt-in live probes

These commands use the saved key and make metered DeepSeek API requests:

```sh
python3 probes/probe_api.py deepseek-flash
python3 probes/probe_api.py deepseek-v4-pro
python3 probes/probe_session.py deepseek-flash
python3 probes/probe_session.py deepseek-v4-pro
```

`probe_api.py` checks streaming reasoning, function/result round trips and
namespace calls. `probe_session.py` checks high/max reasoning, Flash image input,
compaction and recall using a separate stdio app-server. It does not restart the
existing daemon. Probes print structural results and usage, not credentials or
reasoning text. They do not establish benchmark parity or full-context coverage.
