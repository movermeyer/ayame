#
# ayame.route
#
#   Copyright (c) 2011-2014 Akinori Hattori <hattya@gmail.com>
#
#   Permission is hereby granted, free of charge, to any person
#   obtaining a copy of this software and associated documentation files
#   (the "Software"), to deal in the Software without restriction,
#   including without limitation the rights to use, copy, modify, merge,
#   publish, distribute, sublicense, and/or sell copies of the Software,
#   and to permit persons to whom the Software is furnished to do so,
#   subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be
#   included in all copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
#   EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
#   MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
#   NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
#   BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
#   ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
#   CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#   SOFTWARE.
#

import collections
import re

from . import _compat as five
from . import http, uri, util
from .exception import _RequestSlash, RouteError


__all__ = ['Rule', 'Map', 'Router', 'Converter']

_rule_re = re.compile(r"""
    (?P<static>[^<]*)
    <
        (?P<variable>[a-zA-Z] [a-zA-Z0-9_-]*)
        (?:
            :
            (?P<converter>[a-zA-Z_] [a-zA-Z0-9_-]*)
            (?:
                \( (?P<args>.*?) \)
            )?
        )?
    >
""", re.VERBOSE)
_simple_rule_re = re.compile(r'<([^>]+)>')

_args_re = re.compile(r"""
    \s*
    (?:
        (?P<name>\w+) \s* = \s*
    )?
    (?P<value>
        (?P<const>
            None |
            True |
            False
        ) |
        (?P<float>
            [+-]?
            (?:
                (?:
                    \d+ |
                    \d* \. \d+ |
                    \d+ \.
                )
                [eE] [+-]? \d+
            ) |
            (?:
                \d* \. \d+ |
                \d+ \.
            )
        ) |
        (?P<int>
            [+-]?
            (?:
               [1-9] \d* |
               0 [oO] [0-7]+ |
               0 [xX] [\da-fA-F]+ |
               0 [bB] [01]+ |
               0+
            )
        ) |
        (?P<str>
            ".*? (?<!\\)(?:\\\\)*" |
            '.*? (?<!\\)(?:\\\\)*'
        )
    )
    (?P<error>[^,]*?)
    \s*
    (?P<sep>
        , \s* |
        \Z
    )
""", re.VERBOSE)
_sep_re = re.compile('[\s,]')


