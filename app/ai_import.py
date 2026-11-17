"""Bring your old quotation: a firm uploads one quotation it has sent before (PDF or Excel), or the Excel format it
makes its quotations from (its rate list: every item with its rate, usually no quantities), and its app is set up from
it: its items and rates (saved lines), a starting quotation (template), its payment terms and notes, and, for a
quotation, the quotation itself rebuilt in QuoteRoom.

    1. upload (admins)   the text is taken out of the file here: PDF text (a scan has none, so it's refused) or the
                         Excel sheets' cells. Only that text goes to the AI; the file itself is never stored.
    2. read              Claude (Anthropic API, ANTHROPIC_API_KEY) returns its sections and lines as structured data.
                         Numbers are copied from the file, never estimated; the customer's details are left out.
    3. review            every line is editable; the page warns when the lines don't add up to the file's total.
    4. set up            the reviewed lines go through the same loader as the console's "Load price list"
                         (app/price_list.py), into this business only.

One switch turns it on or off for every trial and customer in the shared app: the console's AI import card
(public.console_state 'ai_import' in the trials database, read here every SWITCH_TTL seconds). A single-business
deployment turns it on with AI_IMPORT=1. Either way it also needs ANTHROPIC_API_KEY, and it's off in the demo.
Each business may read LIMIT_TRIAL files during its trial and LIMIT_MONTH a month on a paid plan; every read is
logged in public.ai_imports (trials database) for the console.
"""
import io
import json
import os
import re
import time
from datetime import datetime
from collections import Counter
from typing import List, Literal, Optional

from pydantic import BaseModel
from sqlalchemy import text

from . import db
from .numbers import inr

MODEL = 'claude-haiku-5-5'
STATE_KEY = 'ai_import'
USAGE_KEY = 'ai_import_usage'
SWITCH_TTL = 30
LIMIT_TRIAL = 5
LIMIT_MONTH = 20
MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 60000
MIN_TEXT = 200
TIMEOUT = 50                    # seconds (the app's requests may run for 60)
LOG_DDL = """CREATE TABLE IF NOT EXISTS public.ai_imports (
    id         SERIAL PRIMARY KEY,
    slug       VARCHAR(40),
    at         TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    kind       VARCHAR(10),
    ok         BOOLEAN NOT NULL,
    lines      INTEGER,
    tokens_in  INTEGER,
    tokens_out INTEGER,
    note       VARCHAR(200))"""

_switch = {}


class ImportProblem(ValueError):
    """A message for the person importing (the file can't be read, the limit is reached…)."""


# ── On / off ─────────────────────────────────────────────────────────────────

