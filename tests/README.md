# Tests

Run from the project root:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

- `test_launcher.py`: credential handling, command/keyring preflight and installation
  routing, including help from a clean checkout without bytecode or home writes.
- `test_install.py`: planning without writes, confirmation/cancellation, custom
  destinations, both confirmation gates, empty-home requirements, configuration copying, component
  installation, conflict handling, bell-hook preservation and TOML value round trips.
  Dry-run cases check zero writes, both confirmation gates, cancellation, reported destination
  conflicts, and unchanged component configuration and links.
  Update cases cover preservation of the private home and sound choices, backups of
  local edits, idempotence, dry-run/cancellation, redirected paths and confirmation-time changes.
- `test_integration.py`: native Responses tools and reasoning against a local SSE server.

Tests use disposable data, without saved credentials or paid API requests.
The integration test requires the installed Codex binary.
Metered live probes remain in [`../probes/`](../probes/README.md).