class Rule(object):

    def __init__(self, path, object, methods=None, redirection=False):
        self.__map = None
        self.__path = path
        self.__leaf = not path.endswith('/')
        self.__object = object
        self.__methods = tuple(set(m.upper() for m in methods)) if methods else ('GET', 'POST')
        self.__redirection = redirection

        self._regex = None
        self._segments = []
        self._converters = {}
        self._variables = set()

    @property
    def map(self):
        return self.__map

    @property
    def path(self):
        return self.__path

    @property
    def object(self):
        return self.__object

    @property
    def methods(self):
        return self.__methods

    def is_leaf(self):
        return self.__leaf

    def has_redirect(self):
        return self.__redirection

    def bind(self, map):
        if self.map is not None:
            raise RouteError('rule {!r} already bound to map {!r}'.format(self, self.map))
        self.__map = map
        self._compile()

    def _compile(self):
        assert self.map is not None, 'rule not bound to map'
        path = self.path if self.is_leaf() else self.path.rstrip('/')

        self._segments = []
        self._converters.clear()
        self._variables.clear()

        buf = [r'\A']
        for var, conv, args in self._parse(path):
            if conv is None:
                buf.append(re.escape(var))
                self._segments.append((False, var))
            elif var in self._variables:
                raise RouteError("variable name '{}' already in use".format(var))
            else:
                conv = self._new_converter(conv, args)
                buf.append('(?P<{}>{})'.format(var, conv.pattern))
                self._segments.append((True, var))
                self._converters[var] = conv
                self._variables.add(var)
        if not self.is_leaf():
            self._segments.append((False, '/'))
        buf.append('(?P<__slash__>/?)')
        buf.append(r'\Z')

        self._regex = re.compile(''.join(buf))

    def _parse(self, path):
        pos = 0
        for m in _rule_re.finditer(path):
            g = m.groupdict()
            if g['static']:
                yield g['static'], None, None
            yield (g['variable'],
                   g['converter'] if g['converter'] else 'default',
                   g['args'] if g['args'] else None)
            pos = m.end()
        if pos < len(path):
            yield path[pos:], None, None

    def _new_converter(self, name, args):
        converter = self.map.converters.get(name)
        if converter is None:
            raise RouteError("converter '{}' not found".format(name))

        if args:
            args, kwargs = self._parse_args(args)
            return converter(self.map, *args, **kwargs)
        return converter(self.map)

    def _parse_args(self, expr):
        def error(msg, offset):
            return SyntaxError(msg, ('<args>', 1, offset, expr))

        pos = 0
        args = []
        kwargs = {}
        for m in _args_re.finditer(expr):
            if m.group('error'):
                raise error('invalid syntax', m.start('error') + 1)

            name = m.group('name')
            if kwargs:
                if name is None:
                    raise error('non-keyword arg after keyword arg', m.endpos)
                elif name in kwargs:
                    raise error('keyword argument repeated', m.start('name') + 1)

            for type in ('const', 'int', 'float', 'str'):
                value = m.group(type)
                if value is None:
                    continue
                elif type == 'const':
                    if value == 'True':
                        value = True
                    elif value == 'False':
                        value = False
                    else:
                        value = None
                elif type == 'int':
                    value = int(value, 0)
                elif type == 'float':
                    value = float(value)
                elif type == 'str':
                    q = value[0]
                    value = five.str(value[1:-1].replace('\\' + q, q))
                break
            if name is None:
                args.append(value)
            else:
                kwargs[name] = value
            pos = m.endpos

        if (pos != len(expr) and
            _sep_re.sub('', expr)):
            raise error('invalid syntax', max(pos, 1))
        return tuple(args), kwargs

    def match(self, path):
        assert self.map is not None, 'rule not bound to map'
        m = self._regex.search(path)
        if not m:
            return
        g = m.groupdict()
        slash = g.pop('__slash__')
        if (self.map.slash and
            not self.is_leaf() and
            not slash):
            raise _RequestSlash()

        values = {}
        for var, val in five.items(g):
            try:
                values[var] = self._converters[var].to_python(val)
            except ValueError:
                return
        return values

    def build(self, values, anchor=None, method=None, query=True):
        assert self.map is not None, 'rule not bound to map'
        if not (method is None or
                method in self.methods):
            return
        for var in self._variables:
            if var not in values:
                return
        # path
        buf = []
        cache = {}
        for dyn, var in self._segments:
            if dyn:
                cache[var] = util.to_list(values[var])
                if not cache[var]:
                    return
                val = cache[var].pop(0)
                try:
                    buf.append(self._converters[var].to_uri(val))
                except ValueError:
                    return
            else:
                buf.append(var)
        # query
        if query:
            query = []
            for var, val in five.items(values):
                val = [util.to_bytes(v, self.map.encoding)
                       for v in (cache[var] if var in cache else util.to_list(val))]
                if not val:
                    continue
                var = util.to_bytes(var, self.map.encoding)
                query.append((var, val))
            if query:
                query = sorted(query, key=self.map.sort_key)
                buf.append('?')
                buf.append(five.urlencode(query, doseq=True))
        # anchor
        if anchor:
            buf.append('#')
            buf.append(uri.quote(anchor, encoding=self.map.encoding))
        return u''.join(buf)


class Map(object):

    def __init__(self, encoding='utf-8', slash=True, converters=None,
                 sort_key=None):
        self.encoding = encoding
        self.slash = slash
        self.converters = {
            'default': _StringConverter,
            'string': _StringConverter,
            'path': _PathConverter,
            'int': _IntegerConverter
        }
        if converters:
            self.converters.update(converters)
        self.sort_key = sort_key

        self._rules = []
        self._ref = collections.defaultdict(list)

    def add(self, rule):
        rule.bind(self)
        self._rules.append(rule)
        self._ref[rule.object].append(rule)

    def connect(self, path, object, methods=None):
        self.add(Rule(path, object, methods))

    def redirect(self, path, dest, methods=None):
        self.add(Rule(path, dest, methods, True))

    def mount(self, path):
        return _Submap(self, path)

    def bind(self, environ):
        return Router(self, environ)


