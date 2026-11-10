import csv
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tabreport.cli import main
from tabreport.csvio import RowError, parse_minutes, read_records, write_records
from tabreport.model import (
    Record,
    TeamSummary,
    report_rows,
    select_records,
    summarize,
    totals,
)
from tabreport.render import render_csv, render_markdown, render_report, render_text


class Compatibility(unittest.TestCase):
    def test_integer_minutes(self):
        for value, expected in [("0", 0), (" 007 ", 7), ("120", 120)]:
            self.assertEqual(parse_minutes(value), expected)
        for value in ["", "-1", "+1", "1.0", "１２", "1 2"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_minutes(value)

    def test_reordered_headers_quotes_and_stream_ownership(self):
        stream = io.StringIO('\n status , item , minutes , team \ndone,"a,b", 7 , Ops \n')
        self.assertEqual(read_records(stream), [Record("Ops", "a,b", 7, "done")])
        self.assertFalse(stream.closed)
        output = io.StringIO(newline="")
        write_records([Record("Ops", "a,b", 7, "done")], output)
        self.assertEqual(output.getvalue(), 'team,item,minutes,status\nOps,"a,b",7,done\n')
        self.assertFalse(output.closed)

    def test_header_errors_and_header_only(self):
        for text in ["", "team,item,minutes,team\n", "team,item,minutes\n",
                     "team,item,minutes,status,extra\n", "   \nteam,item,minutes,status\n"]:
            with self.subTest(text=text), self.assertRaises(RowError):
                read_records(io.StringIO(text))
        self.assertEqual(read_records(io.StringIO("team,item,minutes,status\n")), [])

    def test_data_validation_and_multiline_line_number(self):
        header = "team,item,minutes,status\n"
        for row in [",x,1,open\n", "A,,1,open\n", "A,x,1,OPEN\n", "A,x,1\n",
                    'A,"unclosed,1,open\n']:
            with self.subTest(row=row), self.assertRaises(RowError):
                read_records(io.StringIO(header + row))
        with self.assertRaises(RowError) as caught:
            read_records(io.StringIO(header + 'A,"two\nlines",oops,open\n'))
        self.assertEqual(caught.exception.line, 3)
        self.assertTrue(caught.exception.detail)

    def test_selection_preserves_order_and_status(self):
        rows = [Record("B", "one", 2, "open"), Record("A", "two", 3, "done")]
        self.assertEqual(select_records(iter(rows)), rows)
        self.assertEqual(select_records(rows, status="done"), [rows[1]])
        self.assertEqual(select_records(rows, team=" A"), [])
        with self.assertRaises(ValueError):
            select_records(rows, status="DONE")
        self.assertEqual(rows[0].item, "one")

    def test_aggregation_exact_labels_and_default_order(self):
        rows = [Record("ops", "a", 7, "open"), Record("Ops", "b", 2, "done"),
                Record("Ops", "c", 3, "open"), Record("Alpha", "d", 9, "done")]
        groups = summarize(iter(rows))
        self.assertEqual(groups, [TeamSummary("Alpha", 1, 9, 1, 0),
                                  TeamSummary("Ops", 2, 5, 1, 1),
                                  TeamSummary("ops", 1, 7, 0, 1)])
        self.assertEqual(groups[1].completion_percent, 50)
        self.assertEqual(TeamSummary("x", 3, 0, 1, 2).completion_percent, 33)
        with self.assertRaises(ValueError):
            summarize(rows, sort_by="unknown")

    def test_total_and_empty(self):
        groups = [TeamSummary("TOTAL", 1, 3, 1, 0)]
        self.assertEqual([row.team for row in report_rows(iter(groups))], ["TOTAL", "TOTAL"])
        self.assertEqual(report_rows(groups, include_total=False), groups)
        self.assertEqual(totals([]), TeamSummary("TOTAL", 0, 0, 0, 0))
        self.assertEqual(totals([]).completion_percent, 0)
        self.assertEqual(len(groups), 1)

    def test_text_layout(self):
        groups = [TeamSummary("A", 1, 12, 1, 0)]
        self.assertEqual(render_text(groups, include_total=False),
                         "Team  Rows  Minutes  Done  Open\n"
                         "----  ----  -------  ----  ----\n"
                         "A        1       12     1     0\n")
        self.assertIn("A B C D", render_text([TeamSummary("A\r\nB\rC\nD", 1, 0, 0, 1)]))

    def test_simple_markdown_and_csv_fields(self):
        groups = [TeamSummary('A,"B', 1, 12, 1, 0)]
        self.assertEqual(render_markdown([], include_total=False),
                         "| Team | Rows | Minutes | Done | Open |\n"
                         "| :--- | ---: | ---: | ---: | ---: |\n")
        parsed = list(csv.reader(io.StringIO(render_csv(groups))))
        self.assertEqual(parsed, [["team", "rows", "minutes", "done", "open"],
                                  ['A,"B', "1", "12", "1", "0"],
                                  ["TOTAL", "1", "12", "1", "0"]])
        self.assertEqual(render_report(iter(groups)), render_text(groups))
        with self.assertRaises(ValueError):
            render_report(groups, format="unknown")

    def test_cli_stdin_and_error(self):
        out, err = io.StringIO(), io.StringIO()
        code = main(["-", "--format", "markdown", "--status", "done", "--no-total"],
                    stdin=io.StringIO("team,item,minutes,status\nA,x,3,done\nB,y,8,open\n"),
                    stdout=out, stderr=err)
        self.assertEqual(code, 0)
        self.assertIn("| A | 1 | 3 | 1 | 0 |", out.getvalue())
        self.assertNotIn("TOTAL", out.getvalue())
        self.assertEqual(err.getvalue(), "")
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(main(["-"], stdin=io.StringIO("bad\n"), stdout=out, stderr=err), 2)
        self.assertEqual(out.getvalue(), "")
        self.assertTrue(err.getvalue().startswith("error:"))

    def test_module_cli_file_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "in.csv", Path(directory) / "out.md"
            source.write_text("team,item,minutes,status\nÉquipe,x,3,done\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "tabreport", str(source),
                                     "--format", "markdown", "--output", str(destination)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("| Équipe | 1 | 3 | 1 | 0 |", destination.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
