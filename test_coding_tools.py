"""Focused safety tests for V1.1 controlled coding tools."""
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

import coding_tools
import repository_tools


class CodingToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'approved'
        self.root.mkdir()
        (self.root / 'app.py').write_text('label = "old"\n', encoding='utf-8')
        (self.root / 'binary.db').write_bytes(b'\x00')
        (self.root / '.git').mkdir()
        (self.root / '.git' / 'config').write_text('secret', encoding='utf-8')
        self.root_patch = patch.object(repository_tools, 'ALLOWED_ROOTS', (self.root,))
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def proposal(self):
        return {'summary': 'Update label', 'changes': [
            {'path': 'app.py', 'expected': 'label = "old"', 'replacement': 'label = "new"'}
        ]}

    def test_preview_does_not_modify_and_generates_diff(self):
        patch_data = coding_tools.prepare_patch(self.proposal())
        self.assertIn('-label = "old"', patch_data['diff'])
        self.assertIn('+label = "new"', patch_data['diff'])
        self.assertEqual((self.root / 'app.py').read_text(encoding='utf-8'), 'label = "old"\n')

    def test_apply_and_stale_detection(self):
        patch_data = coding_tools.prepare_patch(self.proposal())
        coding_tools.apply_patch(patch_data)
        self.assertEqual((self.root / 'app.py').read_text(encoding='utf-8'), 'label = "new"\n')
        stale = coding_tools.prepare_patch({'summary': 'again', 'changes': [
            {'path': 'app.py', 'expected': 'label = "new"', 'replacement': 'label = "later"'}
        ]})
        (self.root / 'app.py').write_text('label = "changed elsewhere"\n', encoding='utf-8')
        with self.assertRaisesRegex(coding_tools.CodingToolError, 'stale'):
            coding_tools.apply_patch(stale)

    def test_rejecting_or_invalid_targets_cannot_write(self):
        (self.root / 'credentials.json').write_text('{"value": "old"}\n', encoding='utf-8')
        for path in ('../outside.py', 'C:/outside.py', '.git/config', 'binary.db', 'credentials.json'):
            with self.subTest(path=path):
                with self.assertRaises((coding_tools.CodingToolError, repository_tools.RepositoryToolError)):
                    coding_tools.prepare_patch({'changes': [{'path': path, 'expected': 'x', 'replacement': 'y'}]})

    def test_fixed_test_runner_has_no_model_command_parameter(self):
        with patch('coding_tools.subprocess.run') as run:
            run.return_value.stdout = 'ok\n'
            run.return_value.stderr = ''
            run.return_value.returncode = 0
            result = coding_tools.run_tests()
        self.assertTrue(result['passed'])
        command = run.call_args.args[0]
        self.assertEqual(command[1:], ['-B', '-m', 'unittest', 'discover'])

    def test_test_runner_timeout_and_output_cap(self):
        with patch('coding_tools.subprocess.run') as run:
            run.return_value.stdout = 'x' * (coding_tools.TEST_OUTPUT_LIMIT + 20)
            run.return_value.stderr = ''
            run.return_value.returncode = 1
            result = coding_tools.run_tests()
        self.assertFalse(result['passed'])
        self.assertTrue(result['truncated'])

    def test_test_runner_failure_and_timeout(self):
        with patch('coding_tools.subprocess.run') as run:
            run.return_value.stdout = ''
            run.return_value.stderr = 'one test failed'
            run.return_value.returncode = 1
            self.assertFalse(coding_tools.run_tests()['passed'])
        with patch('coding_tools.subprocess.run', side_effect=subprocess.TimeoutExpired(['python'], 1, output='slow')):
            result = coding_tools.run_tests()
        self.assertTrue(result['timed_out'])
        self.assertFalse(result['passed'])


if __name__ == '__main__':
    unittest.main()