def _truthy(value):
    return (value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def switched_on():
    """The platform switch: the console's, for the shared app; AI_IMPORT=1 for a single-business deployment."""
    from . import tenancy
    if not tenancy.tenant_mode():
        return _truthy(os.environ.get('AI_IMPORT'))
    hit = _switch.get('on')
    if hit and time.time() - hit[1] < SWITCH_TTL:
        return hit[0]
    on = False
    try:
        with db.engine.connect() as conn:
            if conn.execute(text("SELECT to_regclass('public.console_state')")).scalar() is not None:
                on = conn.execute(text('SELECT value FROM public.console_state WHERE key = :k'),
                                  {'k': STATE_KEY}).scalar() == '1'
    except Exception:
        on = False
    _switch['on'] = (on, time.time())
    return on


def set_switch(on):
    """The console's switch (the console's database is the trials database). Takes effect within SWITCH_TTL."""
    with db.engine.begin() as conn:
        conn.execute(text('DELETE FROM public.console_state WHERE key = :k'), {'k': STATE_KEY})
        conn.execute(text('INSERT INTO public.console_state (key, value) VALUES (:k, :v)'),
                     {'k': STATE_KEY, 'v': '1' if on else '0'})
    _switch.clear()


def console_switch():
    """The console's own reading of the switch (no cache)."""
    with db.engine.connect() as conn:
        return conn.execute(text('SELECT value FROM public.console_state WHERE key = :k'), {'k': STATE_KEY}).scalar() == '1'


def api_key():
    return (os.environ.get('ANTHROPIC_API_KEY') or '').strip()


def available():
    """Shown and usable in this app: switched on, the API key set, not the public demo."""
    from .demo import demo_enabled
    return not demo_enabled() and bool(api_key()) and switched_on()


# ── Limits ───────────────────────────────────────────────────────────────────

def _usage():
    from .models import AppSetting
    try:
        return json.loads(AppSetting.get(USAGE_KEY) or '{}')
    except ValueError:
        return {}


def left():
    """(files this business can still read, the limit's wording)."""
    from . import plan as plan_mod
    use = _usage()
    status = plan_mod.load_status()
    if status.has_limit and status.is_trial:
        return max(LIMIT_TRIAL - use.get('trial', 0), 0), f'{LIMIT_TRIAL} during your free trial'
    return max(LIMIT_MONTH - use.get(datetime.utcnow().strftime('%Y-%m'), 0), 0), f'{LIMIT_MONTH} a month'


def _count():
    from . import plan as plan_mod
    from .models import AppSetting
    use = _usage()
    status = plan_mod.load_status()
    key = 'trial' if status.has_limit and status.is_trial else datetime.utcnow().strftime('%Y-%m')
    use[key] = use.get(key, 0) + 1
    AppSetting.set(USAGE_KEY, json.dumps(use))
    db.session.commit()


def _log(kind, ok, lines=None, tokens_in=None, tokens_out=None, note=''):
    """One row per read in public.ai_imports (shared app only; never breaks the import)."""
    from flask import g
    from . import tenancy
    if not tenancy.tenant_mode():
        return
    try:
        with db.engine.begin() as conn:
            conn.execute(text(LOG_DDL))
            conn.execute(text('INSERT INTO public.ai_imports (slug, kind, ok, lines, tokens_in, tokens_out, note) '
                              'VALUES (:s, :k, :ok, :l, :ti, :to, :n)'),
                         {'s': g.get('tenant_slug'), 'k': kind, 'ok': ok, 'l': lines, 'ti': tokens_in,
                          'to': tokens_out, 'n': (note or '')[:200]})
    except Exception:
        pass


def recent(limit=30):
    """The latest reads, for the console (none before the first)."""
    with db.engine.connect() as conn:
        if conn.execute(text("SELECT to_regclass('public.ai_imports')")).scalar() is None:
            return []
        return [dict(r) for r in conn.execute(text('SELECT * FROM public.ai_imports ORDER BY id DESC LIMIT :n'),
                                              {'n': limit}).mappings()]


# ── 1. The file's text ───────────────────────────────────────────────────────

def file_text(filename, raw):
    """(kind, text) from an uploaded PDF or .xlsx. Raises ImportProblem for anything it can't read."""
    name = (filename or '').lower()
    if not raw:
        raise ImportProblem('Choose your quotation file (PDF or Excel).')
    if len(raw) > MAX_BYTES:
        raise ImportProblem('That file is larger than 5 MB. Upload the quotation on its own.')
    if name.endswith('.pdf') or raw[:5] == b'%PDF-':
        return 'pdf', _pdf_text(raw)
    if name.endswith('.xlsx') or name.endswith('.xlsm'):
        return 'excel', _excel_text(raw)
    if name.endswith('.xls'):
        raise ImportProblem('This is an old Excel file (.xls). Open it in Excel, choose Save As → Excel Workbook '
                            '(.xlsx), and upload that.')
    raise ImportProblem('Upload a PDF or an Excel file (.xlsx).')


def _pdf_text(raw):
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ImportProblem('This PDF is password-protected. Upload a copy without a password.')
        body = '\n'.join((page.extract_text() or '') for page in reader.pages[:20])
    except ImportProblem:
        raise
    except Exception:
        raise ImportProblem("This PDF couldn't be opened. Try saving it again, or upload the Excel file instead.")
    if len(body.strip()) < MIN_TEXT:
        raise ImportProblem('This PDF is a scan (a picture of the pages), so there\'s no text to read. Upload the '
                            'original file you made it from: the PDF saved from Word or Excel, or the Excel file.')
    return body[:MAX_TEXT]


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, float):
        return f'{value:.2f}'.rstrip('0').rstrip('.')
    return ' '.join(str(value).split())


def _excel_text(raw):
    from openpyxl import load_workbook
    try:
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception:
        raise ImportProblem("This Excel file couldn't be opened. Save it again as .xlsx and upload that.")
    out = []
    for sheet in book.worksheets[:5]:
        rows = []
        for row in sheet.iter_rows(values_only=True):
            cells = [_cell(v) for v in row]
            while cells and not cells[-1]:
                cells.pop()
            if any(cells):
                rows.append('\t'.join(cells))
        if rows:
            out.append(f'Sheet: {sheet.title}\n' + '\n'.join(rows))
    body = '\n\n'.join(out)
    if len(body.strip()) < MIN_TEXT:
        raise ImportProblem('This Excel file has almost nothing in it. Upload the sheet with your quotation or your rates.')
    return body[:MAX_TEXT]


# ── 1b. A clean rate table (a product master): the rows read directly ─────────
# Which column is which: the AI looks at the headings and a few rows (_ask_columns: a small, quick request, not counted
# against the limit), then every row is read here, exactly as written. Without the AI (no key, or it fails), by the
# headings: lower case, letters only; the first heading found of each list wins.
TABLE_NAME = ('productname', 'itemname', 'item', 'name', 'product', 'particulars', 'particular', 'itemdescription',
              'workname', 'work')
TABLE_RATE = ('rate', 'sellingrate', 'sellingprice', 'unitrate', 'unitprice', 'rateperunit', 'price', 'mrp', 'rates',
              'raters', 'rateinrs', 'rateinr', 'priceperunit')
