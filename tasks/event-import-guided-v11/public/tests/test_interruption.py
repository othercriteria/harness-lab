"""An interrupted source must leave the store ready for another import."""
import unittest

from eventlog.importer import import_events
from eventlog.store import EventStore


class SourceInterruptionExample(unittest.TestCase):
    def test_source_interruption_rolls_back_and_store_remains_usable(self):
        for error_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(error_type=error_type.__name__):
                store = EventStore(":memory:")
                try:
                    import_events(['{"id":"prior","kind":"sale","value":1}'], store)
                    error = error_type("source interrupted")

                    def lines():
                        yield '{"id":"pending","kind":"sale","value":2}'
                        raise error

                    with self.assertRaises(error_type) as caught:
                        import_events(lines(), store)
                    self.assertIs(caught.exception, error)
                    self.assertFalse(store.connection.in_transaction)
                    self.assertIsNone(store.get("pending"))
                    self.assertEqual(store.get("prior"),
                                     {"id": "prior", "kind": "sale", "value": 1})
                    report = import_events(
                        ['{"id":"next","kind":"sale","value":3}'], store)
                    self.assertEqual(report, {"inserted": 1, "duplicates": 0,
                                              "invalid": 0, "errors": []})
                    self.assertEqual(store.count(), 2)
                finally:
                    store.close()
