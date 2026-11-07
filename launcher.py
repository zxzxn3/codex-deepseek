#!/usr/bin/env python3
"""An isolated Codex CLI home for DeepSeek; never changes ~/.codex."""
from __future__ import annotations

import getpass
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import warnings

HERE = Path(__file__).resolve().parent
DATA = HERE / ".codex"
# Local imports must not write bytecode before an installation is confirmed.
sys.dont_write_bytecode = True

from libs._config import KEY_ATTRIBUTES, MODELS as MODELS, catalog as catalog, configuration as configuration


VALUE_OPTIONS = {'-c', '--config', '--enable', '--disable', '-m', '--model', '-p', '--profile',
                 '-s', '--sandbox', '-C', '--cd', '--add-dir', '-a', '--ask-for-approval',
                 '--local-provider', '--remote', '--remote-auth-token-env'}


def save_key() -> None:
    if not sys.stdin.isatty():
        raise ValueError("Run codex-deepseek setup-key in an interactive terminal")
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            key = getpass.getpass("DeepSeek API key (hidden): ").strip()
        except (getpass.GetPassWarning, EOFError) as error:
            raise ValueError("Cannot read a hidden key; use an interactive terminal") from error
    if not key or any(c.isspace() for c in key):
        raise ValueError("Empty key or whitespace in key")
    subprocess.run(["secret-tool", "store", "--label=Codex DeepSeek API key",
                    *KEY_ATTRIBUTES], input=key, text=True, capture_output=True,
                   check=True, timeout=60)
    try:
        stored = read_key()
    except KeyringUnavailable as error:
        raise ValueError(f"Keyring verification failed: {error}") from None
    if stored != key:
        raise ValueError("Keyring verification failed: the keyring returned a different secret")
    print("Saved credential to the desktop Secret Service keyring")


class KeyringUnavailable(ValueError):
    """An unavailable desktop credential; exit 78 is reserved for this preflight."""


def read_key(*, timeout=60) -> str:
    try:
        result = subprocess.run(["secret-tool", "lookup", *KEY_ATTRIBUTES],
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise KeyringUnavailable("Desktop keyring lookup timed out; unlock your keyring and retry") from None
    key = result.stdout.strip()
    if result.returncode or not key or any(c.isspace() for c in key):
        raise KeyringUnavailable("Unlock your keyring or run codex-deepseek setup-key")
    return key


def check_key(*, timeout=60) -> None:
    read_key(timeout=timeout)


def _walk(args: list[str]):
    """Yield (index, option, value) per argument, skipping consumed option values.

    A recognized value option yields its attached value (possibly ''); every
    other token yields value=None, and '--' terminates the scan. requires_key
    and explicit_model must agree on this tokenization; both consume it.
    """
    index = 0
    while index < len(args):
        token = args[index]
        if token == '--':
            yield index, token, None
            return
        if token in VALUE_OPTIONS:
            yield index, token, args[index + 1] if index + 1 < len(args) else ''
            index += 2
            continue
        option, separator, value = token.partition('=')
        if separator and option in VALUE_OPTIONS:
            yield index, option, value
        elif len(token) > 2 and token[:2] in VALUE_OPTIONS and not token.startswith('--'):
            yield index, token[:2], token[2:]  # e.g. -cmodel=x or -C/path
        else:
            yield index, token, None
        index += 1


def requires_key(args: list[str]) -> bool:
    """Recognise a conservative set of local commands, skipping global option values."""
    local = {'help', 'queue', 'agents', 'archive', 'delete', 'unarchive',
             'migrate-rollouts', 'completion', 'features', 'apply', 'a', 'sandbox', 'logout'}
    flags = {'--strict-config', '--oss', '--approve-for-me', '--worktree', '--search',
             '--no-alt-screen', '--no-daemon', '--dangerously-bypass-approvals-and-sandbox',
             '--dangerously-bypass-hook-trust'}
    commands = local | {'exec', 'e', 'review', 'resume', 'fork', 'app-server', 'exec-server',
                        'remote-control', 'cloud', 'update', 'mcp', 'plugin', 'doctor',
                        'debug', 'login'}
    for index, option, value in _walk(args):
        if value is not None:
            continue  # an option's consumed value is never a command
        if option == '--':
            return True  # everything after -- is a literal prompt or argument
        if option in ('--help', '-h', '--version', '-V'):
            return False
        if option in flags:
            continue
        if option in local:
            return False
        if option == 'app-server' and args[index + 1:index + 2] == ['proxy']:
            return False  # Raw local socket forwarding never invokes the model provider.
        if option in commands and args[index + 1:] in (['--help'], ['-h']):
            return False
        return True  # prompt, unknown option, or a model-capable command
    return True


def explicit_model(args: list[str]) -> bool:
    """Respect model options without mistaking other options' values for flags."""
    for _index, option, value in _walk(args):
        if value is None:
            continue
        if option in ('-m', '--model'):
            return True
        if option in ('-c', '--config') and value.partition('=')[0].strip().strip('"') == 'model':
            return True
    return False


def main(args: list[str]) -> int:
    if args and args[0] in ('install', '--install-messaging-skill', '--install-bell-hook', '--dir', '--dry-run'):
        from libs import _install as installer
        return installer.run(args, source=HERE)
    if args == ["setup-key"]:
        save_key()
        return 0
    if not (DATA / "config.toml").is_file():
        raise ValueError("Run python3 launcher.py install in the codex-deepseek project first")
    forwarded = args
    if requires_key(args):
        config = tomllib.loads((DATA / 'config.toml').read_text(encoding='utf-8'))
        model = config.get('model')
        if model is not None:
            if not isinstance(model, str) or not model.strip():
                raise ValueError('The DeepSeek home must configure a nonempty model name')
            # Generic -c overrides force an embedded server in Codex 0.162.1.
            # --model selects the default while allowing the shared daemon.
            if not explicit_model(args):
                forwarded = ['--model', model, *args]
        if args[-3:] == ['app-server', 'daemon', 'start']:
            check_key(timeout=15)  # A background service cannot wait indefinitely for desktop input.
        else:
            check_key()
    env = os.environ.copy()
    # Intended CODEX_HOME override: isolate auth, daemon, history and model catalog.
    env["CODEX_HOME"] = str(DATA)
    for name in ("CODEX_THREAD_ID", "CODEX_SESSION_ID"):
        env.pop(name, None)
    os.execvpe("codex", ["codex", *forwarded], env)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\ncodex-deepseek: cancelled", file=sys.stderr)
        raise SystemExit(130)
    except KeyringUnavailable as error:
        print(f"codex-deepseek: {error}", file=sys.stderr)
        raise SystemExit(getattr(os, 'EX_CONFIG', 78))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"codex-deepseek: {error}", file=sys.stderr)
        raise SystemExit(1)