class _Submap(object):

    def __init__(self, map, path):
        self.map = map
        self.path = path

    def add(self, rule):
        self.map.add(Rule(self.path + rule.path, rule.object, rule.methods, rule.has_redirect()))

    def connect(self, path, object, methods=None):
        self.map.add(Rule(self.path + path, object, methods))

    def redirect(self, path, dest, methods=None):
        self.map.add(Rule(self.path + path, dest, methods, True))


class Router(object):

    def __init__(self, map, environ):
        self.map = map
        self.environ = environ

    def match(self, as_rule=False):
        path = self.environ['PATH_INFO']
        method = self.environ['REQUEST_METHOD']
        allow = set()
        for rule in self.map._rules:
            try:
                values = rule.match(path)
            except _RequestSlash:
                environ = self.environ.copy()
                environ['PATH_INFO'] += '/'
                raise http.MovedPermanently(uri.request_uri(environ, True))
            if values is None:
                continue
            elif method not in rule.methods:
                allow.update(rule.methods)
                continue
            elif rule.has_redirect():
                if isinstance(rule.object, five.string_type):
                    def repl(m):
                        var = m.group(1)
                        converter = rule._converters[var]
                        return converter.to_uri(values[var])

                    location = _simple_rule_re.sub(repl, rule.object)
                else:
                    location = rule.object(**values)
                environ = self.environ.copy()
                environ['PATH_INFO'] = location
                raise http.MovedPermanently(uri.request_uri(environ, True))
            return rule if as_rule else rule.object, values
        if allow:
            raise http.NotImplemented(method, uri.request_path(self.environ))
        raise http.NotFound(uri.request_path(self.environ))

    def build(self, object, values=None, anchor=None, method=None, query=True,
              relative=False):
        if values is None:
            values = {}

        for rule in self.map._ref.get(object, ()):
            path = rule.build(values, anchor, method, query)
            if path is None:
                continue
            elif relative:
                return path
            return uri.quote(self.environ.get('SCRIPT_NAME', u'')) + path
        raise RouteError('no rule for building URI')


class Converter(object):

    pattern = '[^/]+'

    def __init__(self, map):
        self.map = map

    def to_python(self, value):
        return value

    def to_uri(self, value):
        return uri.quote(value, encoding=self.map.encoding)


class _StringConverter(Converter):

    def __init__(self, map, length=None, min=None):
        super(_StringConverter, self).__init__(map)
        self.length = length
        self.min = min
        if min is not None:
            max = length if length is not None else ''
            count = '{},{}'.format(min, max)
        elif length is not None:
            count = length
        else:
            count = '1,'
        self.pattern = '[^/]{{{}}}'.format(count)

    def to_uri(self, value):
        value = super(_StringConverter, self).to_uri(value)
        if self.min is not None:
            if (len(value) < self.min or
                (self.length is not None and
                 self.length < len(value))):
                raise ValueError()
        elif (self.length is not None and
              len(value) != self.length):
            raise ValueError()
        return value


class _PathConverter(Converter):

    pattern = '[^/].*?'


class _IntegerConverter(Converter):

    pattern = '\d+'

    def __init__(self, map, digits=None, min=None, max=None):
        super(_IntegerConverter, self).__init__(map)
        self.digits = digits
        self.min = min
        self.max = max
        if digits is not None:
            self.pattern = '\d{{{}}}'.format(digits)

    def to_python(self, value):
        value = int(value)
        if ((self.min is not None and
             value < self.min) or
            (self.max is not None and
             self.max < value)):
            raise ValueError()
        return value

    def to_uri(self, value):
        value = self.to_python(value)
        if self.digits is not None:
            value = '{:0{}d}'.format(value, self.digits)
            if self.digits < len(value):
                raise ValueError()
            return value
        return five.str(value)
