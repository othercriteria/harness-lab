"""Outer archive observations and returned-file comparisons; no host candidate execution."""
import hashlib
import io
import json
import stat
import struct
import warnings
import zipfile

DRIVER = b'''import dataclasses,json,sys
from pathlib import Path
sys.path.insert(0, '/workspace')
from bundle_reader import inspect_bundle,extract_bundle
r={}
for item in json.loads(Path('probe/inputs.json').read_text()):
    name=item['name']; data=Path('probe/'+name+'.zip').read_bytes()
    dest=Path('probe/output')/name
    try:
        if item.get('extract'):
            value=extract_bundle(data,dest,**item.get('limits',{}))
        else:
            value=inspect_bundle(data,**item.get('limits',{}))
        r[name]={'value':dataclasses.asdict(value)}
    except Exception as error:
        r[name]={'error':type(error).__name__}
print(json.dumps(r))
'''


def archive(entries, method=zipfile.ZIP_DEFLATED):
    out = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(out, 'w') as z:
            for name, data, kind in entries:
                info = zipfile.ZipInfo(name)
                info.compress_type = method
                info.external_attr = (kind | 0o600) << 16
                z.writestr(info, data)
    return out.getvalue()


def check(gate):
    name = 'item-' + gate.token()
    payload = ('content-' + gate.token()).encode() + b'\x00\xff'
    entries = [('empty/', b'', stat.S_IFDIR), ('tree/'+name, payload, stat.S_IFREG)]
    valid = archive(entries)
    cases = [dict(name='inspect'), dict(name='extract', extract=True)]
    setup = {'probe/driver.py': DRIVER,
             'probe/inputs.json': json.dumps(cases).encode(),
             'probe/inspect.zip': valid, 'probe/extract.zip': valid,
             'probe/output/.keep': b''}
    probe = gate.case('inspect-and-extract', setup, 'python -I -S probe/driver.py')
    try:
        actual = gate.json(probe)
    except (TypeError, ValueError):
        actual = {}
    expected = {'files': [{'path': 'tree/'+name, 'size': len(payload),
                           'sha256': hashlib.sha256(payload).hexdigest()}],
                'directories': ['empty', 'tree'], 'total_bytes': len(payload)}
    transport = probe.result.get('ok') is True and not probe.result.get('stderr')
    for key in ['inspect', 'extract']:
        observed = actual.get(key) if isinstance(actual, dict) else None
        gate.record(key+'_metadata', transport and observed == {'value': expected},
                    {'expected': expected, 'actual': observed})
    try:
        root = gate.path(probe.workspace, 'probe/output/extract')
        paths = sorted(str(p.relative_to(root)) for p in root.rglob('*'))
        tree_ok = (paths == ['empty', 'tree', 'tree/'+name]
                   and gate.path(probe.workspace, 'probe/output/extract/empty').is_dir()
                   and gate.read(probe, 'probe/output/extract/tree/'+name) == payload)
    except (OSError, ValueError):
        tree_ok = False
    gate.record('extracted_bytes_and_directories', transport and tree_ok,
                {'expected_paths': ['empty', 'tree', 'tree/'+name]})

    one = archive([('safe', b'abcdef', stat.S_IFREG)], zipfile.ZIP_STORED)
    damaged = one.replace(b'abcdef', b'Abcdef', 1)
    small = bytearray(one)
    central = small.index(b'PK\x01\x02')
    struct.pack_into('<I', small, 22, 3)
    struct.pack_into('<I', small, central+24, 3)
    invalid = {
        'traversal': archive([('../escape', b'x', stat.S_IFREG)]),
        'duplicate': archive([('same', b'a', stat.S_IFREG), ('same', b'b', stat.S_IFREG)]),
        'collision': archive([('a/b', b'x', stat.S_IFREG), ('a', b'x', stat.S_IFREG)]),
        'symlink': archive([('a', b'target', stat.S_IFLNK)]),
        'corrupt': damaged,
        'declared_size': bytes(small),
        'over_limit': one,
    }
    cases = [dict(name=n, extract=True, limits={'max_file_bytes': 5} if n=='over_limit' else {}) for n in invalid]
    setup = {'probe/driver.py': DRIVER, 'probe/inputs.json': json.dumps(cases).encode(),
             'probe/output/.keep': b''}
    setup.update({'probe/'+n+'.zip': data for n, data in invalid.items()})
    probe = gate.case('invalid-before-write', setup, 'python -I -S probe/driver.py')
    try:
        actual = gate.json(probe)
    except (TypeError, ValueError):
        actual = {}
    transport = probe.result.get('ok') is True and not probe.result.get('stderr')
    for names, label in [(['traversal'], 'path_rejection'),
                         (['duplicate', 'collision', 'symlink'], 'namespace_and_type_rejection'),
                         (['corrupt', 'declared_size', 'over_limit'], 'integrity_and_limits')]:
        ok = isinstance(actual, dict) and all(actual.get(n)=={'error':'BundleError'} for n in names)
        gate.record(label, transport and ok, {'actual': {n: actual.get(n) for n in names} if isinstance(actual, dict) else actual})
    try:
        root = gate.path(probe.workspace, 'probe/output')
        remaining = sorted(p.name for p in root.iterdir())
        untouched = remaining == ['.keep'] and gate.absent(probe, 'probe/escape')
    except (OSError, ValueError):
        untouched = False
    gate.record('invalid_extraction_writes_nothing', transport and untouched, {})
