import csv
import dataclasses
import io
import unittest

import tabreport
from tabreport.cli import build_parser, main
from tabreport.csvio import RowError, parse_minutes, read_records, write_records
from tabreport.model import Record, TeamSummary, select_records, summarize
from tabreport.render import _markdown_cell, render_csv, render_markdown, render_text


class Acceptance(unittest.TestCase):
    def test_blank_rows_varying_width_and_unicode_whitespace(self):
        text = 'team,item,minutes,status\n\u2003,\t,  ,,,\n" \n ",\t\nA,x,00:59,done\n'
        self.assertEqual(read_records(io.StringIO(text)), [Record('A', 'x', 59, 'done')])

    def test_blank_header_not_skipped(self):
        for row in [' , , , \n', '" "\n', ',,,,,\n']:
            with self.subTest(row=row), self.assertRaises(RowError) as caught:
                read_records(io.StringIO(row + 'team,item,minutes,status\n'))
            self.assertEqual(caught.exception.line, 1)

    def test_nonblank_wrong_width_and_line_number(self):
        header = 'team,item,minutes,status\n'
        for row in ['a\n', 'a,,,,\n', ',x,,\n']:
            with self.subTest(row=row), self.assertRaises(RowError) as caught:
                read_records(io.StringIO(header + ' ,\n' + row))
            self.assertEqual(caught.exception.line, 3)
        with self.assertRaises(RowError) as caught:
            read_records(io.StringIO(header + '\nA,"one\ntwo",1:99,done\n'))
        self.assertEqual(caught.exception.line, 4)

    def test_duration_domain(self):
        for hours in [0, 1, 17, 1007]:
            for minutes in [0, 1, 9, 10, 58, 59]:
                self.assertEqual(parse_minutes(f'\t{hours:04d}:{minutes:02d}\n'), hours * 60 + minutes)
        self.assertEqual(parse_minutes('000000'), 0)
        self.assertEqual(parse_minutes('9' * 30), int('9' * 30))

    def test_duration_rejects_near_misses(self):
        for value in ['1:', '1:0', '1:000', '1:60', '1:-1', '1:+1', '1:\t01',
                      '-0:01', '1.0:01', '١:01', '1:٠١', '1\n:01', '1:01:00',
                      '1_0', '0x10', '1e2', '1:01\x00']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_minutes(value)

    def test_csv_duration_reordered_columns(self):
        stream = io.StringIO('status,minutes,item,team\ndone, 001:09 ,"x,y", Q \n')
        self.assertEqual(read_records(stream), [Record('Q', 'x,y', 69, 'done')])
        self.assertFalse(stream.closed)

    def test_casefold_specials_and_generator(self):
        rows = [Record(name, str(i), i, 'done' if i % 2 else 'open')
                for i, name in enumerate(['ß', 'SS', 'ss', 'Σ', 'ς', 'σ', 'SS '])]
        self.assertEqual(select_records(iter(rows), team='ss'), rows[:3])
        self.assertEqual(select_records(iter(rows), team='σ'), rows[3:6])
        self.assertEqual(select_records(iter(rows), team='SS', status='done'), [rows[1]])
        self.assertEqual(select_records(rows, team=' SS'), [])
        self.assertEqual(rows[-1].team, 'SS ')

    def test_sort_aggregate_ties_and_label_identity(self):
        rows = [Record('z', 'one', 50, 'done'), Record('z', 'two', 50, 'open'),
                Record('A', 'x', 100, 'open'), Record('a', 'x', 100, 'done'),
                Record('TOTAL', 'x', 101, 'done'), Record('b', 'x', 0, 'open')]
        groups = summarize(iter(rows), sort_by='minutes')
        self.assertEqual([g.team for g in groups], ['TOTAL', 'A', 'a', 'z', 'b'])
        self.assertEqual(groups[3], TeamSummary('z', 2, 100, 1, 1))
        self.assertEqual([g.team for g in summarize(rows)], ['A', 'a', 'b', 'TOTAL', 'z'])
        self.assertEqual(summarize(iter([]), sort_by='minutes'), [])
        for sort in ['minute', 'MINUTES', '', None]:
            with self.subTest(sort=sort), self.assertRaises(ValueError):
                summarize([], sort_by=sort)

    def test_markdown_literal_order(self):
        cases = {'': '', '\\': '\\\\', '|': '\\|', '\\|\\': '\\\\\\|\\\\',
                 '\r\n\r\n\n\r': '<br><br><br><br>', '<br>&_*`': '<br>&_*`',
                 'x|y\\z\r\nq': 'x\\|y\\\\z<br>q'}
        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertEqual(_markdown_cell(original), expected)

    def test_markdown_generator_order_and_total(self):
        groups = [TeamSummary('z|', 1, 2, 1, 0), TeamSummary('A\\', 2, 3, 0, 2)]
        lines = render_markdown(iter(groups)).splitlines()
        self.assertEqual(lines[2:], ['| z\\| | 1 | 2 | 1 | 0 |',
                                    '| A\\\\ | 2 | 3 | 0 | 2 |',
                                    '| TOTAL | 3 | 5 | 1 | 2 |'])
        self.assertEqual(groups[0].team, 'z|')

    def test_csv_exact_dialect_including_carriage_return(self):
        # LF dialect deliberately leaves a lone CR unquoted; do not invent normalization.
        groups = [TeamSummary(label, 1, 2, 0, 1)
                  for label in ['a\rb', 'a\nb', 'a\r\nb', 'a,b', 'a"b', 'a\\|b']]
        expected = io.StringIO(newline='')
        writer = csv.writer(expected, lineterminator='\n')
        writer.writerow(['team', 'rows', 'minutes', 'done', 'open'])
        writer.writerows([[g.team, 1, 2, 0, 1] for g in groups])
        self.assertEqual(render_csv(iter(groups), include_total=False), expected.getvalue())

    def test_other_formats_and_writer_unchanged(self):
        group = TeamSummary('A\\|B\r\nC', 1, 2, 1, 0)
        self.assertIn('A\\|B C', render_text([group], include_total=False))
        output = io.StringIO(newline='')
        write_records(iter([Record('A\\|', 'x\ny', 62, 'done')]), output)
        self.assertEqual(output.getvalue(), 'team,item,minutes,status\nA\\|,"x\ny",62,done\n')
        self.assertFalse(output.closed)

    def test_immutable_exports(self):
        for name in ['Record', 'TeamSummary', 'read_records', 'write_records',
                     'select_records', 'summarize', 'render_report']:
            self.assertTrue(hasattr(tabreport, name), name)
        for item in [Record('A', 'x', 1, 'open'), TeamSummary('A', 1, 1, 0, 1)]:
            with self.assertRaises(dataclasses.FrozenInstanceError):
                item.team = 'changed'

    def test_cli_combined_and_parser(self):
        out, err = io.StringIO(), io.StringIO()
        source = 'team,item,minutes,status\nStraße,x,1:00,done\nSTRASSE,y,1:01,done\nStraße,z,9:00,open\n , \n'
        code = main(['-', '--team', 'strasse', '--status', 'done', '--sort', 'minutes',
                     '--format', 'csv', '--no-total'], stdin=io.StringIO(source), stdout=out, stderr=err)
        self.assertEqual((code, err.getvalue()), (0, ''))
        self.assertEqual(out.getvalue(), 'team,rows,minutes,done,open\nSTRASSE,1,61,1,0\nStraße,1,60,1,0\n')
        self.assertEqual(build_parser().parse_args(['-', '--sort', 'minutes']).sort, 'minutes')

    def test_cli_error_does_not_emit_partial_report(self):
        for row in ['A,x,2:60,done\n', ',x,2:00,done\n', 'A,x,2:00,DONE\n']:
            out, err = io.StringIO(), io.StringIO()
            code = main(['-', '--format', 'csv'],
                        stdin=io.StringIO('team,item,minutes,status\nB,y,1,open\n' + row),
                        stdout=out, stderr=err)
            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), '')
            self.assertTrue(err.getvalue().startswith('error:'))
