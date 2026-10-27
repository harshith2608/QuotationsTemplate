"""Formatted text for the presentation pages (Settings → Quotation PDFs → About us / Next steps), typed in a rich text
editor (Quill, in the browser): headings, bold / italic / underline, font colour, alignment, bullet and numbered lists.

Stored as HTML, cleaned here first (clean): only those tags, the editor's alignment / indent classes and a colour are
kept; anything else (scripts, links, images, other styles) is dropped. Plain text saved before (or from a price list
file) still works: is_html() tells them apart, and from_plain() turns it into HTML for the editor.
blocks() reads the clean HTML for the PDF: one block per paragraph, heading or list item, with its text as ReportLab
markup (<b>, <i>, <u>, <strike>, <font color>, <br/>).
"""
import re
from html import escape
from html.parser import HTMLParser

BLOCK = {'p', 'h1', 'h2', 'h3', 'li'}
INLINE = {'strong': 'b', 'b': 'b', 'em': 'i', 'i': 'i', 'u': 'u', 's': 'strike'}
ALLOWED = BLOCK | set(INLINE) | {'br', 'ul', 'ol', 'span'}
DROP_WITH_CONTENT = {'script', 'style', 'head', 'title', 'iframe', 'object', 'noscript', 'template'}
CLASS_RE = re.compile(r'^ql-(align-(center|right|justify)|indent-[1-8])$')
COLOR_RE = re.compile(r'(?:^|;)\s*color\s*:\s*(#[0-9a-fA-F]{3,6}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\))', re.I)
MAX = 20000


def is_html(text):
    return (text or '').lstrip().startswith('<')


def _hex(color):
    color = color.strip()
    m = re.match(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', color, re.I)
    if m:
        return '#%02x%02x%02x' % tuple(min(int(x), 255) for x in m.groups())
    if len(color) == 4:                                   # #abc → #aabbcc
        return '#' + ''.join(ch * 2 for ch in color[1:])
    return color.lower()


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.skip, self.ui = [], [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skip += 1
            return
        a = dict(attrs)
        if tag == 'span' and 'ql-ui' in (a.get('class') or ''):
            self.ui += 1                                   # the editor's own list markers
            self.stack.append('ui')
            return
        if self.skip or tag not in ALLOWED:
            return
        keep = []
        classes = [c for c in (a.get('class') or '').split() if CLASS_RE.match(c)]
        if classes:
            keep.append(f'class="{" ".join(classes)}"')
        m = COLOR_RE.search(a.get('style') or '')
        if m and tag in ('span', 'strong', 'em', 'u', 's', 'b', 'i'):
            keep.append(f'style="color: {_hex(m.group(1))}"')
        if tag == 'li' and a.get('data-list') in ('bullet', 'ordered'):
            keep.append(f'data-list="{a["data-list"]}"')
        if tag == 'br':
            self.out.append('<br>')
            return
        self.out.append(f'<{tag}{" " + " ".join(keep) if keep else ""}>')
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skip = max(self.skip - 1, 0)
            return
        if tag == 'span' and self.stack and self.stack[-1] == 'ui':
            self.stack.pop()
            self.ui -= 1
            return
        if self.skip or tag not in ALLOWED or tag == 'br' or tag not in self.stack:
            return
        while self.stack:                                  # close anything left open inside it
            t = self.stack.pop()
            if t != 'ui':
                self.out.append(f'</{t}>')
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip and not self.ui:
            self.out.append(escape(data, quote=False))


def clean(html):
    """Only the editor's formatting; '' when there's no text in it."""
    p = _Cleaner()
    p.feed((html or '')[:MAX * 2])
    p.close()
    out = ''.join(p.out) + ''.join(f'</{t}>' for t in reversed(p.stack) if t != 'ui')
    return out[:MAX] if plain_text(out).strip() else ''


def plain_text(html):
    return re.sub(r'<[^>]+>', ' ', html or '').replace('&nbsp;', ' ')


def from_plain(text, numbered=False):
    """Plain text (blank line = new paragraph, lines starting with - = a list; numbered: one step per line) as HTML."""
    text = (text or '').replace('\r', '').strip()
    if not text:
        return ''
    if numbered:
        steps = [re.sub(r'^\s*(\d+[.)]|[•●\-–*])\s*', '', l).strip() for l in text.splitlines()]
        return '<ol>' + ''.join(f'<li data-list="ordered">{escape(s)}</li>' for s in steps if s) + '</ol>'
    out = []
    for para in re.split(r'\n\s*\n', text):
        lines = [l for l in para.split('\n') if l.strip()]
        if lines and all(l.strip()[:1] in ('-', '•', '*') for l in lines):
            out.append('<ul>' + ''.join(f'<li data-list="bullet">{escape(l.strip().lstrip("-•* "))}</li>'
                                        for l in lines) + '</ul>')
        elif lines:
            out.append('<p>' + '<br>'.join(escape(l) for l in lines) + '</p>')
    return ''.join(out)


class _Blocks(HTMLParser):
    """Clean HTML → [{'kind': p/h1/h2/h3/li, 'align', 'indent', 'list': bullet/ordered/None, 'markup'}]."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.cur, self.lists, self.inline = [], None, [], []

    def _open(self, kind, a):
        classes = (a.get('class') or '').split()
        align = next((c[9:] for c in classes if c.startswith('ql-align-')), 'left')
        indent = next((int(c[10:]) for c in classes if c.startswith('ql-indent-')), 0)
        kind_list = a.get('data-list') or (self.lists[-1] if self.lists else None) if kind == 'li' else None
        if kind == 'li':
            indent += max(len(self.lists) - 1, 0)
        self.cur = {'kind': kind, 'align': align, 'indent': indent, 'list': kind_list, 'markup': ''}

    def _close(self):
        if self.cur is not None:
            self.cur['markup'] = self.cur['markup'].strip()
            self.blocks.append(self.cur)
            self.cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('ul', 'ol'):
            self._close()
            self.lists.append('bullet' if tag == 'ul' else 'ordered')
        elif tag in BLOCK:
            self._close()
            self._open(tag, a)
        elif tag == 'br':
            if self.cur is not None:
                self.cur['markup'] += '<br/>'
        elif tag in INLINE or tag == 'span':
            if self.cur is None:
                self._open('p', {})
            m = COLOR_RE.search(a.get('style') or '')
            opened = []
            if tag in INLINE:
                opened.append(INLINE[tag])
                self.cur['markup'] += f'<{INLINE[tag]}>'
            if m:
                opened.append('font')
                self.cur['markup'] += f'<font color="{_hex(m.group(1))}">'
            self.inline.append(opened)

    def handle_endtag(self, tag):
        if tag in ('ul', 'ol'):
            self._close()
            if self.lists:
                self.lists.pop()
        elif tag in BLOCK:
            self._close()
        elif (tag in INLINE or tag == 'span') and self.inline:
            opened = self.inline.pop()
            if self.cur is not None:
                self.cur['markup'] += ''.join(f'</{t}>' for t in reversed(opened))

    def handle_data(self, data):
        if not data.strip() and self.cur is None:
            return
        if self.cur is None:
            self._open('p', {})
        self.cur['markup'] += escape(data, quote=False)


def blocks(html):
    p = _Blocks()
    p.feed(clean(html))
    p.close()
    p._close()
    return p.blocks
