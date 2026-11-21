"""Read the bundled historical excerpt through the ordinary Observatory HTTP routes."""

import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from observe import EXAMPLE_ROOT, Evidence, Handler


class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.reader = Evidence(EXAMPLE_ROOT, archived_example=True)

    def get(self, route, **query):
        # Run BaseHTTPRequestHandler's actual HTTP parser, router and serializer
        # without reserving a port in portable CI.
        url = route + ("?" + urlencode(query) if query else "")
        wire = f"GET {url} HTTP/1.0\r\nHost: localhost:8765\r\n\r\n".encode()
        reader = self.reader
        output = io.BytesIO()

        class Request(Handler):
            evidence = reader

            def setup(self):
                self.rfile = io.BytesIO(wire)
                self.wfile = output

            def finish(self):
                pass

            def log_message(self, *_):
                pass

        Request(None, ("127.0.0.1", 1), SimpleNamespace(server_port=8765))
        header, body = output.getvalue().split(b"\r\n\r\n", 1)
        self.assertIn(b"200 OK", header)
        return json.loads(body)

    def test_public_routes_bind_check_patch_and_outer_review(self):
        index = self.get("/api/runs")
        self.assertEqual(index["total"], 1)
        run = self.get("/api/run", run=index["newest"])
        self.assertTrue(run["archived_example"])
        (trial,) = run["trials"]
        self.assertEqual(trial["state"], "outer review rejected")
        key = {"run": run["name"], "trial": trial["name"]}
        trace = self.get("/api/trace", **key)
        (check,) = trace["events"]
        self.assertEqual((check["id"], check["tool_name"]), ("tool-008", "run_checks"))
        self.assertEqual(check["arguments"]["command"], "python3 /tmp/check_label.py")
        self.assertIn("TOTAL FAILS: 0", check["result"]["stdout"])
        self.assertTrue(trace["summary"]["independent_checks_passed"])
        self.assertIn("rejected_trial_label", trace["diff"])
        packet = EXAMPLE_ROOT.parents[1] / "packet"
        artifact = (packet / "artifact.json").read_bytes()
        review = run["delegation"]["outer_review"]
        self.assertEqual(review, json.loads((packet / "review.json").read_bytes()))
        self.assertEqual(
            review["artifact_sha256"], hashlib.sha256(artifact).hexdigest()
        )
        diff = self.get("/api/artifact", **key, name="changes.diff")
        self.assertEqual(
            hashlib.sha256(diff["text"].encode()).hexdigest(),
            json.loads(artifact)["diff_sha256"],
        )

    def test_partial_excerpt_never_fills_gaps_from_workstation(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / "excerpt"
            shutil.copytree(EXAMPLE_ROOT.parent, copy)
            root = copy / "campaigns"
            (run,) = root.iterdir()
            (trial,) = (run / "experiment").glob("trial-*")
            (trial / "tool-008.result.json").unlink()
            (review,) = copy.glob("delegation/jobs/*/review.json")
            review.unlink()
            self.reader = Evidence(root, archived_example=True)
            detail = self.get("/api/run", run=run.name)
            self.assertEqual(
                detail["trials"][0]["state"], "outer review unavailable in excerpt"
            )
            self.assertIsNone(detail["delegation"]["outer_review"])
            (event,) = self.get("/api/trace", run=run.name, trial=trial.name)["events"]
            self.assertEqual(event["state"], "result unavailable in excerpt")
            self.assertIsNone(event["result"])
            # The same directory through the live reader retains normal job semantics.
            live = Evidence(root).run(run.name)
            self.assertFalse(live["archived_example"])
            self.assertEqual(live["trials"][0]["state"], "awaiting outer review")
