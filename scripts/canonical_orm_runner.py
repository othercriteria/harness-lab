"""Sandbox-only runner for the pinned standard-library ORM test adaptation."""

import io
import json
import runpy
import sys
import unittest

sys.path.insert(0, "/workspace")
namespace = runpy.run_path("/evaluation/tests.py")
suite = unittest.defaultTestLoader.loadTestsFromTestCase(namespace["PublicTests"])
log = io.StringIO()
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
print(
    json.dumps(
        {
            "passed": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "skipped": len(result.skipped),
            "failures": len(result.failures),
            "errors": len(result.errors),
            "log": log.getvalue(),
        }
    )
)
