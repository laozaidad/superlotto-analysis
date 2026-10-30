"""公共数据刷新与同次Pages发布的关键工作流契约。"""
from pathlib import Path
import shlex
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class RefreshWorkflowTests(unittest.TestCase):
    def setUp(self):
        # BaseLoader保留on/true为字符串，避免YAML 1.1将on当成布尔键。
        self.workflow = yaml.load((ROOT / '.github/workflows/pages.yml').read_text(), Loader=yaml.BaseLoader)
        self.jobs = self.workflow['jobs']
        self.build = self.jobs['validate-and-package']
        self.steps = self.build['steps']

    def step(self, name):
        return next(step for step in self.steps if step.get('name') == name)

    def test_daily_utc_schedule_and_manual_opt_out(self):
        trigger = self.workflow['on']
        self.assertEqual(trigger['schedule'], [{'cron': '30 14,23 * * *'}])
        self.assertEqual(sorted((hour + 8) % 24 for hour in (14, 23)), [7, 22])
        self.assertEqual(trigger['push']['branches'], ['main'])
        toggle = trigger['workflow_dispatch']['inputs']['refresh_history']
        self.assertEqual((toggle['type'], toggle['default']), ('boolean', 'true'))
        self.assertEqual(self.step('Check and stage public history additions')['if'],
                         "github.event_name != 'workflow_dispatch' || inputs.refresh_history")

    def test_serial_main_checkout_and_scoped_permissions(self):
        self.assertEqual(self.workflow['concurrency'], {'group': 'github-pages', 'cancel-in-progress': 'false'})
        self.assertEqual(self.steps[0]['with']['ref'], 'main')
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(self.build['permissions'], {'contents': 'write', 'pages': 'read'})
        self.assertEqual(self.jobs['deploy']['permissions'], {'pages': 'write', 'id-token': 'write'})
        for job in self.jobs.values():
            self.assertGreater(int(job['timeout-minutes']), 0)

    def test_refresh_validation_commit_package_order_and_no_failure_bypass(self):
        names = [step.get('name') for step in self.steps]
        ordered = ['Check and stage public history additions', 'Validate Python model and exporter',
                   'Validate website', 'Verify browser runtime model and data',
                   'Commit only validated public data', 'Upload only public website files']
        self.assertEqual([names.index(name) for name in ordered], sorted(names.index(name) for name in ordered))
        for step in self.steps:
            self.assertNotIn('continue-on-error', step)
        refresh = self.step('Check and stage public history additions')
        self.assertEqual(refresh['shell'], 'bash')  # 显式bash含pipefail，tee不掩盖下载失败。
        self.assertIn('python3 scripts/update_history.py --site-dir site', refresh['run'])

    def test_exact_public_file_allowlist_no_force_and_no_empty_commit(self):
        command = self.step('Commit only validated public data')['run']
        flattened = command.replace('\\\n', ' ')
        add = next(line for line in flattened.splitlines() if line.strip().startswith('git add '))
        self.assertEqual(set(shlex.split(add)[3:]), {
            'site/data/snapshot.json', 'site/runtime/history.csv', 'site/runtime/manifest.json',
            'site/runtime/model.py', 'site/runtime/research.py', 'site/runtime/conditional_core.py',
        })
        self.assertNotIn('--force', command)
        self.assertNotIn('--allow-empty', command)
        self.assertIn('if ! git diff --cached --quiet; then', command)
        self.assertIn('git push origin HEAD:main', command)
        self.assertLess(command.index('git ls-remote'), command.index('git commit'))
        self.assertIn('test "$remote_head" = "$(git rev-parse HEAD)"', command)

    def test_same_run_deploy_recovers_even_after_prior_deploy_failure(self):
        release = self.step('Record actual artifact revision')
        self.assertIn('site_commit=$(git rev-parse HEAD)', release['run'])
        self.assertIn('sha256sum site/runtime/manifest.json site/runtime/history.csv', release['run'])
        for name in ['Configure Pages', 'Upload only public website files']:
            self.assertNotIn('if', self.step(name))
        deploy = self.jobs['deploy']
        self.assertEqual(deploy['needs'], 'validate-and-package')
        self.assertNotIn('if', deploy)
        guard = deploy['steps'][0]
        self.assertEqual(guard['env']['EXPECTED_COMMIT'], '${{ needs.validate-and-package.outputs.site_commit }}')
        self.assertIn('test "$remote_head" = "$EXPECTED_COMMIT"', guard['run'])
        self.assertTrue(deploy['steps'][1]['uses'].startswith('actions/deploy-pages@'))

    def test_all_embedded_shell_scripts_parse(self):
        for job in self.jobs.values():
            for step in job['steps']:
                if 'run' in step:
                    result = subprocess.run(['bash', '-n'], input=step['run'], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, f"{step.get('name')}: {result.stderr}")


if __name__ == '__main__':
    unittest.main()
