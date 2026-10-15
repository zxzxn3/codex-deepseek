# codex-deepseek

An unofficial launcher for using Codex CLI with your own DeepSeek API key.
Not affiliated with or endorsed by OpenAI or DeepSeek. Codex CLI is installed
separately; requests go directly to the configured DeepSeek API endpoint.

Launch Codex with DeepSeek in an independent `CODEX_HOME`. Requirements:
Linux, Codex CLI 0.158.0+, Python 3.11+, `secret-tool`, an unlocked desktop
Secret Service keyring, and a DeepSeek API key. The installer and offline
integration tests have been verified with Codex CLI 0.162.1; use the probes
after changing the client or provider.

## Files

```text
~/.local/share/codex-deepseek/          launcher, installer, models, probes and documentation
~/.local/share/codex-deepseek/.codex/ private CODEX_HOME (default)
~/.local/bin/codex-deepseek          symlink to launcher.py
```

`launcher.py` resolves both code and its private `.codex/` relative to itself.
Keep API keys, session databases, transcripts, and configuration backups private.
The model catalog comes from DeepSeek’s integration guide; see
[model catalog provenance](MODEL-CATALOG.md) for its source and redistribution status.

## Install

Clone this repository and run the installer:

```sh
git clone https://github.com/zxzxn3/codex-deepseek.git
cd codex-deepseek
python3 install.py
```

The default destination is `~/.local/share/codex-deepseek/`. To choose another
directory and optional components:

```sh
python3 install.py --dir ~/apps/codex-deepseek --defaults \
  --with-messaging-skill --with-bell-hook
```

All four options are optional. `--defaults` skips configuration-source selection;
it does not skip the final confirmation. The skill and bell hook are not enabled
unless requested with their flags.

The installer opens with a project-independence notice and a `Continue? [y/N]`
question. Continuing does not approve file changes. Dependency diagnostics may
appear before the notice. A separate confirmation follows the installation plan.
Colors follow the terminal palette and are disabled with `NO_COLOR`, `TERM=dumb`
or redirected output.

Installation proceeds in this order:

1. Check dependencies, project files, destination paths and the command link.
   The destination `.codex/` must be absent or empty. A nonempty home is refused,
   even with `--defaults`. Different project files and unrelated command links
   are not overwritten. This is a fresh installer, not an updater or migration tool.
2. Without `--defaults`, if `~/.codex/config.toml` exists, ask whether to use
   Codex defaults (Enter) or copy that file. Both choices apply the required
   DeepSeek model, provider, model catalog and keyring authentication settings.
   If no ordinary configuration exists, use defaults. Non-interactive callers
   must use `--defaults` when an ordinary configuration is present.
3. Show a numbered operation plan, destination, configuration source and command
   link. Nothing is written before `Proceed with installation? [y/N]`. Enter or
   EOF cancels; explicit `y` or `yes` proceeds.
4. Install project files into the destination, create its private `.codex/`, write
   `config.toml`, and create `~/.local/bin/codex-deepseek`. Install only the selected
   optional components, then verify files, configuration, permissions and links.
   A step is marked `done` only after its action succeeds. The final two numbered
   steps are manual: store your API key, then start Codex.

The default template adds only DeepSeek connection settings. Approval policy,
sandboxing, reasoning preferences and other behavior use Codex's defaults.
Copying ordinary configuration reads that file without modifying it; it does not
copy credentials, sessions, referenced files or hook approvals. Comments and
formatting are not copied. Paths are not rewritten, and the active `profile`
selection is omitted because separate profile files are not migrated.

After a successful installation, store or update your key:

```sh
codex-deepseek setup-key
```

The command requires an interactive terminal and refuses input if it cannot
hide the key. It saves the key in the desktop keyring under
`application=codex-deepseek provider=deepseek`, and reads it back to verify it.
The key is not written into `config.toml`. Installation verification does not
make a paid API request or establish model connectivity.

If an execution or verification step fails, the error identifies the step.
Earlier steps may have completed; there is no automatic whole-install rollback.
An inherited `CODEX_HOME` does not change the installation destination.

