import json
import subprocess
import sys
import unittest

from placement.allocator import allocate
from placement.loader import load


class RegressionTests(unittest.TestCase):
    def test_full_catalog_ordering_and_feasibility(self):
        workers, compute, storage = load()
        expected_standard = dict(zip(sorted(compute), [
            "atlas", "birch", "atlas", "drift", "cedar", "birch",
            "drift", "cedar", "cedar", "drift", "ember", "ember",
            "fjord", "grove", "grove", "ember", "fjord", "grove",
        ]))
        expected_reserve = dict(zip(sorted(compute), [
            "atlas", "birch", "atlas", "ember", "cedar", "birch",
            "ember", "cedar", "cedar", "fjord", "ember", "grove",
            "fjord", "grove", "grove", "harbor", "fjord", "harbor",
        ]))
        for profile, expected in (("standard", expected_standard),
                                  ("reserve", expected_reserve)):
            with self.subTest(profile=profile):
                services = set(compute)
                result = allocate(services, profile)
                self.assertEqual(result, expected)
                self.assertEqual(services, set(compute))
                self.assertEqual(allocate(services, profile), result)
                self.assertEqual(set(result), services)
                for service, worker in result.items():
                    self.assertIn(worker, compute[service]["compute_workers"])
                    self.assertIn(worker, storage[service]["storage_workers"])
                    self.assertIn(worker, workers["profiles"][profile]["enabled_workers"])
                for worker, data in workers["workers"].items():
                    self.assertLessEqual(list(result.values()).count(worker), data["slots"])

    def test_ordering_against_exhaustive_small_subset(self):
        workers, compute, storage = load()
        services = {"api", "audit", "billing", "catalog", "dispatch"}
        ordered = sorted(services)
        for profile in workers["profiles"]:
            enabled = workers["profiles"][profile]["enabled_workers"]
            candidates = []

            def enumerate_valid(index, mapping):
                if index == len(ordered):
                    candidates.append(tuple(mapping[s] for s in ordered))
                    return
                service = ordered[index]
                for worker in enabled:
                    if (worker in compute[service]["compute_workers"]
                            and worker in storage[service]["storage_workers"]
                            and list(mapping.values()).count(worker)
                            < workers["workers"][worker]["slots"]):
                        mapping[service] = worker
                        enumerate_valid(index + 1, mapping)
                        del mapping[service]

            enumerate_valid(0, {})
            result = allocate(services, profile)
            self.assertEqual(tuple(result[s] for s in ordered), min(candidates))

    def test_cli(self):
        for args, expected in ((["--profile", "standard"], {}),
                               (["--profile", "reserve", "audit", "api", "api"],
                                {"api": "atlas", "audit": "birch"})):
            result = subprocess.run([sys.executable, "-m", "placement", *args],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            self.assertEqual(len(result.stdout.splitlines()), 1)
            self.assertEqual(json.loads(result.stdout), expected)
        for args in (["--profile", "unknown"],
                     ["--profile", "standard", "unknown"],
                     ["--profile"], ["--wat"],
                     ["--prof", "standard"]):
            result = subprocess.run([sys.executable, "-m", "placement", *args],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr)
            self.assertNotIn("Traceback", result.stderr)
