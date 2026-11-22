import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class Boundary(unittest.TestCase):
    def check_packet(self, args, large=False, existing=False):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            gh = p / "gh"
            out = p / "packet"
            gh.write_text(
                "#!"
                + sys.executable
                + "\n"
                + """import json,os,sys
from pathlib import Path
a=sys.argv[1:]
with Path(os.environ['LOG']).open('a') as f:f.write(json.dumps(a)+'\\n')
if a[:2]==['issue','view']:
 n=int(a[2]); row={'number':n,'title':'case','body':'x'*int(os.environ['SIZE']),'labels':[],'state':'CLOSED','url':'url','updatedAt':'today'}
 print(json.dumps(row))
else:print(json.dumps([{'number':n,'labels':[]} for n in range(51)]))
"""
            )
            gh.chmod(0o755)
            if existing:
                out.write_bytes(b"previous")
            log = p / "log"
            r = subprocess.run(
                [
                    sys.executable,
                    "scripts/export_issue_context.py",
                    "sample/repo",
                    str(out),
                    *args,
                ],
                capture_output=True,
                env={
                    **os.environ,
                    "LOG": str(log),
                    "SIZE": "100000" if large else "1",
                    "PATH": str(p) + ":" + os.environ["PATH"],
                },
            )
            return (
                r.returncode,
                out.read_bytes() if out.exists() else None,
                [json.loads(x) for x in log.read_text().splitlines()]
                if log.exists()
                else [],
            )

    def test_fifty_unique_plus_repeat(self):
        numbers = list(range(1, 51)) + [1]
        args = [arg for n in numbers for arg in ("--issue", str(n))]
        status, packet, calls = self.check_packet(args)
        self.assertEqual(status, 0)
        self.assertEqual(
            [r["number"] for r in json.loads(packet)["issues"]], numbers[:-1]
        )
        self.assertCountEqual([c[2] for c in calls], [str(n) for n in numbers[:-1]])

    def test_long_padding_selects_issue_seven_once(self):
        status, packet, calls = self.check_packet(
            ["--issue", "0" * 4500 + "7", "--issue", "7"]
        )
        self.assertEqual(status, 0)
        self.assertEqual([row["number"] for row in json.loads(packet)["issues"]], [7])
        self.assertEqual([call[:3] for call in calls], [["issue", "view", "7"]])

    def test_preserve_size_and_exclusive_output(self):
        s, p, _ = self.check_packet(["--issue", "3"], large=True)
        self.assertNotEqual(s, 0)
        self.assertIsNone(p)
        s, p, _ = self.check_packet(["--issue", "3"], existing=True)
        self.assertNotEqual(s, 0)
        self.assertEqual(p, b"previous")

    def test_legacy_over_limit(self):
        s, p, c = self.check_packet([])
        self.assertNotEqual(s, 0)
        self.assertIsNone(p)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0][:2], ["issue", "list"])
