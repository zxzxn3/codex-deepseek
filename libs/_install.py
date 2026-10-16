"""Read-only installation planning, explicit confirmation, execution and verification."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
import textwrap
import tempfile

# Installation planning must not create bytecode before confirmation.
sys.dont_write_bytecode = True

from ._config import MODELS, configuration, toml_config

SKILL = Path('skills/codex-session-messaging')
BELL = Path('hooks/bell/hooks.toml')
BELL_ASSETS = Path('assets/bell')
LOGO = Path('assets/logo/whale-girl.txt')


def styled(text: str, code: str) -> str:
    if sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb':
        return f'\033[{code}m{text}\033[0m'
    return text


def phase(text: str) -> None:
    print(styled('::', '1;34') + ' ' + styled(text, '1'), flush=True)


def detail(text: str) -> None:
    print('  ' + styled('->', '2') + ' ' + text)


def logo_banner(source: Path) -> None:
    if not sys.stdout.isatty() or os.environ.get('TERM') == 'dumb':
        return
    artwork = (source / LOGO).read_text(encoding='ascii').rstrip('\n')
    columns = shutil.get_terminal_size(fallback=(80, 24)).columns
    if max(map(len, artwork.splitlines()), default=0) <= columns:
        print(artwork)
        print()


def confirm(prompt: str) -> bool:
    while True:
        try:
            answer = input(styled('::', '1;34') + ' ' + styled(prompt, '1')
                           + ' ' + styled('[y/N]', '1') + ' ').strip().lower()
        except EOFError:
            answer = 'n'
        if answer in ('y', 'yes'):
            return True
        if answer in ('', 'n', 'no'):
            print(styled('Cancelled. No changes made.', '33'))
            return False
        print(styled('Please enter y or n.', '33'))


def introduction() -> bool:
    phase('Before you begin')
    width = min(76, shutil.get_terminal_size(fallback=(80, 24)).columns)
    print(styled(textwrap.fill(
        'codex-deepseek is an unofficial, independent project. It is not affiliated '
        'with, sponsored by, or endorsed by OpenAI or DeepSeek. '
        'You use your own DeepSeek API key; API charges are billed by DeepSeek.',
        width=width), '33'))
    print()
    print(styled(textwrap.fill(
        'The installer will show its plan and ask for confirmation again before '
        'creating or changing files. Continuing here does not approve those changes.',
        width=width), '33'))
    print()
    return confirm('Continue?')


def operation_row(operations: list[str], number: int, status: str, *, manual_steps=0) -> None:
    total = len(operations) + manual_steps
    column = max(map(len, operations)) + 4
    label = styled(f'({number}/{total})', '2')
    state = styled(status, '32' if status == 'done' else '2')
    print(f'{label} {operations[number - 1]:<{column}}{state}', flush=True)


def operation_plan(operations: list[str], *, manual_steps=0) -> None:
    for number in range(1, len(operations) + 1):
        operation_row(operations, number, 'pending', manual_steps=manual_steps)


def simulate_operations(operations: list[str], *, manual_steps=0) -> None:
    phase('Simulating changes...')
    for number in range(1, len(operations) + 1):
        operation_row(operations, number, 'simulated', manual_steps=manual_steps)
    detail('File changes and installation verification skipped.')
    print('Dry run complete. No changes made.')


def check_directory(path: Path) -> None:
    for parent in (path, *path.parents):
        if (parent.exists() or parent.is_symlink()) and not parent.is_dir():
            raise ValueError(f'Not a directory: {parent}')


def check_link(source: Path, destination: Path) -> None:
    check_directory(destination.parent)
    if destination.is_symlink() and destination.resolve() == source.resolve():
        return
    if destination.exists() or destination.is_symlink():
        raise ValueError(f'Refusing to replace an unrelated link: {destination}')


def link_to(source: Path, destination: Path) -> None:
    check_link(source, destination)
    if destination.is_symlink():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(os.path.relpath(source, destination.parent))


def check_empty_home(root: Path) -> None:
    check_directory(root)
    home = root / '.codex'
    if home.is_symlink():
        raise ValueError(f'Refusing a symlinked Codex home: {home}')
    check_directory(home)
    if home.exists() and next(home.iterdir(), None) is not None:
        raise ValueError(f'Codex home is not empty: {home}; install does not overwrite existing homes')


def dependencies() -> None:
    for command in ('codex', 'secret-tool'):
        if not shutil.which(command):
            raise ValueError(f'Missing dependency: {command}')
    version = subprocess.check_output(['codex', '--version'], text=True)
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', version)
    if not match or tuple(map(int, match.groups())) < (0, 158, 0):
        raise ValueError('Codex CLI >= 0.158.0 is required')


def project_files(source: Path) -> dict[Path, tuple[bytes, int]]:
    paths = [Path(name) for name in ('launcher.py', 'libs/__init__.py', 'libs/_install.py', 'libs/_config.py', 'models.json',
                                     'README.md', 'MODEL-CATALOG.md')]
    for directory in (Path('probes'), Path('tests'), SKILL, BELL.parent, BELL_ASSETS, LOGO.parent):
        paths.extend(p.relative_to(source) for p in (source / directory).rglob('*')
                     if p.is_file() and (p.suffix in ('.py', '.toml', '.oga', '.txt')
                                        or p.name in ('README.md', 'SKILL.md')))
    for required in (SKILL / 'SKILL.md', BELL, LOGO):
        if required not in paths:
            raise ValueError(f'Bundled component is missing: {required}')
    files = {}
    for relative in sorted(set(paths)):
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing or symlinked project file: {path}')
        files[relative] = (path.read_bytes(), path.stat().st_mode & 0o777)
    models = json.loads(files[Path('models.json')][0])
    entries = models.get('models') if isinstance(models, dict) else None
    if (not isinstance(entries, list) or not all(isinstance(m, dict) for m in entries)
            or not all(isinstance(m.get('slug'), str) for m in entries)
            or {m['slug'] for m in entries} != set(MODELS)):
        raise ValueError('Unexpected model catalog; review before installing')
    return files


def check_payload(source: Path, root: Path, files: dict) -> None:
    check_empty_home(root)
    if root.exists() and root != source:
        allowed = {path.parts[0] for path in files} | {'.codex'}
        if any(path.name not in allowed for path in root.iterdir()):
            raise ValueError(f'Target contains unrelated files: {root}')
    for relative, (content, _) in files.items():
        destination = root / relative
        check_directory(destination.parent)
        if destination.is_symlink() or (destination.exists() and
                (not destination.is_file() or destination.read_bytes() != content)):
            raise ValueError(f'Refusing to overwrite a different project file: {destination}')


def config_source(defaults: bool) -> tuple[str, str]:
    ordinary = Path.home() / '.codex/config.toml'
    if defaults or not ordinary.is_file():
        return '', 'Codex defaults'
    if not sys.stdin.isatty():
        raise ValueError('Ordinary Codex config found; use --defaults or run interactively')
    phase('Choosing configuration...')
    detail(f'Existing configuration: {ordinary}')
    print('    1) Codex defaults\n    2) Copy existing configuration')
    detail('Both choices apply the required DeepSeek connection settings.')
    while True:
        try:
            answer = input('Configuration [1/2, Enter=1, q=cancel]: ').strip().lower()
        except EOFError as error:
            raise ValueError('Installation cancelled; no files changed') from error
        if answer in ('', '1'):
            return '', 'Codex defaults'
        if answer == '2':
            return ordinary.read_text(), f'Copy {ordinary}'
        if answer == 'q':
            raise ValueError('Installation cancelled; no files changed')
        print('Choose 1 or 2, or q to cancel.')


def bell_config(text: str, *, root: Path, resources: Path | None = None) -> str:
    player = shutil.which('paplay')
    if not player:
        raise ValueError('Bell hook requires paplay')
    resources = resources or root
    template = tomllib.loads((resources / BELL).read_text()).get('hooks')
    if not isinstance(template, dict) or not template:
        raise ValueError('Bell template must contain hooks')
    data = tomllib.loads(text)
    hooks = data.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('hooks must be a table')
    changed = False
    for event, additions in template.items():
        groups = hooks.setdefault(event, [])
        for collection in (groups, additions):
            if (not isinstance(collection, list)
                    or not all(isinstance(group, dict) and isinstance(group.get('hooks'), list)
                               and all(isinstance(hook, dict) for hook in group['hooks'])
                               for group in collection)):
                raise ValueError(f'hooks.{event} must contain hook groups')
        for group in additions:
            rendered = []
            for hook in group['hooks']:
                hook = dict(hook)
                try:
                    if not isinstance(hook.get('command'), str):
                        raise ValueError('Bell command must be a string')
                    command = hook['command'].format(
                        player=shlex.quote(player), assets=shlex.quote(str(root / BELL_ASSETS)))
                    argv = shlex.split(command)
                except (KeyError, IndexError, ValueError) as error:
                    raise ValueError(f'Invalid bell command template for {event}') from error
                hook['command'] = command

                def matches(existing):
                    try:
                        current = shlex.split(existing.get('command', ''))
                    except ValueError:
                        return False
                    return existing.get('type') == hook.get('type') and current == argv

                if not any(matches(existing) for old in groups for existing in old['hooks']):
                    rendered.append(hook)
            if rendered:
                groups.append({**group, 'hooks': rendered})
                changed = True
    if not changed:
        return text
    result = toml_config(data)
    tomllib.loads(result)
    return result


def verify_link(source: Path, destination: Path) -> None:
    if not destination.is_symlink() or destination.resolve() != source.resolve():
        raise ValueError(f'Link verification failed: {destination}')


def component_text(text: str, *, width: int) -> str:
    return styled(textwrap.fill(text, width=width), '94')


def next_steps(root: Path, skill: bool, bell: bool, *, automatic_steps: int) -> None:
    command = 'codex-deepseek'
    print()
    phase('Next steps')
    total = automatic_steps + 2
    print(styled(f'({total - 1}/{total})', '2')
          + f' {"Save your API key:":<28}' + styled(f'{command} setup-key', '1'))
    print(styled(f'({total}/{total})', '2')
          + f' {"Start Codex with DeepSeek:":<28}' + styled(command, '1'))
    if bell:
        print('\nTrust the bell hooks in Codex /hooks to enable playback.')
    if not skill or not bell:
        print()
        phase('Optional components')
        if not skill:
            print(component_text(
                'Try out our messaging skill, which lets Codex agents communicate with each other. '
                f'Install with: {command} --install-messaging-skill',
                width=min(76, shutil.get_terminal_size(fallback=(80, 24)).columns)))
        if not bell:
            if not skill:
                print()
            print(component_text(
                'Looking away from the terminal? Let the bell hook sound when a response '
                'finishes or approval is needed, with a cue for each prompt you submit. '
                f'Install with: {command} --install-bell-hook',
                width=min(76, shutil.get_terminal_size(fallback=(80, 24)).columns)))


def planning_check(check, *args, dry_run=False) -> bool:
    try:
        check(*args)
    except ValueError as error:
        if not dry_run:
            raise
        print(styled(f'Would prevent installation: {error}', '33'))
        return False
    return True


def install(source: Path, root: Path, *, defaults=False, skill=False, bell=False, dry_run=False) -> int:
    root = root.expanduser().resolve()
    source = source.resolve()
    files = project_files(source)
    destination_ok = planning_check(check_payload, source, root, files, dry_run=dry_run)
    sys.stdout.flush()
    dependencies()
    link = Path.home() / '.local/bin/codex-deepseek'
    link_ok = planning_check(check_link, root / 'launcher.py', link, dry_run=dry_run)
    logo_banner(source)
    if dry_run:
        phase('Dry run: no changes will be made')
    if not introduction():
        return 0
    print()
    phase('Checking requirements...')
    detail('Python, Codex and secret-tool available.')
    phase('Checking destination...')
    detail('No conflicting project files or command links.' if destination_ok and link_ok
           else 'Resolve the reported conflicts before installing.')
    base, label = config_source(defaults)
    text = configuration(base, root=root)
    if bell:
        text = bell_config(text, root=root, resources=source)
    home = root / '.codex'
    config = home / 'config.toml'
    operations = ['Install project files', 'Create private Codex home',
                  'Write DeepSeek configuration', 'Link command']
    if skill:
        operations.append('Enable session messaging')
    if bell:
        operations.append('Add bell hooks')
    phase('Preparing installation...')
    print()
    operation_plan(operations, manual_steps=2)
    print('\n' + styled('Install directory:', '2') + '  ' + styled(str(root), '1'))
    print(styled('Configuration:', '2') + '      ' + styled(label, '1'))
    print(styled('Command link:', '2') + '       ' + styled(str(link), '1'))
    print()
    if not confirm('Proceed with installation?'):
        return 0
    if dry_run:
        simulate_operations(operations, manual_steps=2)
        next_steps(root, skill, bell, automatic_steps=len(operations))
        return 0
    # Repeat destination checks after the user has had time to read the plan.
    check_payload(source, root, files)
    check_link(root / 'launcher.py', link)
    step = 'create project directory'
    phase('Applying changes...')
    try:
        root.mkdir(parents=True, exist_ok=True)
        for relative, (content, mode) in files.items():
            path = root / relative
            step = f'install {path}'
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as stream:
                    stream.write(content)
                path.chmod(mode)
        (root / 'launcher.py').chmod((root / 'launcher.py').stat().st_mode | 0o100)
        operation_row(operations, 1, 'done', manual_steps=2)
        step = f'write {config}'
        home.mkdir(mode=0o700, exist_ok=True)
        home.chmod(0o700)
        operation_row(operations, 2, 'done', manual_steps=2)
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        operation_row(operations, 3, 'done', manual_steps=2)
        step = 'create command link'
        link_to(root / 'launcher.py', link)
        operation_row(operations, 4, 'done', manual_steps=2)
        if skill:
            step = 'install session messaging skill'
            link_to(root / SKILL, home / 'skills/codex-session-messaging')
            operation_row(operations, 5, 'done', manual_steps=2)
        if bell:
            operation_row(operations, len(operations), 'done', manual_steps=2)
        phase('Verifying installation...')
        step = 'verify installation'
        for relative, (content, _) in files.items():
            if (root / relative).read_bytes() != content:
                raise ValueError(f'File verification failed: {relative}')
        if config.read_text() != text:
            raise ValueError('Config verification failed')
        tomllib.loads(config.read_text())
        verify_link(root / 'launcher.py', link)
        if not os.access(root / 'launcher.py', os.X_OK):
            raise ValueError('Launcher is not executable')
        if home.stat().st_mode & 0o077 or config.stat().st_mode & 0o077:
            raise ValueError('Private home/config permissions verification failed')
        if skill:
            verify_link(root / SKILL, home / 'skills/codex-session-messaging')
    except KeyboardInterrupt:
        print(f'Interrupted at {step}; earlier steps may have completed.', file=sys.stderr)
        raise
    except (OSError, ValueError) as error:
        raise ValueError(f'Installation failed at {step}: {error}; earlier steps may have completed') from error
    detail('Files, configuration, permissions and links verified.')
    print(styled('==> Automatic steps complete.', '1;32'))
    next_steps(root, skill, bell, automatic_steps=len(operations))
    return 0


def installed_home(root: Path) -> tuple[Path, str]:
    root = root.expanduser().resolve()
    config = root / '.codex/config.toml'
    if (root / '.codex').is_symlink() or config.is_symlink():
        raise ValueError('Refusing to modify a symlinked home or config')
    if not (root / 'launcher.py').is_file() or not (root / 'models.json').is_file() or not config.is_file():
        raise ValueError(f'No installed codex-deepseek home at {root}')
    text = config.read_text()
    if tomllib.loads(text).get('model_provider') != 'deepseek':
        raise ValueError(f'Configuration does not select DeepSeek: {config}')
    return root, text


def update(source: Path, root: Path, *, dry_run=False) -> int:
    """Apply a separately downloaded release, preserving all private home data."""
    source = source.resolve()
    root, original_config = installed_home(root)
    if source == root:
        raise ValueError('Run --update from a separate checkout of the new version; '
                         'use --dir to select the existing installation')
    files = project_files(source)
    dependencies()
    # Sounds belong to the user after installation, including intentional deletions.
    files = {path: value for path, value in files.items()
             if not (path.is_relative_to(BELL_ASSETS) and path.suffix == '.oga')}

    def snapshot():
        result = {}
        for relative in files:
            path = root / relative
            # Refuse redirected writes, including symlinked parent directories.
            for part in (path, *path.parents):
                if part == root:
                    break
                if part.is_symlink():
                    raise ValueError(f'Refusing a symlinked update path: {part}')
            check_directory(path.parent)
            if path.exists() and not path.is_file():
                raise ValueError(f'Not a regular project file: {path}')
            result[relative] = ((path.read_bytes(), path.stat().st_mode & 0o777)
                                if path.exists() else None)
        return result

    before = snapshot()
    changes = {path: value for path, value in files.items()
               if before[path] is None or before[path][0] != value[0]
               or (path == Path('launcher.py') and not before[path][1] & 0o100)}
    if not changes:
        print('Project files are already up to date; no files changed.')
        return 0
    if dry_run:
        phase('Dry run: no changes will be made')
    if not introduction():
        return 0
    operations = ['Back up replaced project files', 'Update project files', 'Verify updated files']
    phase('Preparing update...')
    operation_plan(operations)
    detail(f'New version: {source}')
    detail(f'Installation: {root}')
    detail('Keep private Codex home, configuration, command link and sounds unchanged.')
    detail('Backups: ' + str(root / '.update-backups'))
    for relative in changes:
        detail(f'{"Add" if before[relative] is None else "Replace"}: {relative}')
    if not confirm('Proceed with update?'):
        return 0
    if dry_run:
        simulate_operations(operations)
        return 0
    if snapshot() != before or (root / '.codex/config.toml').read_text() != original_config:
        raise ValueError('Installation changed after planning; no changes applied; run again')
    backups = root / '.update-backups'
    if backups.is_symlink():
        raise ValueError(f'Refusing a symlinked backup directory: {backups}')
    phase('Applying changes...')
    backup = None
    step = operations[0]
    try:
        backups.mkdir(mode=0o700, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix='update-', dir=backups))
        for relative in changes:
            if before[relative] is not None:
                target = backup / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before[relative][0])
                target.chmod(before[relative][1])
        operation_row(operations, 1, 'done')
        step = operations[1]
        for relative, (content, mode) in changes.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
            temporary = Path(name)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
                temporary.chmod(mode | (0o100 if relative == Path('launcher.py') else 0))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        operation_row(operations, 2, 'done')
        step = operations[2]
        for relative, (content, _) in changes.items():
            if (root / relative).read_bytes() != content:
                raise ValueError(f'File verification failed: {relative}')
        if (root / '.codex/config.toml').read_text() != original_config:
            raise ValueError('Configuration changed during update')
        operation_row(operations, 3, 'done')
    except (OSError, ValueError, KeyboardInterrupt) as error:
        print(f'Update stopped at {step}; earlier steps may have completed. '
              f'Backup: {backup or backups}', file=sys.stderr)
        raise
    detail(f'Backup: {backup}')
    print(styled('==> Update complete. Restart Codex sessions to use the updated launcher and skill.', '1;32'))
    return 0


def install_extra(root: Path, *, skill=False, dry_run=False) -> int:
    root, original = installed_home(root)
    home = root / '.codex'
    if skill:
        source, destination = root / SKILL, home / 'skills/codex-session-messaging'
        if destination.parent.is_symlink():
            raise ValueError(f'Refusing a symlinked skills directory: {destination.parent}')
        if not (source / 'SKILL.md').is_file():
            raise ValueError(f'Bundled skill is missing: {source}')
        check_link(source, destination)
        if destination.is_symlink():
            print('Session messaging skill is already installed; no files changed.')
            return 0
        operations = ['Link session messaging skill']
        lines = [f'Link: {destination}', f'Target: {source}', 'Configuration stays unchanged.']
        updated = original
    else:
        updated = bell_config(original, root=root)
        if updated == original:
            print('Bell hook is already installed; no files changed.')
            return 0
        config = home / 'config.toml'
        n = 1
        while config.with_name(f'config.toml.bak.{n}').exists():
            n += 1
        backup = config.with_name(f'config.toml.bak.{n}')
        operations = ['Back up configuration', 'Append bell hooks']
        lines = [f'Back up {config} to {backup}',
                 f'Append missing bell hooks to {config}; keep other settings']
    if dry_run:
        phase('Dry run: no changes will be made')
    if not introduction():
        return 0
    print()
    phase('Preparing component installation...')
    operation_plan(operations)
    for line in lines:
        detail(line)
    print()
    if not confirm('Apply these changes?'):
        return 0
    if dry_run:
        simulate_operations(operations)
        return 0
    if (home / 'config.toml').read_text() != original:
        raise ValueError('Configuration changed after planning; no changes applied; run again')
    phase('Applying changes...')
    try:
        if skill:
            link_to(source, destination)
            verify_link(source, destination)
            operation_row(operations, 1, 'done')
        else:
            # Backup is exclusive, and the replacement is validated before it is written.
            with backup.open('xb') as stream:
                stream.write(original.encode())
            backup.chmod(0o600)
            operation_row(operations, 1, 'done')
            temporary = config.with_name(f'config.toml.tmp.{os.getpid()}')
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(updated)
                temporary.replace(config)
            finally:
                temporary.unlink(missing_ok=True)
            if config.read_text() != updated:
                raise ValueError('Bell hook config verification failed')
            tomllib.loads(config.read_text())
            operation_row(operations, 2, 'done')
    except (OSError, ValueError) as error:
        raise ValueError(f'Optional component installation failed: {error}; '
                         'some changes may have completed') from error
    print(styled('==> Component installation complete.', '1;32'))
    if not skill:
        print('Review and trust the bell hooks in Codex /hooks to activate them.')
    return 0


def run(args: list[str], *, source: Path) -> int:
    parser = argparse.ArgumentParser(prog='codex-deepseek install' if args[0] == 'install' else 'codex-deepseek')
    parser.add_argument('--dry-run', action='store_true',
                        help='rehearse the interactive installation without file changes')
    if args[0] == 'install':
        for option in ('--install-messaging-skill', '--install-bell-hook'):
            if any(arg.partition('=')[0] == option for arg in args[1:]):
                parser.error(f'For an existing installation, use codex-deepseek {option} '
                             '(add --dir PATH for a custom destination)')
        parser.add_argument('--dir', type=Path, default=Path.home() / '.local/share/codex-deepseek')
        parser.add_argument('--update', action='store_true', help='update an existing installation from this checkout')
        parser.add_argument('--defaults', action='store_true', help='skip configuration-source selection')
        parser.add_argument('--with-messaging-skill', action='store_true')
        parser.add_argument('--with-bell-hook', action='store_true')
        options = parser.parse_args(args[1:])
        if options.update:
            if options.defaults or options.with_messaging_skill or options.with_bell_hook:
                parser.error('--update cannot be combined with fresh-install options')
            return update(source, options.dir, dry_run=options.dry_run)
        return install(source, options.dir, defaults=options.defaults,
                       skill=options.with_messaging_skill, bell=options.with_bell_hook,
                       dry_run=options.dry_run)
    parser.add_argument('--dir', type=Path, default=source)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--install-messaging-skill', action='store_true')
    group.add_argument('--install-bell-hook', action='store_true')
    options = parser.parse_args(args)
    return install_extra(options.dir, skill=options.install_messaging_skill, dry_run=options.dry_run)