TABLE_UNIT = ('unit', 'uom', 'units', 'per')
TABLE_DESC = ('description', 'details', 'specification', 'specifications', 'desc', 'remarks', 'itemdetails')
TABLE_GROUP = ('productcategory', 'category', 'section', 'group', 'room', 'area', 'head', 'itemcategory')
EXACT_ONLY = {'per', 'area', 'head', 'name', 'item', 'work'}      # "Percentage", "Area (sqft)", "Headcount": not these
TABLE_QTY = ('qty', 'quantity', 'nos', 'noof', 'count')          # a quotation, not a rate list: left to the AI
TABLE_COST = ('agency', 'cost', 'purchase', 'buying', 'vendor', 'labour', 'total', 'amount')   # never the selling rate
TABLE_MIN_ROWS = 5
PREVIEW_ROWS, PREVIEW_CELL, PREVIEW_MAX = 25, 60, 14000
ACRONYMS = {'Ac': 'AC', 'Tv': 'TV', 'Pop': 'POP', 'Mdf': 'MDF', 'Led': 'LED', 'Pvc': 'PVC', 'Wpc': 'WPC', 'Mr': 'MR',
            'Hdhmr': 'HDHMR', 'Upvc': 'uPVC', 'Bwp': 'BWP', 'Bwr': 'BWR', 'Cnc': 'CNC', 'Ms': 'MS', 'Ss': 'SS', 'Gi': 'GI',
            'Pu': 'PU', '3d': '3D', '2d': '2D', 'Bhk': 'BHK', 'Rcc': 'RCC'}
FIELDS = (('name', 'Item name'), ('rate', 'Rate'), ('unit', 'Unit'), ('description', 'Description'),
          ('group', 'Section'))


def _heading(value):
    return re.sub(r'[^a-z]', '', str(value or '').lower())


def _pick(heads, wanted, avoid=()):
    for w in wanted:
        for i, h in enumerate(heads):
            if h == w and not any(a in h for a in avoid):
                return i
    for w in wanted:                          # "Rate (Rs.)", "Product Name *"
        if w in EXACT_ONLY:
            continue
        for i, h in enumerate(heads):
            if h.startswith(w) and not any(a in h for a in avoid):
                return i
    return None


def _caps_name(value):
    """ALL CAPS from a spreadsheet → normal case, keeping acronyms (AC PELMET → AC Pelmet)."""
    v = ' '.join(str(value or '').split())
    if v.isupper():
        v = re.sub(r"[A-Za-z0-9']+", lambda m: ACRONYMS.get(m.group(0), m.group(0)), v.title())
    return v


def _letter(i):
    out, i = '', i + 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _index(letter):
    letter = re.sub(r'[^A-Z]', '', str(letter or '').upper())
    if not letter or len(letter) > 2:
        return None
    n = 0
    for ch in letter:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _sheets(raw):
    """[(title, rows)] of the first sheets, or None when it isn't an Excel file that opens."""
    from openpyxl import load_workbook
    try:
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        return [(sh.title, [r for r in sh.iter_rows(values_only=True, max_row=5000)]) for sh in book.worksheets[:5]]
    except Exception:
        return None


class ColumnMap(BaseModel):
    kind: Literal['rate_list', 'quotation', 'other']
    sheet: int
    heading_row: int
    name: str
    rate: str
    unit: str
    description: str
    group: str


COLUMNS_PROMPT = """These are the first rows of each sheet of an Excel file a business (interiors, furniture, kitchens,
windows…) uploaded to set up its rates. Each row: its number, then its non-empty cells by column letter.
Say which sheet and which columns hold its items and their rates:
- kind: "rate_list" when it lists items with their selling rates (no job's quantities filled in); "quotation" when it is
  a quotation for one job (quantities and amounts filled in for that job); "other" when it is neither.
- sheet: the sheet's number. heading_row: the row number of the column headings (0 if there are none).
- name: the column with each item's name. rate: the selling rate per unit the customer is charged (not a cost, agency,
  purchase, vendor or labour price, not a total or amount). unit: the column with the rate's unit (sqft, nos, rft,
  running ft, LS…). description: the specification or description text. group: the category, room or section of each
  item, in its own column ("" when sections are rows with just a heading, like KITCHEN, in the name column). Each a
  column letter, or "" when the file has no such column; never the same letter for two of them.
Only map a column whose cells hold that kind of value."""


def _preview(sheets):
    out = []
    for n, (title, rows) in enumerate(sheets, 1):
        lines = []
        for r_at, row in enumerate(rows[:PREVIEW_ROWS], 1):
            cells = [f'{_letter(i)}={_cell(v)[:PREVIEW_CELL]}' for i, v in enumerate(row or ()) if _cell(v)]
            if cells:
                lines.append(f'{r_at}: ' + ' | '.join(cells))
        if lines:
            out.append(f'Sheet {n} "{title}":\n' + '\n'.join(lines))
    return '\n\n'.join(out)[:PREVIEW_MAX]


