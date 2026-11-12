# codex-deepseek

An unofficial launcher for using Codex CLI with your own DeepSeek API key.
Not affiliated with or endorsed by OpenAI or DeepSeek. Codex CLI is installed
separately; requests go directly to the configured DeepSeek API endpoint.

DeepSeek's [official setup](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/)
configures your existing Codex home. This launcher creates a separate DeepSeek
home so ordinary Codex and DeepSeek can coexist, and stores your API key in the
desktop keyring instead of the configuration file.

Launch Codex with DeepSeek in an independent `CODEX_HOME`. Requirements:
Linux, Codex CLI 0.158.0+, Python 3.11+, `secret-tool`, an unlocked desktop
Secret Service keyring, and a DeepSeek API key.

Used daily on Linux with DeepSeek, desktop keyring authentication, and the bell
hook. Installation, configuration, and launcher behavior have been tested with
Codex CLI 0.162.1.

## Files

```text
~/.local/share/codex-deepseek/          launcher, installer, models, probes and documentation
~/.local/share/codex-deepseek/.codex/ private CODEX_HOME (default)
~/.local/share/codex-deepseek/deepseek-search/ independent search project
~/.local/bin/codex-deepseek          symlink to launcher.py
~/.local/bin/deepseek-search         symlink to deepseek-search/deepseek_search.py
```

`launcher.py` is the command entry point; `libs/_install.py` and `libs/_config.py` are internal modules.
It resolves both code and its private `.codex/` relative to itself.
Keep API keys, session databases, transcripts, and configuration backups private.
The model catalog comes from DeepSeek’s integration guide; see
[model catalog provenance](MODEL-CATALOG.md) for its source and redistribution status.

## Install

On Ubuntu GNOME, install the system dependencies first. GNOME supplies the
unlocked desktop keyring; `libsecret-tools` provides `secret-tool`:

```sh
sudo apt update
sudo apt install -y git python3 libsecret-tools
```

Codex CLI must be installed separately and be version 0.158.0 or newer. On
Ubuntu 22.04, use Python 3.11 or newer if the default `python3` is older.

### One-line install

For a source checkout, run:

```sh
git clone https://github.com/zxzxn3/codex-deepseek.git
cd codex-deepseek
python3 launcher.py install
```

Or, without keeping the clone in the current directory:

```sh
(tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT; git clone --depth 1 https://github.com/zxzxn3/codex-deepseek.git "$tmp/codex-deepseek" && python3 "$tmp/codex-deepseek/launcher.py" install)
```

If Ubuntu 22.04's `python3` is still 3.10, install and invoke a Python 3.11+
interpreter by replacing the final `python3` with `python3.11`; upgrading to
Ubuntu 24.04 also provides Python 3.12.

The default destination is `~/.local/share/codex-deepseek/`. To choose another
directory and optional components:

```sh
python3 launcher.py install --dir ~/apps/codex-deepseek --defaults \
  --with-messaging-skill --with-usage-skill --with-bell-hook
```

These options are optional. `--defaults` skips configuration-source selection;
it does not skip the final confirmation. Skills and the bell hook are not
enabled unless requested with their flags.

Rehearse the interactive installation without changing files:

```sh
python3 launcher.py install --dry-run
```

Use the same destination and component flags as a real installation. Existing
destination or command-link conflicts are reported but do not stop the preview;
a real installation still refuses them. Dependencies and bundled files are
checked. Configuration-source selection and both confirmation questions remain
interactive; `--defaults` still skips only configuration-source selection. After
confirmation, automatic steps are marked `simulated`, and the usual next steps
are displayed. File changes and installation verification are skipped.

The installer opens with a project-independence notice and a `Continue? [y/N]`
question. Continuing does not approve file changes. Dependency diagnostics may
appear before the notice. A separate confirmation follows the installation plan.
Colors follow the terminal palette and are disabled with `NO_COLOR`, `TERM=dumb`
or redirected output.

Installation proceeds in this order:

1. Check dependencies, project files, destination paths and the command link.
   The destination `.codex/` must be absent or empty. A nonempty home is refused,
   even with `--defaults`. Different project files and unrelated command links
   are not overwritten. Use `--update` below for an existing installation.
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
The key is not written into `config.toml`. Local `app-server proxy` forwarding skips the launcher keyring preflight; daemon startup still requires credentials. Background `app-server daemon start` bounds this preflight to 15 seconds and exits 78 when the keyring is unavailable, so a gateway can report the cause and retry after desktop unlock. Other model-capable commands retain their 60-second preflight. Installation verification does not
make a paid API request or establish model connectivity.

If an execution or verification step fails, the error identifies the step.
Earlier steps may have completed; there is no automatic whole-install rollback.
An inherited `CODEX_HOME` does not change the installation destination.

