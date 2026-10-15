# Tests

Run from the project root:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

- `test_launcher.py`: credential handling and command/keyring preflight.
- `test_install.py`: planning without writes, confirmation/cancellation, custom
  destinations, both confirmation gates, empty-home requirements, configuration copying, component
  installation, conflict handling, bell-hook preservation and TOML value round trips.
- `test_integration.py`: native Responses tools and reasoning against a local SSE server.

Tests use disposable data, without saved credentials or paid API requests.
The integration test requires the installed Codex binary.
Metered live probes remain in [`../probes/`](../probes/README.md).