def _ask_columns(sheets):
    """The AI's reading of which column is which → (ColumnMap, usage), or (None, None) when it can't be asked."""
    if not api_key():
        return None, None
    body = _preview(sheets)
    if not body:
        return None, None
    import anthropic
    try:
        client = anthropic.Anthropic(api_key=api_key(), timeout=25, max_retries=1)
        r = client.messages.parse(model=MODEL, max_tokens=400, output_format=ColumnMap,
                                  messages=[{'role': 'user', 'content': f'{COLUMNS_PROMPT}\n\n<sheets>\n{body}\n</sheets>'}])
    except Exception:
        return None, None
    if r.stop_reason in ('refusal', 'max_tokens') or r.parsed_output is None:
        return None, None
    return r.parsed_output, {'in': r.usage.input_tokens, 'out': r.usage.output_tokens}


def _by_headings(rows):
    """{'heading_row': i, field: column index…} from the headings, 'quotation' for a sheet with quantities, or None."""
    for h_at, row in enumerate(rows[:15]):
        heads = [_heading(v) for v in row or ()]
        name_i, rate_i = _pick(heads, TABLE_NAME), _pick(heads, TABLE_RATE, TABLE_COST)
        if name_i is None or rate_i is None or name_i == rate_i:
            continue
        if any(h in TABLE_QTY for h in heads):
            return 'quotation'
        return {'heading_row': h_at, 'name': name_i, 'rate': rate_i, 'unit': _pick(heads, TABLE_UNIT),
                'description': _pick(heads, TABLE_DESC), 'group': _pick(heads, TABLE_GROUP)}
    return None


def _read_rows(rows, cols):
    """Every item row under the headings, exactly as written: {group: {'name', 'lines'}}. With no section column,
    a row with only a name (KITCHEN, BEDROOM 1…) starts a section."""
    from . import boq
    name_i, rate_i, unit_i, desc_i, group_i = (cols.get(k) for k in ('name', 'rate', 'unit', 'description', 'group'))
    if desc_i == name_i:
        desc_i = None
    groups, seen, names, current = {}, set(), Counter(), 'Items'
    for r in rows[cols['heading_row'] + 1:]:
        r = r or ()
        cell = lambda i: r[i] if i is not None and i < len(r) else None
        name, rate = _caps_name(cell(name_i)), _num(cell(rate_i))
        if name and rate is None and group_i is None and not any(_cell(v) for i, v in enumerate(r) if i != name_i):
            current = name                    # a section heading row
            continue
        if not name or rate is None or rate < 0:
            continue
        desc = boq.clean_description(cell(desc_i)) if desc_i is not None else ''
        unit = boq.clean_unit(cell(unit_i)) if unit_i is not None and cell(unit_i) else 'nos'
        base = re.sub(r'\s*[-–(]\s*(clone|copy)\)?\s*$', '', name, flags=re.I)
        key = (base.lower(), rate, desc, unit)
        if key in seen:
            continue                          # an identical copy ("AC PELMET - Clone")
        seen.add(key)
        names[base.lower()] += 1
        shown = base if names[base.lower()] == 1 else f'{base} ({names[base.lower()]})'
        group = _caps_name(cell(group_i)) if group_i is not None and cell(group_i) else current
        groups.setdefault(group.lower(), {'name': group[:100], 'lines': []})['lines'].append(
            {'name': shown[:100], 'description': desc, 'unit': unit, 'quantity': None, 'rate': rate,
             'amount': None, 'material': '', 'work': '', 'no_amount': False})
    return groups


def _columns_note(title, rows, cols):
    """'Item name ← Product Name (B) · Rate ← Selling Price (F) · …' for the review page."""
    heads = rows[cols['heading_row']] if 0 <= cols['heading_row'] < len(rows) else ()
    parts = []
    for key, label in FIELDS:
        i = cols.get(key)
        if i is None:
            continue
        head = _cell(heads[i]) if heads and i < len(heads) else ''
        parts.append(f'{label} ← {head or "column"} ({_letter(i)})')
    return f'Sheet "{title}": ' + ' · '.join(parts)


def _table_data(groups, note, how):
    return {'rate_list': True, 'pricing': 'item', 'table': True, 'columns': note, 'columns_by': how,
            'pricing_reason': 'Read straight from your sheet: every item, rate and description as you wrote them.',
            'job_title': 'My rates', 'sections': list(groups.values()), 'charges': [], 'subtotal': None,
            'discount': 0, 'gst_percent': None, 'grand_total': None, 'payment_terms': '', 'notes': ''}