## Update

Download or pull the new version into a separate checkout, then run its installer:

```sh
cd /path/to/new/codex-deepseek
python3 launcher.py install --update
# Custom installation, or an interactive preview:
python3 launcher.py install --update --dir ~/apps/codex-deepseek --dry-run
```

The installer lists changed and new project files, then asks for confirmation.
Replaced files, including local edits, are backed up under the installation's
`.update-backups/update-*/` directory. Review the list before approving; local
code edits are replaced, not merged. Files removed from the new version are not
automatically deleted.

Your entire `.codex/`, configuration, credentials, sessions, command link and
existing sound choices stay unchanged. Deleted sound files stay deleted. Optional
components are not enabled or reconfigured; an already linked messaging skill
uses the updated bundled files. Restart sessions after updating. If hook commands
change in a future release, follow that release's instructions separately.

Updates use the selected checkout and do not fetch releases or update Codex CLI.
The checkout must differ from the installation directory. On failure, earlier
files may already have been replaced; the error gives the backup location for
manual recovery. There is no automatic rollback.

## Optional components

These commands work after installation, independently of the configuration-source
choice. They show their plan and require confirmation before writing:

```sh
codex-deepseek --install-messaging-skill
codex-deepseek --install-usage-skill
codex-deepseek --install-bell-hook
```

Add `--dry-run` to any command to preview its plan without changing files.

The target defaults to the project directory containing the running launcher,
including custom installations. Use `--dir /path/to/codex-deepseek` to select a
different installed project. An existing, valid DeepSeek home is required.

- **Session messaging skill:** teaches agents how to address tasks and replies
  across local Codex sessions. It links the bundled
  [skill](skills/codex-session-messaging/SKILL.md) into the selected home without
  rewriting configuration or starting a service.
- **DeepSeek usage skill:** teaches agents to run the bundled usage reporter and
  report estimated cost without depending on a machine-specific command alias.
  It links the [skill](skills/deepseek-usage/SKILL.md) into the selected home.
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
codex-deepseek agents
codex-deepseek resume --all
```

`install`, `setup-key`, `--install-messaging-skill`, `--install-usage-skill` and
`--install-bell-hook`
are launcher commands; other arguments pass to Codex. The child process uses the project's `.codex/`. Launch separate
sessions for ChatGPT and DeepSeek. For model-capable commands the launcher
passes this home's configured model through `--model`, unless you already supplied
an explicit model option. It also passes the configured `model_reasoning_effort`;
otherwise an enclosing project config, including the ordinary `~/.codex/config.toml`
when started from the home directory, can replace it with a different effort.
`resume`, `agents`, and `fork` are excluded from both defaults so Codex restores
the model and reasoning effort saved with the selected session. An explicit model
or effort option still overrides launch defaults. Local management commands are
passed through unchanged.

Start the command center with `codex-deepseek agents` when switching to saved
sessions. Opening it from an already launched session retains that session's
explicit model settings, as Codex 0.167 treats launch values as overrides.

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

Interactive TUI launches avoid generic `-c` overrides so Codex can attach to the
managed daemon for this `CODEX_HOME`. The DeepSeek home supplies its model and
reasoning effort as user configuration; the ordinary Codex home does not repeat
the model's default reasoning effort as a project-layer override. Resumed
threads retain their saved model and effort. Non-interactive commands still
receive the configured effort override.

### Usage and estimated cost

`usage_tool/codex_usage.py` is a standalone accessory, not a `codex-deepseek`
subcommand. It reads the selected Codex home's
`sessions/**/rollout-*.jsonl` and `archived_sessions/**/rollout-*.jsonl`.
Copied sessions are counted once. The default installation example therefore
selects this project's private `.codex/`; it does not scan the ordinary
`~/.codex`. The tool uses the real `usage` object recorded for each response
and estimates cost from DeepSeek's current public prices:

```sh
python3 ~/.local/share/codex-deepseek/usage_tool/codex_usage.py
python3 ~/.local/share/codex-deepseek/usage_tool/codex_usage.py --days 30
python3 ~/.local/share/codex-deepseek/usage_tool/codex_usage.py --hours 2
python3 ~/.local/share/codex-deepseek/usage_tool/codex_usage.py --minutes 90
python3 ~/.local/share/codex-deepseek/usage_tool/codex_usage.py \
  --start 2026-11-08 --end 2026-11-09
