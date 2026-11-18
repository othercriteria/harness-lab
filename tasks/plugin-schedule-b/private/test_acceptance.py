import json, subprocess, sys, unittest
from pipeline.planner import plan
CASES = [{'features': [], 'target': 'audit', 'expected': ['decode', 'audit']}, {'features': [], 'target': 'decode', 'expected': ['decode']}, {'features': [], 'target': 'export', 'expected': ['decode', 'audit', 'redact', 'store', 'export']}, {'features': [], 'target': 'redact', 'expected': ['decode', 'redact']}, {'features': [], 'target': 'store', 'expected': ['decode', 'redact', 'store']}, {'features': ['private'], 'target': 'audit', 'expected': ['decode', 'audit']}, {'features': ['private'], 'target': 'decode', 'expected': ['decode']}, {'features': ['private'], 'target': 'export', 'expected': ['decode', 'audit', 'redact', 'store', 'export']}, {'features': ['private'], 'target': 'redact', 'expected': ['decode', 'audit', 'redact']}, {'features': ['private'], 'target': 'store', 'expected': ['decode', 'audit', 'redact', 'store']}, {'features': ['durable'], 'target': 'audit', 'expected': ['decode', 'audit']}, {'features': ['durable'], 'target': 'decode', 'expected': ['decode']}, {'features': ['durable'], 'target': 'export', 'expected': ['decode', 'audit', 'redact', 'store', 'export']}, {'features': ['durable'], 'target': 'redact', 'expected': ['decode', 'redact']}, {'features': ['durable'], 'target': 'store', 'expected': ['decode', 'redact', 'store']}, {'features': ['private', 'durable'], 'target': 'audit', 'expected': ['decode', 'audit']}, {'features': ['private', 'durable'], 'target': 'decode', 'expected': ['decode']}, {'features': ['private', 'durable'], 'target': 'export', 'expected': ['decode', 'audit', 'redact', 'store', 'export']}, {'features': ['private', 'durable'], 'target': 'redact', 'expected': ['decode', 'audit', 'redact']}, {'features': ['private', 'durable'], 'target': 'store', 'expected': ['decode', 'audit', 'redact', 'store']}]

class Acceptance(unittest.TestCase):
    def test_all_supported_combinations(self):
        for case in CASES:
            with self.subTest(features=case["features"], target=case["target"]):
                result = plan(set(case["features"]), case["target"])
                self.assertIsInstance(result, list)
                self.assertIsNotNone(case["expected"], "Supported constraints have no valid total order")
                self.assertEqual(result, case["expected"])
    def test_repeat_and_input_preservation(self):
        for case in CASES:
            if case["expected"] is None: continue
            features = set(case["features"])
            self.assertEqual(plan(features, case["target"]), case["expected"])
            self.assertEqual(features, set(case["features"]))
            self.assertEqual(plan(features, case["target"]), case["expected"])
    def test_cli_supported_combinations(self):
        for case in CASES:
            with self.subTest(features=case["features"], target=case["target"]):
                args=[sys.executable,"-m","pipeline","--target",case["target"]]
                for feature in case["features"]: args += ["--feature",feature]
                run=subprocess.run(args,capture_output=True,text=True,timeout=1)
                self.assertEqual(run.returncode,0)
                self.assertEqual(run.stderr,"")
                self.assertEqual(len(run.stdout.splitlines()),1)
                self.assertIsNotNone(case["expected"])
                self.assertEqual(json.loads(run.stdout),case["expected"])
    def test_unknown_feature_usage(self):
        run=subprocess.run([sys.executable,"-m","pipeline","--target","decode","--feature","unknown"],capture_output=True,text=True,timeout=1)
        self.assertEqual(run.returncode,2);self.assertEqual(run.stdout,"");self.assertTrue(run.stderr.strip());self.assertNotIn("Traceback",run.stderr)
    def test_unknown_target_usage(self):
        run=subprocess.run([sys.executable,"-m","pipeline","--target","unknown"],capture_output=True,text=True,timeout=1)
        self.assertEqual(run.returncode,2);self.assertEqual(run.stdout,"");self.assertTrue(run.stderr.strip());self.assertNotIn("Traceback",run.stderr)
