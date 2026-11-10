import copy
import json
import runpy
import unittest
from interfaces import DeliveryUncertain, ProcessCrash

DEDUPLICATE = True

class World:
    def __init__(self, faults=(), crash_at=None):
        self.records = {}
        self.effects = []
        self.faults = list(faults)
        self.crash_at = crash_at
        self.boundaries = 0
        self.calls = 0
        self.failed = False

    def boundary(self):
        self.boundaries += 1
        if self.boundaries == self.crash_at:
            self.crash_at = None
            self.failed = True
            raise ProcessCrash()

    def load(self, key):
        self.boundary()
        value = copy.deepcopy(self.records.get(key))
        self.boundary()
        return value

    def save(self, key, value):
        self.boundary()
        json.dumps(value, allow_nan=False)
        self.records[key] = copy.deepcopy(value)
        self.boundary()

    def apply(self, request_id, payload):
        self.calls += 1
        self.boundary()
        fault = self.faults.pop(0) if self.faults else None
        if fault == "before":
            self.failed = True
            raise DeliveryUncertain("unknown outcome")
        existing = [(key, text) for key, text in self.effects if key == request_id]
        if not DEDUPLICATE or not existing:
            self.effects.append((request_id, payload))
        elif existing[0][1] != payload:
            raise AssertionError("Remote ID rebound to another payload")
        if fault == "after":
            self.failed = True
            raise DeliveryUncertain("unknown outcome")
        self.boundary()
        return None

    def invoke(self, testcase, job):
        # A fresh module namespace each time; only journal/remote world survives.
        advance = runpy.run_path("/workspace/delivery.py")["advance"]
        before = copy.deepcopy(job)
        calls_before = self.calls
        self.failed = False
        try:
            result = advance(job, self, self)
        except ProcessCrash:
            result = "crashed"
        testcase.assertEqual(job, before)
        testcase.assertLessEqual(self.calls - calls_before, 1)
        testcase.assertIn(result, ("done", "retry", "crashed"))
        effects = [payload for key, payload in self.effects if key == job["id"]]
        testcase.assertLessEqual(len(effects), 1, "duplicate application")
        if result == "done":
            testcase.assertEqual(effects, [job["payload"]], "false completion")
        if not self.failed:
            testcase.assertEqual(result, "done", "fault-free invocation deferred work")
        return result

class AcceptanceTests(unittest.TestCase):
    def complete(self, world, job):
        # Consume injected finite failures, then require fault-free completion.
        for _ in range(len(world.faults) + 3):
            if world.invoke(self, job) == "done":
                world.crash_at = None
                break
        else:
            self.fail("did not finish after failures ceased")
        for _ in range(2):
            self.assertEqual(world.invoke(self, job), "done")
        self.assertEqual([p for k,p in world.effects if k == job["id"]], [job["payload"]])

    def test_uncertain_before_application(self):
        self.complete(World(["before"]), {"id":"x", "payload":"value"})

    def test_lost_acknowledgement(self):
        self.complete(World(["after"]), {"id":"x", "payload":"value"})

    def test_mixed_uncertainties(self):
        self.complete(World(["before", "after", "after", "before"]), {"id":"x", "payload":"value"})

    def test_crash_at_each_operation_boundary(self):
        for boundary in range(1, 13):
            with self.subTest(boundary=boundary):
                world = World(crash_at=boundary)
                self.complete(world, {"id":"x", "payload":"value"})

    def test_interleaved_jobs_with_uncertainty(self):
        world = World(["after", "before"])
        a = {"id":"a", "payload":"alpha"}
        b = {"id":"b", "payload":"beta"}
        world.invoke(self, a)
        world.invoke(self, b)
        self.complete(world, a)
        self.complete(world, b)
        self.assertCountEqual(world.effects, [("a","alpha"), ("b","beta")])

    def test_pending_payload_mismatch_when_recorded(self):
        world = World(["before"])
        world.invoke(self, {"id":"x", "payload":"first"})
        if "x" in world.records:
            before, calls = copy.deepcopy(world.records), world.calls
            advance = runpy.run_path("/workspace/delivery.py")["advance"]
            with self.assertRaises(ValueError):
                advance({"id":"x", "payload":"second"}, world, world)
            self.assertEqual(world.records, before)
            self.assertEqual(world.calls, calls)

    def test_unicode_and_same_payload_distinct_ids(self):
        world = World()
        for key in ("δ", "delivery/2", "δ", "delivery/2"):
            self.complete(world, {"id":key, "payload":"héllo\nworld"})
        self.assertEqual(len(world.effects), 2)