def rate_table(raw, ask=True):
    """A product master / rate list Excel (items with rates, no quantities) read row by row: the review data (see tidy),
    or None when it isn't one (then the AI reads the whole file). Which column is which: the AI's look at the headings
    and first rows (ask), else the headings themselves. data['usage']: the AI's tokens, when it was asked."""
    sheets = _sheets(raw)
    if not sheets:
        return None
    if ask:
        found, used = _ask_columns(sheets)
        if found is not None:
            if found.kind == 'quotation':
                return None                   # a job's quotation: the AI reads it all, with its totals
            if found.kind == 'rate_list' and 1 <= found.sheet <= len(sheets):
                title, rows = sheets[found.sheet - 1]
                cols = {k: _index(getattr(found, k)) for k, _ in FIELDS}
                cols['heading_row'] = max(found.heading_row - 1, -1)       # (-1: no headings, items from row 1)
                for k in ('unit', 'description', 'group'):                  # (a column used twice: not this one)
                    if cols[k] is not None and cols[k] in (cols['name'], cols['rate']):
                        cols[k] = None
                if cols['name'] is not None and cols['rate'] is not None and cols['name'] != cols['rate']:
                    groups = _read_rows(rows, cols)
                    if sum(len(g['lines']) for g in groups.values()) >= TABLE_MIN_ROWS:
                        data = _table_data(groups, _columns_note(title, rows, cols), 'ai')
                        data['usage'] = used
                        return data
    for title, rows in sheets:                # without the AI: by the headings
        cols = _by_headings(rows)
        if cols == 'quotation':
            return None
        if cols:
            groups = _read_rows(rows, cols)
            if sum(len(g['lines']) for g in groups.values()) < TABLE_MIN_ROWS:
                return None
            return _table_data(groups, _columns_note(title, rows, cols), 'headings')
    return None


# ── 2. Read it ───────────────────────────────────────────────────────────────

class Line(BaseModel):
    name: str
    description: str
    size: str
    unit: str
    quantity: Optional[float]
    rate: Optional[float]
    amount: Optional[float]
    material: str = ''
    work_type: str = ''


class Section(BaseModel):
    name: str
    lines: List[Line]


class Charge(BaseModel):
    name: str
    amount: float


class Quote(BaseModel):
    is_rate_list: bool = False
    pricing: Literal['material', 'item', 'unsure'] = 'unsure'
    pricing_reason: str = ''
    job_title: str
    sections: List[Section]
    charges: List[Charge]
    subtotal: Optional[float]
    discount: Optional[float]
    gst_percent: Optional[float]
    grand_total: Optional[float]
    payment_terms: str
    notes_and_terms: str


PROMPT = """This is the text of a quotation (BOQ) that a business (interiors, furniture, kitchens, windows, glass work…)
sent to a customer, or of the format it makes its quotations from (its rate list: items with their rates, quantities
and amounts usually left empty), taken from a PDF or an Excel sheet, so table columns may be run together.
Read it into the structure:
- is_rate_list: true for a rate list or a blank quotation format (rates, but no job's quantities filled in), false for
  a quotation made for a job.
- sections: the rooms, categories or section headings, in order, each with its priced lines.
- each line: the item's name as written, without its serial number ("TV Unit Base Drawers", not "1.1 TV Unit Base
  Drawers"; keep the words that tell similar items apart); the specification or description as written ('' if none);
  the size as written ('' if none); the unit as written (sqft, rft, nos, LS…); quantity = what the rate is
  multiplied by to give the amount (the area or length when the rate is per sqft or rft, else the count); rate and
  amount exactly as printed; material = the material or finish the line's rate depends on, as written ("Laminate",
  "Acrylic", "Veneer", "PU"…), '' if it names none; work_type = "Box Work" or "Frame Work" only when the file prices
  the same material differently for box work (carcass, cabinets) and frame work (shutters, panels), else ''.
- pricing: "material" when the rate depends on the material (and work type), not on the item: every laminate line at
  one rate per sqft and every acrylic line at another, whatever the item. "item" when items have their own rates (a
  wardrobe and a TV unit in the same material at different rates, lump sums). "unsure" if you can't tell.
  pricing_reason: one short sentence for the business owner, with an example from the file.
- charges: fees or extra amounts added after the lines, such as a design fee, contingency or transport. Not taxes.
- subtotal (total of the lines, before discount, charges and tax), discount, gst_percent, grand_total: as printed.
- job_title: what the job is, in 2–4 words ("3 BHK interiors", "Pharmacy interiors", "Kitchen and wardrobes").
- payment_terms and notes_and_terms: their own wording, '' if none.
Copy numbers exactly (Indian format: 1,45,000 = 145000). Never estimate or invent a number: use null when one isn't
printed. Leave out the customer's name, phone number and address."""


