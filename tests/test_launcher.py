"""Keyring tests without accessing real credentials."""
from pathlib import Path
import contextlib
import io
import subprocess
import sys
import unittest
import tempfile
import tomllib
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher

class CredentialTest(unittest.TestCase):
    def test_store_and_verify(self):
        results = [subprocess.CompletedProcess([], 0, '', ''),
                   subprocess.CompletedProcess([], 0, 'test-only\n', '')]
        with patch.object(launcher.sys.stdin, 'isatty', return_value=True), patch.object(launcher.getpass, 'getpass', return_value='test-only'), patch.object(launcher.subprocess, 'run', side_effect=results) as run, contextlib.redirect_stdout(io.StringIO()):
            launcher.save_key()
        self.assertEqual(run.call_args_list[0].kwargs['input'], 'test-only')
        self.assertNotIn('test-only', run.call_args_list[0].args[0])
        self.assertEqual(run.call_args_list[1].args[0], ['secret-tool', 'lookup', *launcher.KEY_ATTRIBUTES])

    def test_noninteractive_key_input_is_rejected(self):
        with patch.object(launcher.sys.stdin, 'isatty', return_value=False), \
             patch.object(launcher.getpass, 'getpass') as read, \
             patch.object(launcher.subprocess, 'run') as store:
            with self.assertRaisesRegex(ValueError, 'interactive terminal'):
                launcher.save_key()
            read.assert_not_called()
            store.assert_not_called()

    def test_echo_fallback_is_rejected(self):
        with patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
             patch.object(launcher.getpass, 'getpass', side_effect=launcher.getpass.GetPassWarning), \
             patch.object(launcher.subprocess, 'run') as store:
            with self.assertRaisesRegex(ValueError, 'hidden key'):
                launcher.save_key()
            store.assert_not_called()

    def test_missing_or_invalid_secret(self):
        for code, value in [(1, 'sensitive-output'), (0, ''), (0, 'bad key')]:
            with patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, value, '')):
                with self.assertRaisesRegex(ValueError, 'Unlock your keyring'):
                    launcher.check_key()

class InstallerEntryTest(unittest.TestCase):
    def test_install_and_components_route_without_home_or_keyring(self):
        from libs import _install
        for args in (['install', '--defaults', '--dry-run'],
                     ['install', '--update', '--dir', '/tmp/example'],
                     ['--install-messaging-skill'], ['--install-bell-hook', '--dry-run']):
            with self.subTest(args=args), patch.object(_install, 'run', return_value=0) as run, \
                 patch.object(launcher, 'check_key') as key, \
                 patch.object(launcher.os, 'execvpe') as execute:
                self.assertEqual(launcher.main(args), 0)
                run.assert_called_once_with(args, source=launcher.HERE)
                key.assert_not_called()
                execute.assert_not_called()

    def test_install_help_works_from_clean_checkout_without_writes(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(launcher.HERE / 'launcher.py', root / 'launcher.py')
            shutil.copytree(launcher.HERE / 'libs', root / 'libs',
                            ignore=shutil.ignore_patterns('__pycache__'))
            before = sorted(str(p.relative_to(root)) for p in root.rglob('*'))
            result = subprocess.run([sys.executable, str(root / 'launcher.py'), 'install', '--help'],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('codex-deepseek install', result.stdout)
            self.assertIn('--dry-run', result.stdout)
            self.assertIn('--update', result.stdout)
            self.assertEqual(sorted(str(p.relative_to(root)) for p in root.rglob('*')), before)


class KeyPreflightTest(unittest.TestCase):
    def test_local_commands_do_not_touch_keyring(self):
        for args in [['queue', '--message', 'hello'], ['agents'], ['help', 'exec'],
                     ['-h'], ['-V'], ['exec', '--help'],
                     ['-c', 'model=x', 'queue'], ['--config=model=x', 'agents'],
                     ['-C', '/tmp', 'archive', 'id'], ['-cmodel=x', 'queue']]:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as tmp:
                data = Path(tmp)
                (data / 'config.toml').write_text('')
                with patch.object(launcher, 'DATA', data), \
                     patch.object(launcher, 'check_key') as check, \
                     patch.object(launcher.os, 'execvpe') as execute:
                    launcher.main(args)
                    check.assert_not_called()
                    self.assertEqual(execute.call_args.args[1], ['codex', *args])

    def test_home_model_is_forwarded_before_user_overrides(self):
        for args in ([], ['exec', 'hello'], ['resume', '--all']):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as tmp:
                data = Path(tmp)
                (data / 'config.toml').write_text('model = "deepseek-flash"\n')
                with patch.object(launcher, 'DATA', data), \
                     patch.object(launcher, 'check_key'), \
                     patch.object(launcher.os, 'execvpe') as execute:
                    launcher.main(args)
                self.assertEqual(execute.call_args.args[1],
                                 ['codex', '--model', 'deepseek-flash', *args])
                self.assertEqual(execute.call_args.args[2]['CODEX_HOME'], str(data))

    def test_explicit_models_are_not_overridden(self):
        for args in (['-m', 'deepseek-v4-pro'], ['--model=custom'], ['-mcustom'],
                     ['exec', '--model', 'custom', 'hello'],
                     ['-c', 'model="custom"', 'exec', 'hello'],
                     ['--config=model="custom"'], ['-cmodel="custom"']):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as tmp:
                data = Path(tmp)
                (data / 'config.toml').write_text('model = "deepseek-flash"\n')
                with patch.object(launcher, 'DATA', data), \
                     patch.object(launcher, 'check_key'), \
                     patch.object(launcher.os, 'execvpe') as execute:
                    launcher.main(args)
                self.assertEqual(execute.call_args.args[1], ['codex', *args])

    def test_model_detection_skips_option_values_and_literal_arguments(self):
        for args in (['-C', '--model'], ['--', '-m', 'literal'],
                     ['-c', 'model_reasoning_effort="high"']):
            with self.subTest(args=args):
                self.assertFalse(launcher.explicit_model(args))

    def test_prompts_and_option_values_do_not_become_commands(self):
        for args in [[], ['exec', 'queue'], ['resume'], ['app-server'], ['doctor'],
                     ['please inspect', 'queue'], ['--', 'queue'],
                     ['-c', 'queue', 'exec', 'hi'], ['--profile', 'agents'],
                     ['-C', 'queue'], ['exec', '--', '--help'],
                     ['--unknown-option', 'queue'], ['-i', 'image.png', 'queue']]:
            with self.subTest(args=args):
                self.assertTrue(launcher.requires_key(args))


if __name__ == '__main__':
    unittest.main()
