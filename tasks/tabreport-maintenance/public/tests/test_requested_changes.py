import csv
import io
import subprocess
import sys
import unittest

from tabreport.csvio import RowError, parse_minutes, read_records
from tabreport.model import Record, TeamSummary, select_records, summarize
from tabreport.render import _markdown_cell, render_csv, render_markdown


class RequestedChanges(unittest.TestCase):
    def test_whitespace_data_rows_before_field_count(self):
        source = "team,item,minutes,status\n , \n\t\n,,,\nA,x,3,open\n"
        self.assertEqual(read_records(io.StringIO(source)), [Record("A", "x", 3, "open")])
        with self.assertRaises(RowError):
            read_records(io.StringIO("team,item,minutes,status\n ,x, , \n"))

    def test_hours_minutes_and_rejections(self):
        for value, expected in [(" 2:05 ", 125), ("00:09", 9), ("0:00", 0), ("123:59", 7439)]:
            self.assertEqual(parse_minutes(value), expected)
        for value in ["2:5", "2:60", "2:005", ":05", "2 :05", "2: 05", "+2:05", "２:05", "2:０５", "1:2:03"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_minutes(value)
        self.assertEqual(read_records(io.StringIO("team,item,minutes,status\nA,x,1:02,done\n"))[0].minutes, 62)

    def test_casefold_selection_without_group_merging(self):
        rows = [Record("Ops", "a", 1, "open"), Record("ops", "b", 2, "done"),
                Record("Straße", "c", 3, "done")]
        selected = select_records(rows, team="OPS")
        self.assertEqual(selected, rows[:2])
        self.assertEqual([group.team for group in summarize(selected)], ["Ops", "ops"])
        self.assertEqual(select_records(rows, team="STRASSE"), [rows[2]])
        self.assertEqual(select_records(rows, team="OPS", status="done"), [rows[1]])
        self.assertEqual(select_records(rows, team=" OPS"), [])

    def test_minutes_sort_api_and_cli(self):
        rows = [Record("b", "x", 4, "open"), Record("a", "x", 9, "done"),
                Record("A", "x", 9, "open"), Record("b", "y", 8, "done")]
        self.assertEqual([group.team for group in summarize(rows, sort_by="minutes")], ["b", "A", "a"])
        result = subprocess.run([sys.executable, "-m", "tabreport", "-", "--format", "markdown", "--sort", "minutes"],
                                input="team,item,minutes,status\nA,x,2,open\nB,y,8,done\n",
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[2:],
                         ["| B | 1 | 8 | 1 | 0 |", "| A | 1 | 2 | 0 | 1 |", "| TOTAL | 2 | 10 | 1 | 1 |"])

    def test_markdown_escaping(self):
        raw = "A\\B|C\r\nD\rE\nF"
        escaped = "A\\\\B\\|C<br>D<br>E<br>F"
        self.assertEqual(_markdown_cell(raw), escaped)
        self.assertEqual(_markdown_cell("\\|"), "\\\\\\|")
        self.assertEqual(_markdown_cell("<tag>&_*"), "<tag>&_*")
        report = render_markdown([TeamSummary(raw, 1, 2, 0, 1)], include_total=False)
        self.assertEqual(report.splitlines()[2], "| " + escaped + " | 1 | 2 | 0 | 1 |")

    def test_csv_lf_terminators_and_quoting(self):
        groups = [TeamSummary('A,"B\nC', 1, 2, 0, 1)]
        output = render_csv(groups, include_total=False)
        self.assertEqual(output, 'team,rows,minutes,done,open\n"A,""B\nC",1,2,0,1\n')
        self.assertEqual(list(csv.reader(io.StringIO(output)))[1][0], groups[0].team)
        self.assertEqual(render_csv([], include_total=False), "team,rows,minutes,done,open\n")
        self.assertEqual(render_csv([]), "team,rows,minutes,done,open\nTOTAL,0,0,0,0\n")


if __name__ == "__main__":
    unittest.main()
