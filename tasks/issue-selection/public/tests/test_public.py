import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path.cwd() / 'scripts/export_issue_context.py'
FAKE_GH = '''#!/bin/python3
import json, sys
command = sys.argv[2]
number = int(sys.argv[3]) if command == 'view' else 4
row = dict(number=number, title='Example', state='OPEN', body='Text',
           url='https://example.invalid/issue', updatedAt='today',
           labels=[{'name':'z'}, {'name':'a'}])
print(json.dumps(row if command == 'view' else [row]))
'''


class IssueExport(unittest.TestCase):
    def invoke(self, *args):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh = root / 'gh'
            gh.write_text(FAKE_GH.replace('#!/bin/python3', '#!' + sys.executable))
            gh.chmod(0o755)
            output = root / 'packet.json'
            result = subprocess.run([sys.executable, str(SCRIPT), 'example/repo', str(output), *args],
                                    env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH']},
                                    capture_output=True, text=True)
            return result.returncode, json.loads(output.read_text()) if output.exists() else None

    def test_all(self):
        status, packet = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual(packet['issues'][0]['labels'], ['a', 'z'])

    def test_selected(self):
        status, packet = self.invoke('--issue', '007', '--issue', '2', '--issue', '7')
        self.assertEqual(status, 0)
        self.assertEqual([row['number'] for row in packet['issues']], [2, 7])
        self.assertEqual(packet['scope'], 'Selected issue titles, bodies and label names. Comments and PRs excluded.')

    def test_signed_number(self):
        status, packet = self.invoke('--issue', '+7')
        self.assertNotEqual(status, 0)
        self.assertIsNone(packet)
