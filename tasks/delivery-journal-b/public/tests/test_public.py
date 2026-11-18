import copy
import unittest
from delivery import advance

class MemoryStore:
    def __init__(self): self.records = {}
    def load(self, key): return copy.deepcopy(self.records.get(key))
    def save(self, key, record): self.records[key] = copy.deepcopy(record)

class SuccessfulRemote:
    def __init__(self): self.applications = []
    def apply(self, request_id, payload):
        if not any(key == request_id for key, _ in self.applications):
            self.applications.append((request_id, payload))

class PublicTests(unittest.TestCase):
    def test_first_and_repeated_completion(self):
        store, remote = MemoryStore(), SuccessfulRemote()
        job = {"id": "invoice-1", "payload": "send receipt"}
        self.assertEqual(advance(job, store, remote), "done")
        self.assertEqual(advance(job, store, remote), "done")
        self.assertEqual(remote.applications, [("invoice-1", "send receipt")])
        self.assertEqual(job, {"id": "invoice-1", "payload": "send receipt"})

    def test_payload_mismatch(self):
        store, remote = MemoryStore(), SuccessfulRemote()
        self.assertEqual(advance({"id": "x", "payload": "a"}, store, remote), "done")
        before = copy.deepcopy(store.records)
        with self.assertRaises(ValueError): advance({"id": "x", "payload": "b"}, store, remote)
        self.assertEqual(store.records, before)
        self.assertEqual(remote.applications, [("x", "a")])

    def test_independent_jobs(self):
        store, remote = MemoryStore(), SuccessfulRemote()
        for key in ("a", "b", "a", "b"):
            self.assertEqual(advance({"id": key, "payload": "same"}, store, remote), "done")
        self.assertEqual(remote.applications, [("a", "same"), ("b", "same")])
