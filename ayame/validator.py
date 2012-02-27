#
# ayame.validator
#
#   Copyright (c) 2011-2012 Akinori Hattori <hattya@gmail.com>
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

from abc import ABCMeta, abstractmethod
import re

from ayame import core, markup
from ayame.exception import ValidationError


__all__ = ['Validator', 'RegexValidator', 'EmailValidator', 'URLValidator',
           'RangeValidator', 'StringValidator']

# from RFC 1035 and RFC 2822
_atext = "[A-Z0-9!#$%&'*+\-/=?^_`{|}~]"
_label = '(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)'
_email = r'''
    # local part
    {atext}+(?:\.{atext}+)*
    @
    # domain
    {label}(?:\.{label})*
    \Z
'''.format(atext=_atext,
           label=_label)

# from RFC 3986
_pct_encoded = '(?:%[0-9A-F][0-9A-F])'
_unreserved = '[A-Z0-9\-._~]'
_sub_delims = "[!$&'()*+,;=]"
_pchar = '(?:{}|{}|{}|[:@])'.format(_unreserved, _pct_encoded, _sub_delims)
_ipv4 = '(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
_url = r'''
    # scheme
    (?:https?|ftp) : //
    # authority
    (?:
        # userinfo
        (?:{unreserved}|{pct_encoded}|{sub_delims})+
        (?:
            : (?:{unreserved}|{pct_encoded}|{sub_delims})+
        )?
        @
    )?
    (?:
        # host
        (?:{label}(?:\.{label})*) | {ipv4}
    )
    (?:
        # port
        : \d+
    )?
    # path
    (?:/{pchar}*(?:/{pchar}*)*)?
    # query
    (?:
        \? (?:{pchar}|[/?])*
    )?
    # fragment
    (?:
        \# (?:{pchar}|[/?])*
    )?
    \Z
'''.format(unreserved=_unreserved,
           pct_encoded=_pct_encoded,
           sub_delims=_sub_delims,
           label=_label,
           ipv4=_ipv4,
           pchar=_pchar)

# HTML elements
_INPUT = markup.QName(markup.XHTML_NS, 'input')
# HTML attributes
_TYPE = markup.QName(markup.XHTML_NS, 'type')
_MAXLENGTH = markup.QName(markup.XHTML_NS, 'maxlength')

class Validator(core.Behavior):

    __metaclass__ = ABCMeta

    @abstractmethod
    def validate(self, object):
        pass

class RegexValidator(Validator):

    def __init__(self, pattern, flags=0):
        self.regex = re.compile(pattern, flags)

    def validate(self, object):
        if not (isinstance(object, basestring) and
                self.regex.match(object)):
            raise ValidationError()

class EmailValidator(RegexValidator):

    def __init__(self):
        super(EmailValidator, self).__init__(_email,
                                             re.IGNORECASE | re.VERBOSE)

class URLValidator(RegexValidator):

    def __init__(self):
        super(URLValidator, self).__init__(_url, re.IGNORECASE | re.VERBOSE)

class RangeValidator(Validator):

    def __init__(self, min=None, max=None):
        self.min = min
        self.max = max

    def validate(self, object):
        if (self.min is not None and
            not (isinstance(object, self.typeof(self.min)) and
                 self.min <= object)):
            raise ValidationError()
        elif (self.max is not None and
              not (isinstance(object, self.typeof(self.max)) and
                   object <= self.max)):
            raise ValidationError()

    def typeof(self, object):
        if isinstance(object, (long, int)):
            return (long, int)
        elif isinstance(object, basestring):
            return basestring
        return type(object)

class StringValidator(RangeValidator):

    def validate(self, object):
        if not isinstance(object, basestring):
            raise ValidationError()
        super(StringValidator, self).validate(len(object))

    def on_component(self, component, element):
        if (self.max is not None and
            self.is_text_input(element)):
            element.attrib[_MAXLENGTH] = unicode(self.max)

    def is_text_input(self, element):
        return (element.qname == _INPUT and
                element.attrib[_TYPE] in ('text', 'password'))