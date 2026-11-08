#!/usr/bin/env python3
"""An isolated Codex CLI home for DeepSeek; never changes ~/.codex."""
from __future__ import annotations

import getpass
import json
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

from libs._config import (
    KEY_ATTRIBUTES, MODELS as MODELS, catalog as catalog,
    configuration as configuration, toml_config as toml_config,
)


VALUE_OPTIONS = {'-c', '--config', '--enable', '--disable', '-m', '--model', '-p', '--profile',
                 '-s', '--sandbox', '-C', '--cd', '--add-dir', '-a', '--ask-for-approval',
                 '--local-provider', '--remote', '--remote-auth-token-env'}
COMMAND_FLAGS = {'--strict-config', '--oss', '--approve-for-me', '--worktree', '--search',
                 '--no-alt-screen', '--no-daemon', '--dangerously-bypass-approvals-and-sandbox',
                 '--dangerously-bypass-hook-trust'}


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
    if read_key() != key:
        raise ValueError("Keyring verification failed")
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


def requires_key(args: list[str]) -> bool:
    """Recognise a conservative set of local commands, skipping global option values."""
    local = {'help', 'queue', 'agents', 'archive', 'delete', 'unarchive',
             'migrate-rollouts', 'completion', 'features', 'apply', 'a', 'sandbox', 'logout'}
    commands = local | {'exec', 'e', 'review', 'resume', 'fork', 'app-server', 'exec-server',
                        'remote-control', 'cloud', 'update', 'mcp', 'plugin', 'doctor',
                        'debug', 'login'}
    index = 0
    while index < len(args):
        token = args[index]
        if token == '--':
            return True
        if token in {'--help', '-h', '--version', '-V'}:
            return False
        if token in VALUE_OPTIONS:
            index += 2
            continue
        if token.partition('=')[0] in VALUE_OPTIONS and '=' in token:
            index += 1
            continue
        if len(token) > 2 and token[:2] in VALUE_OPTIONS and not token.startswith('--'):
            index += 1  # e.g. -cmodel=x or -C/path
            continue
        if token in COMMAND_FLAGS:
            index += 1
            continue
        if token in local:
            return False
        if token == 'app-server' and args[index + 1:index + 2] == ['proxy']:
            return False  # Raw local socket forwarding never invokes the model provider.
        if token in commands and args[index + 1:] in (['--help'], ['-h']):
            return False
        return True  # prompt, unknown option, or a model-capable command
    return True


def explicit_model(args: list[str]) -> bool:
    """Respect model options without mistaking other options' values for flags."""
    index = 0
    while index < len(args):
        token = args[index]
        if token == '--':
            break
        option, separator, value = token.partition('=')
        if token in VALUE_OPTIONS:
            option = token
            value = args[index + 1] if index + 1 < len(args) else ''
            index += 2
        elif separator and option in VALUE_OPTIONS:
            index += 1
        elif len(token) > 2 and token[:2] in VALUE_OPTIONS and not token.startswith('--'):
            option, value = token[:2], token[2:]
            index += 1
        else:
            index += 1
            continue
        if option in ('-m', '--model'):
            return True
        if option in ('-c', '--config') and value.partition('=')[0].strip().strip('"') == 'model':
            return True
    return False


def explicit_config_key(args: list[str], key: str) -> bool:
    """Return whether a `-c/--config key=value` override names `key`."""
    index = 0
    while index < len(args):
        token = args[index]
        if token == '--':
            break
        option, separator, value = token.partition('=')
        if token in VALUE_OPTIONS:
            option = token
            value = args[index + 1] if index + 1 < len(args) else ''
            index += 2
        elif separator and option in VALUE_OPTIONS:
            index += 1
        elif len(token) > 2 and token[:2] in VALUE_OPTIONS and not token.startswith('--'):
            option, value = token[:2], token[2:]
            index += 1
        else:
            index += 1
            continue
        if option in ('-c', '--config') and \
                value.partition('=')[0].strip().strip('"') == key:
            return True
    return False


def restore_requested(args: list[str]) -> bool:
    """Return whether the first command restores or selects an existing session."""
    index = 0
    while index < len(args):
        token = args[index]
        if token == '--':
            return False
        if token in VALUE_OPTIONS:
            index += 2
            continue
        if token.partition('=')[0] in VALUE_OPTIONS and '=' in token:
            index += 1
            continue
        if len(token) > 2 and token[:2] in VALUE_OPTIONS and not token.startswith('--'):
            index += 1
            continue
        if token in COMMAND_FLAGS:
            index += 1
            continue
        return token in {'resume', 'agents', 'fork'}
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
        config = tomllib.loads((DATA / 'config.toml').read_text())
        model = config.get('model')
        if model is not None:
            if not isinstance(model, str) or not model.strip():
                raise ValueError('The DeepSeek home must configure a nonempty model name')
            # A normal launch needs both values because Codex otherwise applies its
            # server defaults. Session restore/select commands omit both so Codex
            # restores the model and effort saved with the thread.
            if not explicit_model(args) and not restore_requested(args):
                forwarded = ['--model', model, *args]
                effort = config.get('model_reasoning_effort')
                if effort is not None:
                    if not isinstance(effort, str) or not effort.strip():
                        raise ValueError('model_reasoning_effort must be a nonempty string')
                    if not explicit_config_key(args, 'model_reasoning_effort'):
                        forwarded[:0] = ['-c', f'model_reasoning_effort={json.dumps(effort)}']
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
        raise SystemExit(os.EX_CONFIG)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"codex-deepseek: {error}", file=sys.stderr)
        raise SystemExit(1)
