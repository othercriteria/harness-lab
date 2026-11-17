import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from tabreport.diff import compare_records, main, render_diff
from tabreport.model import Record

FIELDS = ['team', 'item', 'kind', 'before_minutes', 'after_minutes',
          'before_status', 'after_status', 'delta_minutes']


class Once:
    def __init__(self, values):
        self.values = values
        self.used = False

    def __iter__(self):
        if self.used:
            raise AssertionError('iterable consumed twice')
        self.used = True
        return iter(self.values)


class SnapshotDiffTests(unittest.TestCase):
    def test_changes_and_exact_identity(self):
        before = [Record('Ops', 'x', 7, 'open'), Record('ops', 'x', 9, 'done'),
                  Record('A', 'gone', 12, 'done'), Record('B', 'same', 2, 'open')]
        after = [Record('Ops', 'x', 3, 'done'), Record('ops', 'x', 9, 'done'),
                 Record('B', 'same', 2, 'open'), Record('C', 'new', 0, 'open')]
        saved = copy.deepcopy((before, after))
        rows = compare_records(Once(before), Once(after))
        self.assertEqual([(r['team'], r['item'], r['kind'], r['delta_minutes']) for r in rows],
                         [('A', 'gone', 'removed', -12), ('C', 'new', 'added', 0), ('Ops', 'x', 'modified', -4)])
        self.assertEqual((before, after), saved)
        self.assertTrue(all(set(r) == set(FIELDS) for r in rows))
        self.assertEqual(rows[0]['before_status'], 'done')
        self.assertIsNone(rows[0]['after_status'])
        self.assertIsNone(rows[1]['before_minutes'])
        self.assertEqual(rows[1]['after_minutes'], 0)
        self.assertEqual(rows[2]['before_minutes'], 7)

    def test_ordering_rename_and_status_only(self):
        before = [Record('A', 'old', 1, 'open'), Record('B', 'x', 3, 'open')]
        after = [Record('Straße', 'x', 1, 'done'), Record('STRASSE', 'x', 1, 'done'),
                 Record('a', 'b', 1, 'open'), Record('A', 'new', 1, 'open'),
                 Record('a', 'B', 1, 'open'), Record('B', 'x', 3, 'done')]
        rows = compare_records(before, after)
        self.assertEqual([(r['team'], r['item']) for r in rows],
                         [('A', 'new'), ('A', 'old'), ('a', 'B'), ('a', 'b'),
                          ('B', 'x'), ('STRASSE', 'x'), ('Straße', 'x')])
        self.assertEqual((rows[4]['kind'], rows[4]['delta_minutes']), ('modified', 0))

    def test_duplicates_in_either_snapshot(self):
        a, b = Record('A', 'x', 1, 'open'), Record('A', 'x', 2, 'done')
        for before, after in [([a, a], []), ([], [a, b]), ([a, b], [a])]:
            with self.subTest(before=before, after=after), self.assertRaises(ValueError):
                compare_records(Once(before), Once(after))

    def test_empty_and_render_errors(self):
        self.assertEqual(compare_records([], []), [])
        self.assertEqual(json.loads(render_diff(iter([]))), [])
        empty_csv = render_diff([], format='csv')
        self.assertEqual(list(csv.reader(io.StringIO(empty_csv, newline=''))), [FIELDS])
        self.assertTrue(empty_csv.endswith('\n') and not empty_csv.endswith('\r\n'))
        with self.assertRaises(ValueError):
            render_diff([], format='markdown')

    def test_render_preserves_data_and_input_order(self):
        rows = [dict(zip(FIELDS, ['Ω,"\r\nteam', 'item\nnext', 'added', None, 0, None, 'open', 0])),
                dict(zip(FIELDS, ['A', 'z', 'removed', 5, None, 'done', None, -5]))]
        saved = copy.deepcopy(rows)
        text = render_diff(Once(rows))
        self.assertTrue(text.endswith('\n') and not text.endswith('\n\n'))
        self.assertEqual(json.loads(text), rows)
        csv_text = render_diff(Once(rows), format='csv')
        parsed = list(csv.reader(io.StringIO(csv_text, newline='')))
        self.assertEqual(parsed, [FIELDS,
                         ['Ω,"\r\nteam', 'item\nnext', 'added', '', '0', '', 'open', '0'],
                         ['A', 'z', 'removed', '5', '', 'done', '', '-5']])
        self.assertEqual(rows, saved)

    def run_main(self, argv, stdin=''):
        source, out, err = io.StringIO(stdin), io.StringIO(), io.StringIO()
        result = main(argv, stdin=source, stdout=out, stderr=err)
        self.assertFalse(source.closed or out.closed or err.closed)
        return result, out.getvalue(), err.getvalue()

    def test_cli_stdin_either_side_and_existing_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.csv'
            path.write_text('team,item,minutes,status\nA,x,1:02,open\n', encoding='utf-8')
            other = 'team,item,minutes,status\nA,x,03,done\n'
            for argv, delta in [([str(path), '-'], -59), (['-', str(path)], 59)]:
                code, out, err = self.run_main(argv, other)
                self.assertEqual(code, 0, err)
                row, = json.loads(out)
                self.assertEqual(row['delta_minutes'], delta)
                self.assertEqual(row['kind'], 'modified')

    def test_cli_output_and_empty_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            before, after, output = [Path(directory) / x for x in ('before.csv', 'after.csv', 'report.csv')]
            before.write_text('team,item,minutes,status\n', encoding='utf-8')
            after.write_text('team,item,minutes,status\n', encoding='utf-8')
            code, out, err = self.run_main([str(before), str(after), '--format', 'csv', '--output', str(output)])
            self.assertEqual(code, 0, err)
            self.assertEqual(out, '')
            data = output.read_bytes().decode('utf-8')
            self.assertEqual(list(csv.reader(io.StringIO(data, newline=''))), [FIELDS])
            self.assertTrue(data.endswith('\n') and not data.endswith('\r\n'))

    def test_invalid_input_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory:
            good, bad, output = [Path(directory) / x for x in ('good.csv', 'bad.csv', 'report.json')]
            good.write_text('team,item,minutes,status\nA,x,1,open\n', encoding='utf-8')
            for data in (b'team,item,minutes,status\nA,x,1,open\nA,x,1,open\n',
                         b'team,item,minutes,status\nA,x,1:99,open\n', b'\xff'):
                bad.write_bytes(data)
                output.write_bytes(b'old report')
                code, out, err = self.run_main([str(good), str(bad), '--output', str(output)])
                self.assertEqual(code, 2)
                self.assertEqual(out, '')
                self.assertTrue(err)
                self.assertEqual(output.read_bytes(), b'old report')

    def test_missing_input_and_output_write_error(self):
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / 'good.csv'
            good.write_text('team,item,minutes,status\n', encoding='utf-8')
            for argv in ([str(good), str(Path(directory) / 'missing.csv')],
                         [str(good), str(good), '--output', directory]):
                code, out, err = self.run_main(argv)
                self.assertEqual(code, 2)
                self.assertEqual(out, '')
                self.assertTrue(err)

    def test_stdout_write_error_returns_2_and_preserves_caller_streams(self):
        # The optional stdout is an output destination too. A valid comparison
        # must report its write failure through main's documented return value.
        class FailingOutput(io.StringIO):
            def __init__(self, error_type):
                super().__init__()
                self.error_type = error_type

            def write(self, text):
                raise self.error_type('destination write failed')

        with tempfile.TemporaryDirectory() as directory:
            after = Path(directory) / 'after.csv'
            after.write_text('team,item,minutes,status\nA,x,2,done\n', encoding='utf-8')
            for format in ('json', 'csv'):
                for error_type in (OSError, BrokenPipeError):
                    with self.subTest(format=format, error_type=error_type):
                        source = io.StringIO('team,item,minutes,status\nA,x,1,open\n')
                        out, err = FailingOutput(error_type), io.StringIO()
                        code = main(['-', str(after), '--format', format],
                                    stdin=source, stdout=out, stderr=err)
                        self.assertEqual(code, 2)
                        self.assertTrue(err.getvalue())
                        self.assertEqual(out.getvalue(), '')
                        self.assertFalse(source.closed or out.closed or err.closed)

    def test_stdout_encoding_error_uses_output_failure_contract(self):
        # A real TextIOWrapper can fail while encoding otherwise valid UTF-8
        # input. JSON may escape non-ASCII text, whereas CSV must preserve it.
        with tempfile.TemporaryDirectory() as directory:
            after = Path(directory) / 'after.csv'
            after.write_text('team,item,minutes,status\nÉ,x,1,open\n', encoding='utf-8')
            for format in ('json', 'csv'):
                with self.subTest(format=format):
                    source = io.StringIO('team,item,minutes,status\n')
                    buffer = io.BytesIO()
                    out = io.TextIOWrapper(buffer, encoding='ascii', write_through=True)
                    err = io.StringIO()
                    try:
                        code = main(['-', str(after), '--format', format],
                                    stdin=source, stdout=out, stderr=err)
                        self.assertIn(code, (0, 2) if format == 'json' else (2,))
                        if code == 2:
                            self.assertTrue(err.getvalue())
                        self.assertFalse(source.closed or out.closed or err.closed)
                    finally:
                        out.close()
