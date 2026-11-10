"""Sandbox-only canonical runner; never import candidate code on the host.

Invocation: /bin/python3 -I -S /evaluation/canonical_runner.py
Trusted evaluator copies canonical/tests.py to /evaluation/tests.py.
"""

import io
import json
import runpy
import sys
import unittest

TEST_NAMES = [
    "test_bold",
    "test_bold_and_italic",
    "test_header_1",
    "test_header_1_bold",
    "test_header_2",
    "test_header_2_italic",
    "test_italic",
    "test_italic_multiple",
    "test_no_conversion",
    "test_no_conversion_pound",
]

sys.path.insert(0, "/workspace")
namespace = runpy.run_path("/evaluation/tests.py")
suite = unittest.TestSuite(
    unittest.FunctionTestCase(namespace[name]) for name in TEST_NAMES
)
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
