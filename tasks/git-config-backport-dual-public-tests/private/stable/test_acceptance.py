import io
import re
import unittest
import configparser as cp
import service

LEGACY = False
SORTED = True

class Acceptance(unittest.TestCase):
    def make(self, **kwargs):
        return cp.ConfigParser(**kwargs)

    def reject(self, p, key):
        out=io.StringIO('preserved')
        out.seek(0,2)
        before=dict((s,dict(p[s])) for s in p)
        try:
            p.write(out)
        except Exception as e:
            self.assertIs(type(e), ValueError if LEGACY else cp.InvalidWriteError)
            if not LEGACY:
                self.assertIsInstance(e, cp.Error)
            self.assertIn(repr(key),str(e))
        else:
            self.fail('unsafe key accepted')
        self.assertEqual(out.getvalue(),'preserved')
        self.assertEqual(out.tell(),9)
        self.assertFalse(out.closed)
        self.assertEqual(dict((s,dict(p[s])) for s in p),before)

    def test_all_key_categories_and_parser_types(self):
        for cls in (cp.ConfigParser,cp.RawConfigParser):
            for key in ('a=b','a:b','x\ny','x\ry','[section]'):
                with self.subTest(cls=cls,key=key):
                    p=cls();p.read_dict({'early':{'ok':'1'},'late':{key:'v'}})
                    self.reject(p,key)

    def test_default_keys(self):
        p=self.make();p['DEFAULT']={'bad=key':'v'};p['s']={'ok':'1'}
        self.reject(p,'bad=key')

    def test_unnamed(self):
        p=self.make(allow_unnamed_section=True);p.read_string('safe = value')
        p.set(cp.UNNAMED_SECTION,'bad:key','v');self.reject(p,'bad:key')

    def test_custom_delimiters(self):
        p=self.make(delimiters=('=>','||'));p.read_dict({'s':{'x||y':'v'}})
        self.reject(p,'x||y')
        p=self.make(delimiters=('=>',));p.read_dict({'s':{'safe=x:y':'v'}})
        out=io.StringIO();p.write(out)
        self.assertIn('safe=x:y',out.getvalue())

    def test_configurable_section_pattern(self):
        p=self.make();p.SECTCRE=re.compile(r'BEGIN:')
        p.read_dict({'s':{'[otherwise-safe]':'v'}})
        out=io.StringIO();p.write(out)
        p=self.make(delimiters=('=',));p.SECTCRE=re.compile(r'BEGIN:')
        p.optionxform=str;p.read_dict({'s':{'BEGIN:bad':'v'}})
        self.reject(p,'BEGIN:bad')

    def test_interpolation_preflight(self):
        calls=[]
        class Interpolation(cp.Interpolation):
            def before_write(self,*args):
                calls.append(args);return args[-1]
        p=self.make(interpolation=Interpolation())
        p.read_dict({'first':{'safe':'v'},'last':{'bad=key':'v'}})
        self.reject(p,'bad=key');self.assertEqual(calls,[])

    def test_safe_byte_format_and_spacing(self):
        p=self.make(allow_no_value=True)
        p.read_dict({'s':{'z':'last','a':'first','empty':None,'multi':'one\ntwo'}})
        items=[('z','last'),('a','first'),('empty',None),('multi','one\ntwo')]
        if SORTED:items.sort()
        for spacing in (None,False,True):
            use_space=(not LEGACY) if spacing is None else spacing
            d=' = ' if use_space else '='
            want='[s]\n'+''.join(k+(d+v.replace('\n','\n\t') if v is not None else '')+'\n' for k,v in items)+'\n'
            out=io.StringIO()
            if spacing is None:p.write(out)
            else:p.write(out,space_around_delimiters=spacing)
            self.assertEqual(out.getvalue(),want)

    def test_no_over_validation(self):
        p=self.make(delimiters=('=>',));p.optionxform=str
        p.read_dict({'s':{'a=b':'literal\nvalue','pre[section]':'ok',' spaced ':'ok'}})
        out=io.StringIO();p.write(out);self.assertIn('a=b',out.getvalue())

    def test_write_only_sink(self):
        class Sink:
            def __init__(self):self.values=[]
            def write(self,value):self.values.append(value)
        p=self.make();p.read_dict({'s':{'ok':'1'}})
        sink=Sink();p.write(sink);self.assertTrue(sink.values)
        p.set('s','bad=key','v');sink=Sink()
        with self.assertRaises(ValueError if LEGACY else cp.Error):p.write(sink)
        self.assertEqual(sink.values,[])

    def test_service_status_types(self):
        p=self.make();p.read_dict({'s':{'ok':'1'}})
        out=io.StringIO();status=service.export(p,out)
        self.assertIs(type(status),int if LEGACY else bool)
        self.assertEqual(status,0 if LEGACY else True)
        p.set('s','bad=key','2');out=io.StringIO();status=service.export(p,out)
        self.assertIs(type(status),int if LEGACY else bool)
        self.assertEqual(status,2 if LEGACY else False);self.assertEqual(out.getvalue(),'')

    def test_stream_errors_propagate(self):
        p=self.make();p.read_dict({'s':{'ok':'1'}})
        for error in (OSError('io'),ValueError('unrelated')):
            class Sink:
                def write(self,value):raise error
            with self.assertRaises(type(error)) as cm:service.export(p,Sink())
            self.assertIs(cm.exception,error)

        # A header-less section can fail in interpolation before any stream write.
        # Output progress does not identify the source of a ValueError.
        for unnamed in (False,True):
            error=ValueError('unrelated interpolation before output')
            class Hook(cp.Interpolation):
                def before_write(self,parser,section,option,value):raise error
            p=self.make(allow_unnamed_section=unnamed,interpolation=Hook())
            p.read_string('key=value' if unnamed else '[s]\nkey=value')
            with self.assertRaises(ValueError) as cm:service.export(p,io.StringIO())
            self.assertIs(cm.exception,error)

    def test_existing_parsing_error_handling(self):
        class Parser:
            def write(self,stream):raise cp.ParsingError('bad')
        out=io.StringIO();self.assertEqual(service.export(Parser(),out),2 if LEGACY else False)
        self.assertFalse(out.closed)

    def test_interpolation_state_change_preserves_error_origin(self):
        for cls in (cp.ConfigParser, cp.RawConfigParser):
            with self.subTest(parser=cls.__name__):
                error = ValueError('later interpolation error after state update')
                class Hook(cp.Interpolation):
                    def before_write(self, parser, section, option, value):
                        parser.set(section, 'late=key', 'added by interpolation')
                        raise error
                parser = cls(interpolation=Hook())
                parser.read_dict({'s': {'safe': 'value'}})
                out = io.StringIO()
                with self.assertRaises(ValueError) as caught:
                    service.export(parser, out)
                self.assertIs(caught.exception, error)
                self.assertTrue(parser.has_option('s', 'late=key'))
                self.assertFalse(out.closed)
