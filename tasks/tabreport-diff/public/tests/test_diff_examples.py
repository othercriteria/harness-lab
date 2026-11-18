import csv
import io
import json
import unittest

from tabreport.diff import compare_records, main, render_diff
from tabreport.model import Record


class DiffExamples(unittest.TestCase):
    def test_status_change_and_zero_removal(self):
        before = [Record("A", "task", 10, "open"), Record("B", "old", 0, "done")]
        after = [Record("A", "task", 10, "done")]
        rows = compare_records(iter(before), iter(after))
        self.assertEqual(rows, [
            {"team": "A", "item": "task", "kind": "modified", "before_minutes": 10,
             "after_minutes": 10, "before_status": "open", "after_status": "done", "delta_minutes": 0},
            {"team": "B", "item": "old", "kind": "removed", "before_minutes": 0,
             "after_minutes": None, "before_status": "done", "after_status": None, "delta_minutes": 0},
        ])
        self.assertEqual(json.loads(render_diff(iter(rows))), rows)
        cells = list(csv.reader(io.StringIO(render_diff(iter(rows), format="csv"))))
        self.assertEqual(cells[2], ["B", "old", "removed", "0", "", "done", "", "0"])

    def test_unchanged_omitted_and_duplicates_rejected(self):
        row = Record("A", "x", 3, "open")
        self.assertEqual(compare_records([row], [row]), [])
        with self.assertRaises(ValueError):
            compare_records([row, row], [])

    def test_cli_rejects_two_stdin_inputs(self):
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(main(["-", "-"], stdin=io.StringIO(), stdout=out, stderr=err), 2)
        self.assertEqual(out.getvalue(), "")
        self.assertTrue(err.getvalue())

    def test_package_exports(self):
        import tabreport
        self.assertIs(tabreport.compare_records, compare_records)
        self.assertIs(tabreport.render_diff, render_diff)