## Optional components

These commands work after installation, independently of the configuration-source
choice. They show their plan and require confirmation before writing:

```sh
codex-deepseek --install-messaging-skill
codex-deepseek --install-bell-hook
```

The target defaults to the project directory containing the running launcher,
including custom installations. Use `--dir /path/to/codex-deepseek` to select a
different installed project. An existing, valid DeepSeek home is required.

- **Session messaging skill:** teaches agents how to address tasks and replies
  across local Codex sessions. It links the bundled
  [skill](skills/codex-session-messaging/SKILL.md) into the selected home without
  rewriting configuration or starting a service.
- **Bell hook:** plays sounds when submitting a prompt, finishing a response or
  requesting approval. Requires `paplay`; the sounds are bundled in
  [`assets/bell/`](assets/bell/README.md), and the configuration is defined in
  [`hooks/bell/`](hooks/bell/README.md). Replace `prompt.oga` or `complete.oga`
  there to customize playback without reinstalling; missing sound files are
  silently skipped. Missing bell handlers are
  appended without resetting other settings. The previous
  configuration is backed up as `config.toml.bak.N`. Review and trust the hooks
  through Codex `/hooks` to activate them; installation never grants approval.

Repeated installation of an already-present component makes no changes.
Unrelated skill conflicts are refused. Optional components do not copy or reset
`AGENTS.md`, memories, credentials or sessions.

## Use

The displayed commands use the installed command link. Put `~/.local/bin` first
on PATH, or use the full launcher path if another command shadows that link:

```sh
codex                                      # ordinary Codex home
codex-deepseek                             # DeepSeek Flash
codex-deepseek -m deepseek-v4-pro
codex-deepseek -c 'model_reasoning_effort="max"'
codex-deepseek resume --all
```

`setup-key`, `--install-messaging-skill` and `--install-bell-hook`
are launcher commands; other arguments pass to Codex. The child process uses the project's `.codex/`. Launch separate
sessions for ChatGPT and DeepSeek. For model-capable commands the launcher
passes this home's configured model through `-c model=...`. This selects the
configured default on direct TUI startup. In Codex CLI 0.162.1 that root-level
option does not reliably override the model for subcommands such as `exec`;
use `codex-deepseek -m deepseek-flash exec ...` to select it explicitly.
Project configuration can still override reasoning effort. Local management
commands are passed through unchanged.

Local management commands (`queue`, `agents`, `archive`, `delete`, `unarchive`,
`migrate-rollouts`, `completion`, `features`, `apply`, `sandbox`, `logout`) and
help/version skip the launcher's keyring preflight. Queue acceptance still does
not guarantee the receiving session can authenticate when it starts work.
Normal sessions, `exec`, `review`, `resume`, `fork` and service/unknown commands
retain the early key check. Ambiguous command syntax retains the key check.

The provider uses native Responses streaming. Configuration and supported
models are defined in `launcher.py` and `models.json`; probes and tests cover
compatibility. See [probes/README.md](probes/README.md) for commands, including
opt-in paid probes.

## Optional tools

Session messaging is optional. Its addressing and reply workflow is documented
in the bundled [skill](skills/codex-session-messaging/SKILL.md).

See [probes/README.md](probes/README.md) for optional paid compatibility probes.
These are not required for normal use.

## Backup and restore

The private `.codex/` directory contains configuration and session data. Stop
sessions and the background server before copying it, or use a SQLite-aware
live snapshot. Back up the keyring and any external symlink targets separately.

Restore at the same absolute path when possible. Moving the project changes
`CODEX_HOME` and may require updating catalog, database, and external paths.
`install.py` does not migrate history and refuses nonempty homes. Do not use it to
restore or reset an existing environment.
Restore the keyring separately or rerun `codex-deepseek setup-key`.

## References

- [DeepSeek Codex integration](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/codex/)
- [DeepSeek Responses compatibility](https://api-docs.deepseek.com/guides/responses_api)

Offline tests: [`tests/`](tests/README.md). Optional live probes: [`probes/`](probes/README.md).
