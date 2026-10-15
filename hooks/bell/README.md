# Bell hook

`hooks.toml` is a Codex hook configuration template. It defines the events,
commands, timeouts and asynchronous behavior; the installer does not duplicate
those event definitions in Python.

The installer reads the TOML, substitutes `{player}` with the discovered `paplay`
executable and `{assets}` with the installed project's absolute `assets/bell`
path, then appends missing handlers to the selected home's configuration.
Paths are shell-quoted, including installations whose paths contain spaces.
Each command checks that its sound file exists before playing. Missing files
produce no output and return success; they do not prevent hook installation.

The hook is opt-in: `python3 install.py --with-bell-hook`, or
`codex-deepseek --install-bell-hook` for an existing installation. Review and
trust the installed handlers in Codex `/hooks` before expecting playback.

For custom sounds, replace the two files described in
[assets/bell](../../assets/bell/README.md). The template is used at installation;
changing events or commands in it does not automatically rewrite installed hooks.