python3 ~/.local/share/codex-deepseek/usage_tool/codex_usage.py --all
python3 ~/.local/share/codex-deepseek/usage_tool/codex_usage.py --json
python3 ~/.local/share/codex-deepseek/usage_tool/codex_usage.py --no-chart
```

To let Codex agents use this workflow directly, install the optional component:

```sh
codex-deepseek --install-usage-skill
```

The first run builds a local incremental index at
`.codex/usage/usage.sqlite3`; later runs read only appended rollout data. The
cache contains token counters and timestamps, not message text. Input cache
hits, cache misses, output tokens, peak/off-peak periods, and model-specific
pricing are accounted for separately.

`--days` uses calendar-day boundaries and defaults to 14 days. `--hours` and
`--minutes` select exact rolling windows ending at the current time; the three
window options are mutually exclusive. `--start` and `--end` select an explicit
past or present window in the `Asia/Shanghai` timezone. Both options are
required together and accept either `YYYY-MM-DD` or an ISO date-time. A
date-only end includes the whole end day.

The result is an estimate. DeepSeek's platform remains authoritative for
billing, and separately billed Search/Fetch usage is not included. Pricing and
peak-period rules are based on the official
[DeepSeek pricing page](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/).

The reporter is one self-contained standard-library file. Copy it into another
Codex home and run it there, or pass a home explicitly:

```sh
cp /path/to/codex-deepseek/usage_tool/codex_usage.py /path/to/other-home/
python3 /path/to/other-home/codex_usage.py
python3 /path/to/other-home/codex_usage.py --home /path/to/other-home
```

When run without `--home`, it first checks whether the script's directory is a
Codex home; for the bundled `usage_tool/` layout it then checks the sibling `.codex/`.
It has no dependency on the launcher or the `libs/` package.

### Web search

The co-located [`deepseek-search/`](deepseek-search/README.md) project is an
independent command. It reads the same keyring credential managed by
`codex-deepseek setup-key`, but does not load the launcher or its modules:

```sh
deepseek-search "DeepSeek V4 release"
deepseek-search -n 5 "CachyOS proxy"
deepseek-search --json --need-content "some documentation"
```

`--need-content` includes full page Markdown when the API returns it. Search
requests are billed by DeepSeek per successful request; see the
[Search API guide](https://api-docs.deepseek.com/zh-cn/guides/search.md).

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
`launcher.py install` does not migrate history and refuses nonempty homes. Do not use it to
restore or reset an existing environment.
Restore the keyring separately or rerun `codex-deepseek setup-key`.

## ASCII art

```text
                       __,.
                    -=~` ` ,,
                   $` __:^=~`~=^ __
                   `-= _}*=?^^==+_ ~_
                  _-+_=~ /`  ,` _`=_`#_
                  `+_^ .     ?+, < "$_/_.
                  _=[   /\   ] ___[ `_@*&_
                 _$?   @_*<? ' ~=~?  ~[_ `~=-.
              .=____$_ ^[~~   .  .[_// ~~^~`~~
               ````?@~=+@*..___.*?]` [ #&
                   $^. "+_=$@~_<"@[_&-_ =~ -_'#_[
             *^` _=,< #] "[$<$@=@$?{, _  "=_`  `]>
            _$`%=^~  _= ? `$ ?` '~\ \ $=__`~ -$_
        _=?_`    .   =_  ?_?,       ],`_/*>&-*`-{=_
      _ [}]~   -^    ,~  _~\>-------@_ "  `~>~  ^<%\
      [--~    ]*  $-/   *``_--.....-@^=._-=' ,  _"#/
      `~] ,#=  _=@_   _/%-{'        `$__/   _~_]^$"
          = ?%[_`~$\.=@=/_'           \?-_+['.@ `        =_
         <%{`  `_]=$=~_$ '             \?,`~ -_,       ,< `,
          "~=<" _*~  >"~"               -=^< _*"    _=~    [
              _<`  _{  = ,              ==  ?@.___  ^     #~
           ,==,   ,`   *," ,          _/ *   `\   ~~\   _*`
           ~- `=+$     _^ __~ =---== ` +=`\    #+_.._  /'
            `=.>  ?=+._^   `\===..>=? ^   _%-='_.^  _  @
                ?-.+_  ~==-..._____,[--==^~ _-=^  _*~ _\
                    ~!==.___  ````` ___.=-=^`~==?~   _~
                         !  ~%^~~^^~'@<_          _> `
                        $    /   ,   `  ~^^=====^~
                        ^   _    $   _
                         %  ?    $  _(
                         ~ =`>  *\. %
                         _` ~   #= =^
                         @_**[ ___ $[
                         ?$__@_$~~$@
                          ~===%@@@@~
                               ```
```

Adapted into ASCII with GPT, using Chafa for the character conversion.
See [artwork credits](assets/logo/README.md) for the original artists and license.

## References

- [DeepSeek Codex integration](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/codex/)
- [DeepSeek Responses compatibility](https://api-docs.deepseek.com/guides/responses_api)

Offline tests: [`tests/`](tests/README.md). Optional live probes: [`probes/`](probes/README.md).
