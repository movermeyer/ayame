#
# ayame.i18n
#
#   Copyright (c) 2012-2014 Akinori Hattori <hattya@gmail.com>
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
import sys

import ayame
from . import core, local
from .exception import ResourceError


__all__ = ['Localizer']

_kv_re = re.compile(r"""
    \A
    (?P<key>
        .*? (?<!\\)(?:\\\\)*
    )
    (?:
        # separator
        (?:
            \s* [:=] \s*
        ) |
        \s+
    )
    (?P<value>.*)
    \Z
""", re.VERBOSE)
_backslash_re = re.compile(r'\\(.)')
_lcont_re = re.compile(r"""
    (?<!\\)(?:\\\\)* \\
    \Z
""", re.VERBOSE)
_ctrl_chr = {
    'f': '\f',
    'n': '\n',
    'r': '\r',
    't': '\t'
}


class Localizer(object):

    extension = '.properties'

    def get(self, component, locale, key):
        for bundle, prefix in self._iter_resource(component, locale):
            if bundle:
                if prefix:
                    v = bundle.get(prefix + '.' + key)
                    if v is not None:
                        return v
                v = bundle.get(key)
                if v is not None:
                    return v

    def _iter_resource(self, component, locale):
        res = component.config['ayame.resource.loader']
        sep = component.config['ayame.markup.separator']

        def load(module, *args):
            name = '_'.join(args)
            try:
                r = res.load(module, name + self.extension)
                with r.open() as fp:
                    return self._load(fp)
            except (OSError, IOError, ResourceError):
                pass

        for class_, scope, prefix in self._iter_class(component):
            m = sys.modules.get(class_.__module__)
            if m:
                n = sep.join(c.__name__ for c in scope + (class_,)) if scope else class_.__name__
                lc, cc = locale[:2]
                if lc:
                    if cc:
                        yield load(m, n, lc, cc), prefix
                    yield load(m, n, lc), prefix
                yield load(m, n), prefix

    def _iter_class(self, component):
        queue = collections.deque()
        if isinstance(component, core.Component):
            path = component.path().split(':')
            scope = ()
            for i, c in enumerate(reversed(tuple(component.iter_parent()))):
                c = c.__class__
                if c.markup_type.scope:
                    scope = c.markup_type.scope
                queue.appendleft((c, scope, '.'.join(path[i:])))
            queue.appendleft((component.__class__, self._scope_of(component.__class__), ''))
        queue.appendleft((local.app().__class__, (), ''))

        while queue:
            class_, scope, prefix = queue.pop()
            yield class_, scope, prefix
            if (not self._is_base_class(class_) and
                class_.__bases__):
                queue.extend((c, self._scope_of(c), prefix)
                             for c in class_.__bases__
                             if self._is_target_class(c))

    def _is_base_class(self, class_):
        return class_ in (core.Page, core.MarkupContainer, core.Component, ayame.Ayame)

    def _is_target_class(self, class_):
        return issubclass(class_, (core.Component, ayame.Ayame))

    def _scope_of(self, class_):
        if issubclass(class_, core.MarkupContainer):
            return class_.markup_type.scope
        return ()

    def _load(self, fp):
        match = _kv_re.match
        sub = _backslash_re.sub
        has_lcont = _lcont_re.search
        ctrl_get = _ctrl_chr.get

        def repl(m):
            ch = m.group(1)
            return ctrl_get(ch, ch)

        bundle = {}
        ll = []
        for l in fp:
            l = l.lstrip().rstrip('\n\r')
            if (not l or
                l[0] in ('#', '!')):
                # blank or comment line
                continue
            elif l[-1] == '\\':
                if has_lcont(l):
                    # found line continuation
                    ll.append(l[:-1])
                    continue
            if ll:
                ll.append(l)
                l = ''.join(ll)
                ll = []
            m = match(l)
            if m:
                key, value = m.groups()
                value = sub(repl, value)
            else:
                key, value = l, ''
            key = sub(repl, key)
            bundle[key] = value
        return bundle