def read(body):
    """Claude's reading of the quotation text → (Quote, usage). Raises ImportProblem."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key(), timeout=TIMEOUT, max_retries=1)
    try:
        r = client.messages.parse(model=MODEL, max_tokens=16000, output_format=Quote,
                                  messages=[{'role': 'user', 'content': f'{PROMPT}\n\n<quotation>\n{body}\n</quotation>'}])
    except anthropic.APIStatusError as exc:
        raise ImportProblem('Reading the quotation failed just now. Try again in a minute.') from exc
    except anthropic.APIConnectionError as exc:
        raise ImportProblem('Reading the quotation took too long or couldn\'t connect. Try again in a minute.') from exc
    if r.stop_reason == 'max_tokens':
        raise ImportProblem('This quotation is too long to read in one go. Upload a shorter one (one job).')
    if r.stop_reason == 'refusal' or r.parsed_output is None:
        raise ImportProblem("This file couldn't be read as a quotation or a rate list.")
    return r.parsed_output, {'in': r.usage.input_tokens, 'out': r.usage.output_tokens}


def read_upload(filename, raw):
    """The whole of steps 1–2 for an upload, within the limit: the review data (see tidy). Raises ImportProblem."""
    name = (filename or '').lower()
    if raw and len(raw) <= MAX_BYTES and (name.endswith('.xlsx') or name.endswith('.xlsm')):
        table = rate_table(raw)              # a rate list: its rows read as they are (exact, quick, not counted)
        if table:
            used = table.pop('usage', None) or {}
            _log('excel', True, sum(len(s['lines']) for s in table['sections']), used.get('in'), used.get('out'),
                 note='rate table: columns by the AI' if table.get('columns_by') == 'ai' else 'rate table, by its headings')
            return table
    if left()[0] <= 0:
        raise ImportProblem(f'You\'ve used all your quotation imports ({left()[1]}). Message us on WhatsApp if you '
                            'need another.')
    kind, body = file_text(filename, raw)
    try:
        quote, used = read(body)
    except ImportProblem as exc:
        _log(kind, False, note=str(exc))
        raise
    data = tidy(quote)
    lines = sum(len(s['lines']) for s in data['sections'])
    if not lines:
        _log(kind, False, tokens_in=used['in'], tokens_out=used['out'], note='no lines')
        raise ImportProblem("No priced lines were found in this file. Is it a quotation or a rate list, with items "
                            "and rates?")
    _count()
    _log(kind, True, lines, used['in'], used['out'])
    return data


# ── 3. Review ────────────────────────────────────────────────────────────────

# "1.1 ", "3. ", "4) ", "a) ", "(iv) " in front of a name (a bare "2 " is part of it: "2 BHK wardrobe")
_NUMBERING = re.compile(r'^\s*(?:\(?\d+(?:\.\d+)+[.)]?|\(?\d+[.)]|\(?[A-Za-z][.)]|\(?[ivxIVX]+[.)])\s+')


def _name(value):
    name = _NUMBERING.sub('', ' '.join(str(value or '').split()))
    return (name[:1].upper() + name[1:])[:100]


def _section(value):
    """A section heading: "A MASTER BEDROOM" → "Master Bedroom"."""
    name = _name(re.sub(r'^\s*[A-Z]\s+(?=[A-Z])', '', ' '.join(str(value or '').split())))
    return name.title() if name.isupper() else name


def _num(value):
    """A number (whole ones as int, so 72 shows as 72, not 72.0), or None."""
    try:
        n = round(float(value), 2) if value is not None and value != '' else None
    except (TypeError, ValueError):
        return None
    return int(n) if n is not None and n == int(n) else n


def _work(value):
    """'Box Work' / 'Frame Work' (the app's work types) from what the file or the form says, else ''."""
    v = str(value or '').lower()
    return 'Box Work' if 'box' in v else 'Frame Work' if 'frame' in v else ''


def tidy(quote):
    """The reading as plain data for the review page: names without serial numbers, units in the app's words, a
    rate worked out from amount ÷ quantity when only the amount is printed, the size kept in the description. A rate
    list (said so, or no line has a quantity or an amount) is checked as rates only: no totals."""
    from . import boq
    rate_list = quote.is_rate_list or all(l.quantity is None and l.amount is None for s in quote.sections for l in s.lines)
    sections = []
    for s in quote.sections:
        lines = []
        for l in s.lines:
            name = _name(l.name)
            if not name:
                continue
            qty, rate, amount = _num(l.quantity), _num(l.rate), _num(l.amount)
            if rate is None and amount is not None:
                rate, qty = (_num(amount / qty), qty) if qty else (amount, 1)
            elif rate and amount is not None and (qty is None or abs(qty * rate - amount) > 1):
                qty = _num(round(amount / rate, 3))   # the printed amount wins: area × count × rate, say
            desc = ' '.join((l.description or '').split())
            if desc.lower() == name.lower():
                desc = ''
            if l.size.strip():
                desc = (desc + ' · ' if desc else '') + 'Size: ' + ' '.join(l.size.split())
            lines.append({'name': name, 'description': desc[:500], 'unit': boq.clean_unit(l.unit),
                          'quantity': qty, 'rate': rate, 'amount': amount,
                          'material': ' '.join(l.material.split())[:60], 'work': _work(l.work_type),
                          'no_amount': amount is None and rate is not None and not rate_list})   # maybe not in their total
        if lines:
            sections.append({'name': _section(s.name) or 'Items', 'lines': lines})
    charges = [{'name': _name(c.name), 'amount': _num(c.amount)} for c in quote.charges
               if _name(c.name) and (_num(c.amount) or 0) > 0]
    return {'rate_list': rate_list, 'pricing': quote.pricing, 'pricing_reason': ' '.join(quote.pricing_reason.split())[:300],
            'job_title': ' '.join(quote.job_title.split())[:60] or 'My quotation',
            'sections': sections, 'charges': charges, 'subtotal': _num(quote.subtotal), 'discount': abs(_num(quote.discount) or 0),   # "- 10,000"
            'gst_percent': _num(quote.gst_percent), 'grand_total': _num(quote.grand_total),
            'payment_terms': quote.payment_terms.strip()[:3000], 'notes': quote.notes_and_terms.strip()[:5000]}


def from_form(form):
    """The review page's form → the same plain data (lines left unticked are dropped)."""
    sections = []
    for i in range(min(int(form.get('sections') or 0), 60)):
        lines = []
        for j in range(min(int(form.get(f's{i}_lines') or 0), 200)):
            p = f's{i}_{j}_'
            if not form.get(p + 'keep') or not _name(form.get(p + 'name')):
                continue
            lines.append({'name': _name(form.get(p + 'name')), 'description': (form.get(p + 'description') or '').strip()[:2000],
                          'unit': (form.get(p + 'unit') or '').strip(), 'quantity': _num(form.get(p + 'quantity')),
                          'rate': _num(form.get(p + 'rate')),
                          'material': ' '.join((form.get(p + 'material') or '').split())[:60], 'work': _work(form.get(p + 'work'))})
        if lines:
            sections.append({'name': _section(form.get(f's{i}_name')) or 'Items', 'lines': lines})
    charges = []
    for k in range(min(int(form.get('charges') or 0), 20)):
        if form.get(f'c{k}_keep') and _name(form.get(f'c{k}_name')) and _num(form.get(f'c{k}_amount')):
            charges.append({'name': _name(form.get(f'c{k}_name')), 'amount': _num(form.get(f'c{k}_amount'))})
    return {'rate_list': form.get('rate_list') == '1', 'pricing': 'material' if form.get('pricing') == 'material' else 'item',
            'job_title': ' '.join((form.get('job_title') or '').split())[:60] or 'My quotation', 'sections': sections,
            'charges': charges, 'discount': abs(_num(form.get('discount')) or 0), 'gst': _num(form.get('gst')),
            'payment_terms': (form.get('payment_terms') or '').strip()[:3000], 'notes': (form.get('notes') or '').strip()[:5000]}


# ── 4. Set up ────────────────────────────────────────────────────────────────

def by_material(data):
    """The reviewed lines the way a business that prices by material keeps them: a line measured in sqft (or sq m) is an
    item in a material (one rate per material, or per material and work type when the file has both box and frame
    work; an area line with no material is a material of its own, like Glass); anything else (pieces, running feet,
    lump sums, the charges) is a fitting with its price. Where one material comes at several rates, the most common
    one is taken and the others are listed in 'mixed'.
    → {'materials': [{'name', 'rates': {work: rate}}], 'fittings': [{'name', 'price', 'unit'}],
       'rooms': [{'name', 'items': [template items]}], 'mixed': ["Laminate: ₹1,650 (Kitchen base unit)"]}"""
    from . import boq
    names, seen, fits, rooms = {}, {}, {}, []
    sections = data['sections'] + ([{'name': 'Other charges', 'lines': [
        {'name': c['name'], 'unit': 'lump sum', 'rate': c['amount'], 'material': '', 'work': ''}
        for c in data['charges']]}] if data['charges'] else [])
    for s in sections:
        items = []
        for l in s['lines']:
            rate, unit = l['rate'] or 0, boq.clean_unit(l['unit'])
            if unit in boq.AREA_UNITS:
                mat = l.get('material') or l['name']
                mat = names.setdefault(mat.lower(), mat[:60])
                seen.setdefault(mat, []).append((l.get('work') or '', rate, l['name']))
                items.append({'name': l['name'], 'material': mat, 'work': l.get('work') or ''})
                continue
            name, n = l['name'], 1
            while name.lower() in fits and fits[name.lower()]['price'] != rate:          # same name, another price
                n += 1
                name = (f"{l['name']} ({s['name']})" if n == 2 else f"{l['name']} ({s['name']} {n - 1})")[:100]
            fits.setdefault(name.lower(), {'name': name, 'price': rate, 'unit': unit})
            items.append({'name': name, 'type': 'fitting'})
        rooms.append({'name': s['name'], 'items': items})
    materials, mixed, split = [], [], set()
    for mat, rows in seen.items():
        works = {w for w, _, _ in rows if w}
        both = len(works) == 2                              # box and frame work at their own rates
        if not both:
            split.add(mat)
        rates = {}
        for work in (('Box Work', 'Frame Work') if both else ('',)):
            mine = [(r, item) for w, r, item in rows if (not both or (w or 'Box Work') == work)]
            rate = Counter(r for r, _ in mine).most_common(1)[0][0]
            rates[work] = rate
            mixed += [f"{mat}{' ' + work if work else ''}: ₹{inr(r, 0)} ({item})" for r, item in mine if r != rate]
        materials.append({'name': mat, 'rates': rates})
    for r in rooms:            # one rate for the material: no work type on its items; with both, unsaid is box work
        for it in r['items']:
            if it.get('material') in split:
                it['work'] = ''
            elif it.get('material'):
                it['work'] = it['work'] or 'Box Work'
    return {'materials': materials, 'fittings': list(fits.values()), 'rooms': rooms, 'mixed': mixed,
            'work_types': any(len(m['rates']) > 1 for m in materials)}


def price_list(data):
    """The reviewed data as a price list file (app/price_list.py): saved lines (one per item name; the same name at
    another rate gets its section's name added), a starting quotation with those sections, the quotation rebuilt,
    payment terms and notes, and GST if it was on. A rate list (no quantities: just their rates) gives only the rates
    and those settings: no starting quotation, nothing rebuilt. By material (see by_material): materials, fittings and
    the starting quotation; the quotation isn't rebuilt either."""
    from . import boq, quote_gst
    if data.get('pricing') == 'material':
        m = by_material(data)
        out = {'pricing': 'material',
               'materials': [{'name': x['name'], **({'rates': x['rates']} if '' not in x['rates'] else {'rate': x['rates']['']})}
                             for x in m['materials']],
               'fittings': m['fittings'],
               'templates': [] if data.get('rate_list') else [{'name': data['job_title'], 'rooms': m['rooms']}],
               'settings': {k: v for k, v in (('payment_terms', data['payment_terms']), ('important_notes', data['notes'])) if v}}
        if data.get('gst') in quote_gst.RATES:
            out['options'] = {'gst': data['gst']}
        return out
    lines, by_name = [], {}

    def line_for(l, section):
        rate = l['rate'] or 0
        name, n = l['name'], 1
        while name.lower() in by_name and by_name[name.lower()]['rate'] != rate:     # same name, another rate
            n += 1
            name = (f"{l['name']} ({section})" if n == 2 else f"{l['name']} ({section} {n - 1})")[:100]
        key = name.lower()
        if key not in by_name:
            by_name[key] = {'name': name, 'description': l['description'], 'unit': boq.clean_unit(l['unit']),
                            'rate': rate, 'group': section[:60]}
            lines.append(by_name[key])
        return by_name[key]['name']

    rooms, quote_rooms = [], []
    sections = data['sections'] + ([{'name': 'Other charges', 'lines': [
        {'name': c['name'], 'description': '', 'unit': 'lump sum', 'quantity': 1, 'rate': c['amount']}
        for c in data['charges']]}] if data['charges'] else [])
    for s in sections:
        names, items = [], []
        for l in s['lines']:
            name = line_for(l, s['name'])
            if name not in names:
                names.append(name)
            items.append({'name': name, 'description': l['description'], 'unit': boq.clean_unit(l['unit']),
                          'quantity': l['quantity'] or 0, 'rate': l['rate'] or 0})
        rooms.append({'name': s['name'], 'items': names})
        quote_rooms.append({'name': s['name'], 'items': items})
    out = {'pricing': 'item', 'lines': lines,
           'templates': [] if data.get('rate_list') else [{'name': data['job_title'], 'rooms': rooms}],
           'quotations': [] if data.get('rate_list') else [{'customer_name': f"{data['job_title']} (your old quotation)",
                                                            'discount': data['discount'], 'rooms': quote_rooms}],
           'settings': {k: v for k, v in (('payment_terms', data['payment_terms']), ('important_notes', data['notes'])) if v}}
    if data.get('gst') in quote_gst.RATES:
        out['options'] = {'gst': data['gst']}
    return out


def set_up(data):
    """Load the reviewed quotation into this business (its saved lines, template, settings, the quotation).
    Returns (summary, the rebuilt quotation's id or None). Raises price_list.PriceListError."""
    from . import price_list as PL
    from .models import Project
    result = PL.apply(PL.parse(json.dumps(price_list(data)).encode()), remove_starter=True, replace_settings=False,
                      hide_starter_rates=data.get('pricing') == 'material')
    from . import setup_guide
    for key in ('import', 'rates'):            # the setup guide: set up the quick way (how you price: by apply)
        setup_guide.mark(key)
    made = None
    if result['quotations']:
        name = result['quotations'][0]
        made = next((p.id for p in Project.query.order_by(Project.id.desc()).limit(20) if p.customer_name == name), None)
    return result, made
