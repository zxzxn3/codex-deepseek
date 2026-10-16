"""Installer checks use disposable homes and mocked dependencies, never real credentials."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from libs import _install as installer
import launcher


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / 'app with spaces'
        self.source = launcher.HERE
        self.enterContext(patch.object(installer.Path, 'home', return_value=self.home))
        self.enterContext(patch.object(installer, 'dependencies'))
        self.original_introduction = installer.introduction
        self.introduction = self.enterContext(patch.object(installer, 'introduction', return_value=True))
        self.enterContext(patch.object(installer.sys.stdin, 'isatty', return_value=False))
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def install(self, **options):
        options.setdefault('defaults', True)
        return installer.install(self.source, self.root, **options)

    def contents(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob('*'))

    def test_dry_run_keeps_confirmations_without_writes(self):
        self.introduction.side_effect = self.original_introduction
        with patch('builtins.input', return_value='y') as prompt:
            self.assertEqual(self.install(dry_run=True), 0)
            self.assertEqual(prompt.call_count, 2)
        self.assertEqual(self.contents(), [])
        self.assertIn('Dry run complete. No changes made.', self.output.getvalue())
        self.assertIn('Install project files', self.output.getvalue())
        self.assertNotIn('Applying changes', self.output.getvalue())
        self.assertNotIn('Automatic steps complete', self.output.getvalue())
        self.assertIn('simulated', self.output.getvalue())
        self.assertIn('Next steps', self.output.getvalue())

    def test_dry_run_can_cancel_at_either_confirmation(self):
        self.introduction.side_effect = self.original_introduction
        for answers in (['n'], [EOFError()], ['y', 'n'], ['y', EOFError()]):
            with self.subTest(answers=answers), patch('builtins.input', side_effect=answers):
                self.assertEqual(self.install(dry_run=True), 0)
                self.assertEqual(self.contents(), [])
        self.assertNotIn('simulated', self.output.getvalue())

    def test_dry_run_reports_conflicts_without_overwriting(self):
        home = self.root / '.codex'
        home.mkdir(parents=True)
        marker = home / 'config.toml'
        marker.write_text('existing home')
        link = self.home / '.local/bin/codex-deepseek'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.home / 'unrelated')
        before = self.contents()
        with patch('builtins.input', return_value='y') as prompt:
            self.assertEqual(self.install(dry_run=True), 0)
            prompt.assert_called_once()
        self.assertEqual(self.contents(), before)
        self.assertEqual(marker.read_text(), 'existing home')
        self.assertEqual(link.readlink(), self.home / 'unrelated')
        self.assertEqual(self.output.getvalue().count('Would prevent installation:'), 2)
        self.assertNotIn('No conflicting project files', self.output.getvalue())
        with self.assertRaisesRegex(ValueError, 'not empty'):
            self.install()

    def test_component_dry_runs_preserve_config_and_links(self):
        with patch('builtins.input', return_value='y'):
            self.install()
        self.introduction.side_effect = self.original_introduction
        config = self.root / '.codex/config.toml'
        before, content = self.contents(), config.read_bytes()
        for skill in (True, False):
            with self.subTest(skill=skill), self.bell_dependencies(), patch('builtins.input', return_value='y') as prompt:
                self.assertEqual(installer.install_extra(self.root, skill=skill, dry_run=True), 0)
                self.assertEqual(prompt.call_count, 2)
                self.assertEqual(self.contents(), before)
                self.assertEqual(config.read_bytes(), content)

    def test_decline_and_eof_do_not_write(self):
        for answer in ['', 'n', EOFError()]:
            with self.subTest(answer=answer), patch('builtins.input', side_effect=[answer]):
                self.assertEqual(self.install(), 0)
                self.assertEqual(self.contents(), [])
        self.assertIn('Codex defaults', self.output.getvalue())
        self.assertNotIn('Enable session messaging', self.output.getvalue())
        self.assertNotIn('Add bell hooks', self.output.getvalue())

    def test_both_confirmations_precede_any_writes(self):
        self.introduction.side_effect = self.original_introduction
        for answers in (['n'], [EOFError()], ['y', 'n'], ['y', EOFError()]):
            with self.subTest(answers=answers), patch('builtins.input', side_effect=answers):
                self.assertEqual(self.install(), 0)
                self.assertEqual(self.contents(), [])
        with patch('builtins.input', side_effect=['y', 'y']):
            self.assertEqual(self.install(), 0)
        self.assertTrue((self.root / '.codex/config.toml').is_file())

    def test_defaults_and_source_survive_relocation(self):
        original = (self.source / 'launcher.py').read_bytes()
        with patch('builtins.input', return_value='y'):
            self.install()
        config = tomllib.loads((self.root / '.codex/config.toml').read_text())
        self.assertEqual(config['model_catalog_json'], str(self.root / 'models.json'))
        for key in ('approval_policy', 'sandbox_mode', 'hooks', 'web_search',
                    'model_reasoning_effort', 'show_raw_agent_reasoning'):
            self.assertNotIn(key, config)
        link = self.home / '.local/bin/codex-deepseek'
        self.assertEqual(link.resolve(), self.root / 'launcher.py')
        self.assertTrue((self.root / 'libs/_install.py').is_file())
        self.assertTrue((self.root / installer.SKILL / 'SKILL.md').is_file())
        self.assertFalse((self.root / installer.SKILL / 'SKILL.zh.md').exists())
        self.assertFalse((self.root / '.codex/skills').exists())
        self.assertEqual((self.source / 'launcher.py').read_bytes(), original)
        self.assertEqual((self.root / '.codex').stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / '.codex/config.toml').stat().st_mode & 0o777, 0o600)
        self.assertIn('--install-bell-hook', self.output.getvalue())

    def test_empty_home_is_accepted_but_any_content_blocks(self):
        data = self.root / '.codex'
        data.mkdir(parents=True)
        marker = data / 'auth.json'
        marker.write_text('fixture')
        before = self.contents()
        with patch('builtins.input') as prompt:
            with self.assertRaisesRegex(ValueError, 'not empty'):
                self.install()
            prompt.assert_not_called()
        self.assertEqual(self.contents(), before)
        self.assertEqual(marker.read_text(), 'fixture')
        marker.unlink()
        with patch('builtins.input', return_value='y'):
            self.install()
        self.assertTrue((data / 'config.toml').is_file())
        with patch('builtins.input') as prompt:
            with self.assertRaisesRegex(ValueError, 'not empty'):
                self.install()
            prompt.assert_not_called()

    def test_target_and_command_conflicts_abort_before_writes(self):
        self.root.mkdir()
        foreign = self.root / 'unrelated.txt'
        foreign.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'unrelated files'):
            self.install()
        foreign.unlink()
        link = self.home / '.local/bin/codex-deepseek'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.home / 'another-launcher')
        with self.assertRaisesRegex(ValueError, 'unrelated link'):
            self.install()
        self.assertFalse((self.root / '.codex').exists())
        self.assertTrue(link.is_symlink())

    def test_configuration_copy_is_only_a_config_copy(self):
        ordinary = self.home / '.codex'
        ordinary.mkdir()
        original = ('approval_policy = "on-request"\nsandbox_mode = "workspace-write"\n'
                    'profile = "ordinary"\n'
                    '[hooks]\nStop = [{hooks = [{type="command", command="true"}]}]\n'
                    '[hooks.state.fixture]\ntrusted_hash = "do-not-copy"\n')
        (ordinary / 'config.toml').write_text(original)
        (ordinary / 'auth.json').write_text('not copied')
        with patch.object(installer.sys.stdin, 'isatty', return_value=True), \
             patch('builtins.input', side_effect=['2', 'y']):
            self.install(defaults=False)
        result = tomllib.loads((self.root / '.codex/config.toml').read_text())
        self.assertEqual(result['approval_policy'], 'on-request')
        self.assertEqual(result['hooks']['Stop'][0]['hooks'][0]['command'], 'true')
        self.assertNotIn('state', result['hooks'])
        self.assertNotIn('profile', result)
        self.assertFalse((self.root / '.codex/auth.json').exists())
        self.assertEqual((ordinary / 'config.toml').read_text(), original)

    def test_noninteractive_ordinary_config_needs_defaults(self):
        config = self.home / '.codex/config.toml'
        config.parent.mkdir()
        config.write_text('')
        with self.assertRaisesRegex(ValueError, '--defaults'):
            self.install(defaults=False)
        self.assertFalse(self.root.exists())

    def test_bad_copy_and_quit_leave_no_target(self):
        config = self.home / '.codex/config.toml'
        config.parent.mkdir()
        config.write_text('model = [broken')
        with patch.object(installer.sys.stdin, 'isatty', return_value=True):
            with patch('builtins.input', return_value='2'):
                with self.assertRaises(tomllib.TOMLDecodeError):
                    self.install(defaults=False)
            for answer in ['q', EOFError()]:
                with patch('builtins.input', side_effect=[answer]):
                    with self.assertRaisesRegex(ValueError, 'cancelled'):
                        self.install(defaults=False)
        self.assertFalse(self.root.exists())

    def test_recheck_after_confirmation_prevents_overwrite(self):
        def consent(_):
            data = self.root / '.codex'
            data.mkdir(parents=True)
            (data / 'config.toml').write_text('created during prompt')
            return 'y'
        with patch('builtins.input', side_effect=consent):
            with self.assertRaisesRegex(ValueError, 'not empty'):
                self.install()
        self.assertEqual((self.root / '.codex/config.toml').read_text(), 'created during prompt')
        self.assertFalse((self.root / 'launcher.py').exists())

    def test_skill_addition_does_not_touch_config(self):
        with patch('builtins.input', return_value='y'):
            self.install()
        config = self.root / '.codex/config.toml'
        before = config.read_bytes()
        with patch('builtins.input', return_value='n'):
            installer.install_extra(self.root, skill=True)
        destination = self.root / '.codex/skills/codex-session-messaging'
        self.assertFalse(destination.exists())
        with patch('builtins.input', return_value='y'):
            installer.install_extra(self.root, skill=True)
        self.assertEqual(destination.resolve(), self.root / installer.SKILL)
        self.assertEqual(config.read_bytes(), before)
        with patch('builtins.input') as prompt:
            installer.install_extra(self.root, skill=True)
            prompt.assert_not_called()

    def test_skill_in_initial_install_and_conflicting_addon(self):
        with patch('builtins.input', return_value='y'):
            self.install(skill=True)
        destination = self.root / '.codex/skills/codex-session-messaging'
        destination.unlink()
        destination.mkdir()
        (destination / 'SKILL.md').write_text('unrelated')
        config = (self.root / '.codex/config.toml').read_bytes()
        with self.assertRaisesRegex(ValueError, 'unrelated link'):
            installer.install_extra(self.root, skill=True)
        self.assertEqual((self.root / '.codex/config.toml').read_bytes(), config)
        self.assertEqual((destination / 'SKILL.md').read_text(), 'unrelated')

    def test_addons_require_an_existing_installation(self):
        for skill in (False, True):
            with self.assertRaisesRegex(ValueError, 'No installed'):
                installer.install_extra(self.root, skill=skill)
        self.assertEqual(self.contents(), [])

    def bell_dependencies(self):
        return patch.object(installer.shutil, 'which', return_value='/usr/bin/paplay')

    def test_bell_append_preserves_preferences_hooks_and_trust(self):
        with patch('builtins.input', return_value='y'):
            self.install()
        config = self.root / '.codex/config.toml'
        data = tomllib.loads(config.read_text())
        data['tui'] = {'notifications': False}
        data['hooks'] = {'Stop': [{'hooks': [{'type': 'command', 'command': 'true'}]}],
                         'state': {'fixture': {'trusted_hash': 'retain-existing'}}}
        original = installer.toml_config(data)
        config.write_text(original)
        with self.bell_dependencies(), patch.object(installer.shutil, 'which', return_value='/usr/bin/paplay'):
            with patch('builtins.input', return_value='n'):
                installer.install_extra(self.root)
            self.assertEqual(config.read_text(), original)
            with patch('builtins.input', return_value='y'):
                installer.install_extra(self.root)
            after = tomllib.loads(config.read_text())
            self.assertEqual(after['tui'], data['tui'])
            self.assertEqual(after['hooks']['state'], data['hooks']['state'])
            self.assertEqual(after['hooks']['Stop'][0], data['hooks']['Stop'][0])
            self.assertEqual(len(after['hooks']['Stop']), 2)
            self.assertEqual((config.parent / 'config.toml.bak.1').read_text(), original)
            with patch('builtins.input') as prompt:
                installer.install_extra(self.root)
                prompt.assert_not_called()
            self.assertEqual(len(list(config.parent.glob('*.bak.*'))), 1)
        self.assertIn('/hooks', self.output.getvalue())

    def test_missing_bell_dependency_writes_nothing(self):
        with patch.object(installer.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'paplay'):
                self.install(bell=True)
        self.assertEqual(self.contents(), [])

    def test_initial_bell_hook_is_opt_in(self):
        with self.bell_dependencies(), \
             patch.object(installer.shutil, 'which', return_value='/usr/bin/paplay'), \
             patch('builtins.input', return_value='y'):
            self.install(bell=True)
        hooks = tomllib.loads((self.root / '.codex/config.toml').read_text())['hooks']
        expected = tomllib.loads((self.root / installer.BELL).read_text())['hooks']
        self.assertEqual(set(hooks), set(expected))
        self.assertNotIn('state', hooks)

    def test_bell_paths_follow_installation_and_sounds_can_be_replaced(self):
        with self.bell_dependencies(), patch('builtins.input', return_value='y'):
            self.install(bell=True)
        config = self.root / '.codex/config.toml'
        before = config.read_bytes()
        data = tomllib.loads(before.decode())
        import shlex
        for event, groups in data['hooks'].items():
            command = shlex.split(groups[0]['hooks'][0]['command'])
            self.assertEqual(command[:3], ['test', '!', '-f'])
            self.assertEqual(command[-2], '/usr/bin/paplay')
            self.assertEqual(command[3], command[-1])
            self.assertEqual(Path(command[-1]).parent, self.root / installer.BELL_ASSETS)
            self.assertTrue(Path(command[-1]).is_file())
        sound = self.root / installer.BELL_ASSETS / 'prompt.oga'
        sound.write_bytes(b'custom sound fixture')
        self.assertEqual(config.read_bytes(), before)
        with self.bell_dependencies(), patch('builtins.input') as prompt:
            installer.install_extra(self.root)
            prompt.assert_not_called()
        self.assertEqual(sound.read_bytes(), b'custom sound fixture')
        self.assertEqual(config.read_bytes(), before)

    def test_missing_sound_skips_player_and_returns_success(self):
        import shlex
        import subprocess
        log = self.home / 'player.log'
        player = self.home / 'fake player'
        player.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> ' + shlex.quote(str(log)) + '\n')
        player.chmod(0o700)
        with patch.object(installer.shutil, 'which', return_value=str(player)), \
             patch('builtins.input', return_value='y'):
            self.install(bell=True)
        data = tomllib.loads((self.root / '.codex/config.toml').read_text())
        sounds = self.root / installer.BELL_ASSETS
        (sounds / 'prompt.oga').unlink()
        prompt = data['hooks']['UserPromptSubmit'][0]['hooks'][0]['command']
        complete = data['hooks']['Stop'][0]['hooks'][0]['command']
        result = subprocess.run(['/bin/sh', '-c', prompt], cwd=self.home,
                                capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertFalse(log.exists())
        result = subprocess.run(['/bin/sh', '-c', complete], cwd=self.home,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(log.read_text().strip(), str(sounds / 'complete.oga'))
        (sounds / 'complete.oga').unlink()
        result = subprocess.run(['/bin/sh', '-c', complete], cwd=self.home,
                                capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(len(log.read_text().splitlines()), 1)
        with patch.object(installer.shutil, 'which', return_value=str(player)), \
             patch('builtins.input') as ask:
            installer.install_extra(self.root)
            ask.assert_not_called()

    def test_cli_has_no_copy_or_overwrite_switch(self):
        with patch.object(installer, 'install', return_value=0) as run:
            installer.run(['install', '--dir', str(self.root), '--defaults',
                           '--with-messaging-skill', '--with-bell-hook'], source=self.source)
            run.assert_called_once_with(self.source, self.root, defaults=True, skill=True, bell=True,
                                        dry_run=False)
        with patch.object(installer, 'install_extra', return_value=0) as run:
            installer.run(['--dir', str(self.root), '--install-bell-hook'], source=self.source)
            run.assert_called_once_with(self.root, skill=False, dry_run=False)
        for option in ('--config-source', '--force', '--install-hooks'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                installer.run(['install', option], source=self.source)

    def test_component_flags_explain_the_correct_entry(self):
        for option in ('--install-messaging-skill', '--install-bell-hook'):
            output = io.StringIO()
            with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as error:
                installer.run(['install', option], source=self.source)
            self.assertEqual(error.exception.code, 2)
            self.assertIn(f'codex-deepseek {option}', output.getvalue())

    def test_update_preserves_home_sounds_and_backs_up_local_edits(self):
        with patch('builtins.input', return_value='y'):
            self.install(skill=True)
        config = self.root / '.codex/config.toml'
        original = config.read_bytes()
        session = self.root / '.codex/session-fixture'
        session.write_text('private session')
        sound = self.root / installer.BELL_ASSETS / 'prompt.oga'
        sound.write_bytes(b'custom sound')
        missing_sound = self.root / installer.BELL_ASSETS / 'complete.oga'
        missing_sound.unlink()
        readme = self.root / 'README.md'
        readme.write_text('local edit')
        link = self.home / '.local/bin/codex-deepseek'
        original_link = link.readlink()
        with patch('builtins.input', return_value='y'):
            self.assertEqual(installer.update(self.source, self.root), 0)
        self.assertEqual(readme.read_bytes(), (self.source / 'README.md').read_bytes())
        backups = list((self.root / '.update-backups').glob('update-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'README.md').read_text(), 'local edit')
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(session.read_text(), 'private session')
        self.assertEqual(sound.read_bytes(), b'custom sound')
        self.assertFalse(missing_sound.exists())
        self.assertEqual(link.readlink(), original_link)
        with patch('builtins.input') as prompt:
            installer.update(self.source, self.root)
            prompt.assert_not_called()
        self.assertEqual(len(list((self.root / '.update-backups').iterdir())), 1)

    def test_update_dry_run_and_cancellation_do_not_write(self):
        with patch('builtins.input', return_value='y'):
            self.install()
        (self.root / 'README.md').write_text('old version')
        before = self.contents()
        self.introduction.side_effect = self.original_introduction
        for answers, dry_run in ((['y', 'y'], True), (['n'], False),
                                 (['y', 'n'], False), (['y', EOFError()], False)):
            with self.subTest(answers=answers), patch('builtins.input', side_effect=answers):
                installer.update(self.source, self.root, dry_run=dry_run)
            self.assertEqual(self.contents(), before)
            self.assertEqual((self.root / 'README.md').read_text(), 'old version')

    def test_update_refuses_redirected_paths_and_rechecks_before_writing(self):
        with patch('builtins.input', return_value='y'):
            self.install()
        readme = self.root / 'README.md'
        readme.unlink()
        foreign = self.home / 'foreign'
        foreign.write_text('keep')
        readme.symlink_to(foreign)
        with self.assertRaisesRegex(ValueError, 'symlinked update path'):
            installer.update(self.source, self.root)
        self.assertEqual(foreign.read_text(), 'keep')
        readme.unlink()
        readme.write_text('old')
        def consent(_):
            readme.write_text('changed during prompt')
            return 'y'
        with patch('builtins.input', side_effect=consent):
            with self.assertRaisesRegex(ValueError, 'changed after planning'):
                installer.update(self.source, self.root)
        self.assertFalse((self.root / '.update-backups').exists())
        with self.assertRaisesRegex(ValueError, 'separate checkout'):
            installer.update(self.root, self.root)

    def test_update_cli_routes_without_fresh_install_flags(self):
        with patch.object(installer, 'update', return_value=0) as run:
            installer.run(['install', '--update', '--dir', str(self.root), '--dry-run'],
                          source=self.source)
            run.assert_called_once_with(self.source, self.root, dry_run=True)
        for option in ('--defaults', '--with-messaging-skill', '--with-bell-hook'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                installer.run(['install', '--update', option], source=self.source)

    def test_toml_round_trip(self):
        source = ('title = "line\\nnext"\nvalues = [true, 3, 1.25, "x"]\n'
                  'date = 2026-10-15\ntime = 12:34:56\n'
                  'stamp = 2026-10-15T12:34:56Z\n'
                  '["quoted.key"]\nitems = [{a = "b", nested = {x = [1, 2]}}]\n')
        parsed = tomllib.loads(source)
        self.assertEqual(tomllib.loads(installer.toml_config(parsed)), parsed)


if __name__ == '__main__':
    unittest.main()
