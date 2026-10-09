"""Exercise rollout ordering and failures without Docker or production credentials."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy-production.sh'

class DeploymentTests(unittest.TestCase):
    def run_deploy(self, tag='v0.20.3', fail=''):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deploy = root / 'production'
            deploy.mkdir()
            (deploy / '.env').write_text('IMAGE_TAG=v0.20.2\nSECRET=do-not-print\n')
            (deploy / 'compose.yml').write_text('old compose')
            tools = root / 'bin'
            tools.mkdir()
            for name, body in {
                'docker': '''printf '%s\\n' "$*" >> "$MOCK_LOG"
if [[ -n "$MOCK_FAIL" && "$*" == *"$MOCK_FAIL"* ]]; then exit 1; fi
if [[ "$*" == *pg_dump* ]]; then printf 'mock dump'; fi
if [[ "$*" == *pg_restore* ]]; then cat >/dev/null; fi
''',
                'flock': 'exit 0\n',
                'sleep': 'exit 0\n',
            }.items():
                path = tools / name
                path.write_text('#!/usr/bin/env bash\n' + body)
                path.chmod(0o700)
            log = root / 'commands'
            result = subprocess.run(['bash', str(SCRIPT), tag, str(deploy)], env={**os.environ, 'PATH': f'{tools}:{os.environ["PATH"]}', 'MOCK_LOG': str(log), 'MOCK_FAIL': fail}, text=True, capture_output=True)
            return result, log.read_text() if log.exists() else '', (deploy / '.env').read_text(), list((deploy / 'backups').glob('*/database.dump'))

    def test_success_backs_up_before_stopping_and_migrates_before_starting(self):
        result, commands, env, backups = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(commands.index('pg_restore'), commands.index('stop -t 30'))
        self.assertLess(commands.index('run --rm migrate'), commands.index('up -d --wait'))
        self.assertIn('IMAGE_TAG=v0.20.3', env)
        self.assertEqual(len(backups), 1)
        self.assertNotIn('do-not-print', result.stdout + result.stderr)

    def test_pull_or_backup_failure_preserves_live_configuration(self):
        for fail in ['pull', 'pg_restore']:
            with self.subTest(fail=fail):
                result, commands, env, _ = self.run_deploy(fail=fail)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('stop -t', commands)
                self.assertIn('IMAGE_TAG=v0.20.2', env)

    def test_migration_failure_does_not_start_application_or_roll_back_schema(self):
        result, commands, _, _ = self.run_deploy(fail='run --rm migrate')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('up -d --wait', commands)
        self.assertIn('No automatic schema rollback', result.stderr)

    def test_older_and_invalid_tags_do_not_touch_docker(self):
        for tag in ['v0.20.1', 'main', 'v1.2.3; echo secret']:
            result, commands, env, _ = self.run_deploy(tag=tag)
            self.assertEqual(commands, '')
            self.assertIn('IMAGE_TAG=v0.20.2', env)

if __name__ == '__main__':
    unittest.main()
