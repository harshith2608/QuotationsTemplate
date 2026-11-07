"""AI helpers on quotations (app/ai_tools.py): off unless switched on (AI_DRAFT=1 / AI_CHECK=1 here; the console's
switches in the shared app) with the API key. Draft from a message: the AI's answer becomes the new quotation form with
the business's own rates (never the AI's), lines without a size waiting to be filled in, the questions to ask; by-item
businesses get their own lines. Photos of site notes: their own switch and limit (per photo), turned upright, shrunk, re-encoded and sent as
pixels, shown back small, never stored. Check before sending: exact checks (size, rate vs their own, discount, twice) plus
the AI's, without the customer's details; the limit per business. The AI is replaced by a fake client, so no request
leaves the machine."""
import json
import os
import re
from types import SimpleNamespace

import anthropic
import httpx2

from app import create_app, db, boq, ai_tools as T
from app.models import AppSetting, BoqItem, PriceListItem, Project
from app.numbers import inr

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
for k in ('AI_DRAFT', 'AI_CHECK', 'AI_PHOTOS', 'ANTHROPIC_API_KEY', 'DEMO_MODE'):
    os.environ.pop(k, None)

calls, answers = [], []


class FakeMessages:
    def parse(self, **kw):
        calls.append(kw)
        answer = answers.pop(0)
        if answer == 'fail':
            raise anthropic.APIConnectionError(request=httpx2.Request('POST', 'https://api.anthropic.com'))
        return SimpleNamespace(parsed_output=answer, stop_reason='end_turn',
                               usage=SimpleNamespace(input_tokens=900, output_tokens=200))


anthropic.Anthropic = lambda **kw: SimpleNamespace(messages=FakeMessages())

app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
with app.app_context():
    first = Project.query.first().id
    TANDEM = PriceListItem.query.filter(PriceListItem.name.ilike('tandem drawer')).first()
    TANDEM_NAME, TANDEM_PRICE = TANDEM.name, TANDEM.price

# ── Off until switched on ──
ok('off: no Draft from a message on the new quotation form', 'Draft from a message' not in c.get('/projects/new?blank=1').text)
ok('off: no Check before sending on a quotation', 'Check before sending' not in c.get(f'/projects/{first}').text)
ok('off: their pages are not there', c.get('/projects/draft').status_code == 404
   and c.post(f'/projects/{first}/check').status_code == 404)
os.environ.update(AI_DRAFT='1', AI_CHECK='1')
ok('switched on but no API key: still off', c.get('/projects/draft').status_code == 404)
os.environ['ANTHROPIC_API_KEY'] = 'test-key'
ok('on: Draft from a message on the new quotation form', '/projects/draft' in c.get('/projects/new?blank=1').text)
ok('on: Check before sending on a quotation', f'/projects/{first}/check' in c.get(f'/projects/{first}').text)


def rooms_of(html):
    return json.loads(re.search(r'id="existing-rooms-data" type="application/json">(.*?)</script>', html, re.S)
                      .group(1).replace('\\u003c', '<'))


# ── Draft from a message (priced by material) ──
D, R, I = T.Draft, T.DraftRoom, T.DraftItem
answers.append(D(job_title='2 BHK interiors', questions=['What size are the kitchen cabinets?', 'Loft in the master bedroom?'], rooms=[
    R(name='Master Bedroom', items=[I(kind='measured', name='Wardrobe', length_ft=9, width_ft=7, material='Acrylic', work_type='Box Work'),
                                    I(kind='measured', name='Loft', material='Laminates')]),
    R(name='Kitchen', items=[I(kind='measured', name='Base Cabinet', length_ft=10, material='Laminates', work_type='Box Work'),
                             I(kind='fitting', name=TANDEM_NAME.lower(), quantity=4),
                             I(kind='fitting', name='Gas Hob'),
                             I(kind='measured', name='Overhead Cabinet', length_ft=999, width_ft=3, material='Granite')])]))
msg = 'Customer Ravi 9876543210. 2BHK: master wardrobe 9x7 acrylic, loft in laminate. Kitchen 10x8 with 4 tandem drawers and a hob.'
with app.app_context():
    before = T.left('draft')[0]
r = c.post('/projects/draft', data={'message': msg})
prompt = calls[-1]['messages'][0]['content']
ok('the AI gets the message and the business\'s own items (materials, fittings)', msg in prompt and 'Acrylic' in prompt
   and TANDEM_NAME in prompt and calls[-1]['model'] == 'claude-haiku-5-5')
ok('the new quotation form opens, filled in, with what to check', r.status_code == 200 and 'id="projectForm"' in r.text
   and 'Drafted from the message: 2 BHK interiors' in r.text and 'What size are the kitchen cabinets?' in r.text)
rooms = rooms_of(r.text)
items = {i['name']: i for room in rooms for i in room['items']}
ok('rooms in order', [x['name'] for x in rooms] == ['Master Bedroom', 'Kitchen'])
w = items['Wardrobe']
ok('a measured item with its size and material (priced by the business\'s rates in the form)',
   (w['type'], w['length'], w['width'], w['wood_type'], w['work_type']) == ('measured', 9, 7, 'Acrylic', 'Box Work')
   and 'unit_price' not in w and not w.get('pending'))
ok('no size given → waiting for a size; a material without a work type gets its first one',
   items['Loft'].get('pending') and 'length' not in items['Loft'] and items['Loft']['wood_type'] == 'Laminates'
   and items['Loft']['work_type'] in ('Box Work', 'Frame Work'))
ok('only one size → waiting too', items['Base Cabinet'].get('pending'))
ok('an impossible size and an unknown material → waiting, on the default material',
   items['Overhead Cabinet'].get('pending') and items['Overhead Cabinet']['wood_type'] != 'Granite')
t = items[TANDEM_NAME]
ok('a fitting by its own name, quantity from the message, at the business\'s price (not the AI\'s)',
   (t['type'], t['quantity'], t['unit_price']) == ('fixed', 4, TANDEM_PRICE) and not t.get('pending'))
ok('a fitting not in their rates: no price, quantity waiting, and said so', items['Gas Hob']['unit_price'] == 0
   and items['Gas Hob'].get('pending') and 'Not in your rates, so no price yet: Gas Hob' in r.text)
ok('the customer isn\'t filled in from the message', 'value="Ravi' not in r.text and '9876543210"' not in r.text)
ok('waiting lines counted for the person', '4 lines are waiting for a size or quantity' in r.text)
with app.app_context():
    ok('one draft used', T.left('draft')[0] == before - 1)

n = len(calls)
r = c.post('/projects/draft', data={'message': 'hi'})
ok('too short: asked for the requirements, AI not called', len(calls) == n and 'Paste the customer' in r.text)

# ── Priced by item: their own lines ──
with app.app_context():
    boq.set_enabled(True)
    fc_row = BoqItem.query.filter_by(name='False Ceiling').first() or BoqItem(name='False Ceiling')
    fc_row.unit, fc_row.rate, fc_row.category, fc_row.description = 'sqft', 120, 'Ceiling', 'Gypsum board'
    db.session.add(fc_row)
    db.session.commit()
answers.append(D(job_title='Hall work', questions=[], rooms=[R(name='Hall', items=[
    I(kind='line', name='false ceiling', length_ft=15, width_ft=12),
    I(kind='line', name='Electrical points', quantity=20, unit='points'),
    I(kind='measured', name='TV Unit', length_ft=8, width_ft=6)])]))
r = c.post('/projects/draft', data={'message': 'Hall 15x12 false ceiling, 20 electrical points and a TV unit 8 by 6'})
prompt = calls[-1]['messages'][0]['content']
items = {i['name']: i for room in rooms_of(r.text) for i in room['items']}
fc = items.get('False Ceiling', {})
ok('by item: the AI is given their own lines', 'False Ceiling [sqft]' in prompt and 'prices by item' in prompt)
ok('…their line at their rate, quantity from the size (15 × 12 = 180 sqft)', (fc.get('type'), fc.get('unit_price'),
   fc.get('quantity'), fc.get('description')) == ('boq', 120, 180, 'Gypsum board'))
ok('…a line not in their rates: price to follow', items['Electrical points'].get('tbc') and items['Electrical points']['unit'] == 'point'
   and items['Electrical points']['quantity'] == 20)
ok('…a measured item becomes a line too (no materials when pricing by item)', items['TV Unit']['type'] == 'boq')
with app.app_context():
    boq.set_enabled(False); db.session.commit()

# ── One allowance of AI uses for every helper (trial / plan / plan with AI), and bought uses ──
from app import plan as PM
MONTH = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
def set_used(n, credits=0):
    AppSetting.set(T.USAGE_KEY, json.dumps({'trial': n, MONTH: n})); AppSetting.set(T.CREDITS_KEY, str(credits))
    db.session.commit()
with app.app_context():
    from datetime import date as _d
    PM.save_plan('trial', PM.today(), PM.today().replace(year=PM.today().year + 1)); db.session.commit(); PM.g.pop('plan_status', None)
    trial = T.pool()
    PM.save_plan('1y', PM.today(), PM.today().replace(year=PM.today().year + 1)); db.session.commit(); PM.g.pop('plan_status', None)
    std = T.pool()
    PM.save_plan('1y_ai', PM.today(), PM.today().replace(year=PM.today().year + 1)); db.session.commit(); PM.g.pop('plan_status', None)
    with_ai = T.pool()
    ok('allowance: 10 in a trial, 20 a month on a plan, 100 a month on a plan with AI', (trial['tier'], trial['allowance'])
       == ('trial', 10) and (std['tier'], std['allowance']) == ('standard', 20) and (with_ai['tier'], with_ai['allowance']) == ('ai', 100))
    PM.save_plan('1y', PM.today(), PM.today().replace(year=PM.today().year + 1)); db.session.commit(); PM.g.pop('plan_status', None)
    set_used(18, 5)
    T._count('photos', 3)
    p = T.pool()
    ok('the month\'s uses first, then bought ones (18 of 20 used + 5 bought, 3 used → 20 of 20, 4 bought left)',
       p['used'] == 20 and p['credits'] == 4 and p['left'] == 4 and '20 a month + 4 bought' in p['words'])
    T.add_credits(40)
    ok('bought uses are added to what\'s left of earlier ones', T.pool()['credits'] == 44)
    PM.save_plan('trial', PM.today(), PM.today().replace(year=PM.today().year + 1)); db.session.commit(); PM.g.pop('plan_status', None)
    set_used(10, 44)
    ok('a trial: its 10 only (bought uses wait for a plan), and it\'s told to choose a plan', T.pool()['left'] == 0
       and 'Choose a plan' in T.limit_text())
    PM.save_plan('', None, None)                     # back to no plan (the demo data's), as before
    db.session.commit(); PM.g.pop('plan_status', None)
    set_used(999)
n = len(calls)
r = c.post('/projects/draft', data={'message': 'Wardrobe 9 x 7 in the master bedroom, acrylic finish please'})
ok('limit reached: said so, AI not called', len(calls) == n and 'used this month&#39;s 20 AI uses' in r.text)
with app.app_context():
    set_used(0)

# ── Photos of site notes ──
import base64, io
from PIL import Image


def photo(w=3000, h=2000, orientation=None, fmt='JPEG'):
    img = Image.new('RGB', (w, h), 'white')
    buf = io.BytesIO()
    if orientation:
        exif = Image.Exif(); exif[0x0112] = orientation
        img.save(buf, fmt, exif=exif)
    else:
        img.save(buf, fmt)
    return buf.getvalue()


def data_url(raw, kind='jpeg'):
    return f'data:image/{kind};base64,' + base64.b64encode(raw).decode()


ok('photos: off until switched on (their own switch)', 'id="draftPhotos"' not in c.get('/projects/draft').text)
os.environ['AI_PHOTOS'] = '1'
page = c.get('/projects/draft').text
ok('on: take photos of the notes, with the AI uses left', 'id="draftPhotos"' in page and re.search(r'\d+ AI uses left', page)
   and '1 AI use each' in page)
answers.append(D(job_title='Kitchen and wardrobe', questions=['Loft size?'], rooms=[
    R(name='Kitchen', items=[I(kind='measured', name='Base Cabinet', length_ft=10.5, width_ft=2.75, material='Laminates', work_type='Box Work')])]))
with app.app_context():
    before_p = T.left()[0]
r = c.post('/projects/draft', data={'message': '', 'photo_data': [data_url(photo(orientation=6)), data_url(photo(800, 600, fmt='PNG'), 'png')]})
blocks = calls[-1]['messages'][0]['content']
imgs = [b for b in blocks if b['type'] == 'image']
sizes = [Image.open(io.BytesIO(base64.b64decode(b['source']['data']))).size for b in imgs]
ok('photos only (no message): the AI reads the photos, then the instructions for handwritten notes',
   len(imgs) == 2 and blocks[-1]['type'] == 'text' and 'handwritten notes' in blocks[-1]['text']
   and '<requirements>' not in blocks[-1]['text'])
ok('each photo turned upright and shrunk to 1568 px, sent as JPEG', sizes[0] == (1045, 1568) and sizes[1] == (800, 600)
   and all(b['source']['media_type'] == 'image/jpeg' for b in imgs))
items = {i['name']: i for room in rooms_of(r.text) for i in room['items']}
ok('the draft from the notes, with the photos shown small to check against', items['Base Cabinet']['length'] == 10.5
   and 'Drafted from your notes' in r.text and r.text.count('alt="Site notes, page') == 2)
with app.app_context():
    ok('counted per photo, from the one allowance', T.left()[0] == before_p - 2)
n = len(calls)
r = c.post('/projects/draft', data={'photo_data': [data_url(photo())] * 4})
ok('more than 3 photos: said so, AI not called', len(calls) == n and 'Up to 3 photos' in r.text)
r = c.post('/projects/draft', data={'photo_data': [data_url(b'not a picture at all, just text')]})
ok('not a picture: said so, AI not called', len(calls) == n and 'couldn&#39;t be opened' in r.text)
r = c.post('/projects/draft', data={'photo_data': [data_url(photo(150, 100))]})
ok('too small to read: said so', len(calls) == n and 'too small to read' in r.text)
answers.append(D(job_title='Wardrobe', questions=[], rooms=[R(name='Bedroom', items=[I(kind='measured', name='Wardrobe')])]))
r = c.post('/projects/draft', data={'photos': [(io.BytesIO(photo(1200, 900)), 'notes.jpg')]}, content_type='multipart/form-data')
ok('without the phone shrinking it, the photo file itself works too', len(calls) == n + 1 and 'Drafted from your notes' in r.text)
with app.app_context():
    set_used(19)
r = c.post('/projects/draft', data={'photo_data': [data_url(photo())] * 2})
ok('1 use left, 2 photos sent: asked to choose fewer', len(calls) == n + 1 and 'You have 1 AI use left' in r.text)
with app.app_context():
    set_used(20)
os.environ['AI_PHOTOS'] = ''
r = c.post('/projects/draft', data={'message': 'Wardrobe 9 x 7 in the master bedroom', 'photo_data': [data_url(photo())]})
ok('photos switched off: photos ignored, the message goes the message\'s way (no uses left here)', len(calls) == n + 1
   and 'used this month&#39;s 20 AI uses' in r.text)
with app.app_context():
    set_used(0)

# ── Check before sending ──
q = json.dumps([
    {'name': 'Master Bedroom', 'items': [
        {'name': 'Wardrobe', 'length': 9, 'width': 7, 'wood_type': 'Acrylic', 'work_type': 'Box Work'},
        {'name': 'Wardrobe', 'length': 9, 'width': 7, 'wood_type': 'Acrylic', 'work_type': 'Box Work'},
        {'name': 'Panelling', 'length': 25, 'width': 9, 'wood_type': 'Laminates', 'work_type': 'Frame Work'}]},
    {'name': 'Kitchen', 'items': [
        {'name': TANDEM_NAME, 'type': 'fixed', 'quantity': 4, 'unit_price': TANDEM_PRICE * 0.5}]}])
c.post('/projects/new', data={'customer_name': 'Checky Customer', 'mobile': '9000000977', 'discount_type': 'percentage',
                              'discount_value': '25', 'rooms_data': q})
with app.app_context():
    pid = Project.query.order_by(Project.id.desc()).first().id
answers.append(T.Review(findings=[T.Finding(level='idea', where='Kitchen · Base Cabinet', message='The kitchen has drawers but no cabinets.')]))
r = c.post(f'/projects/{pid}/check')
prompt = calls[-1]['messages'][0]['content']
text = r.text
ok('the check page: exact checks and the AI\'s', r.status_code == 200 and 'Check before sending' in text
   and 'The kitchen has drawers but no cabinets.' in text)
ok('a rate different from the business\'s own', f'your usual rate is ₹{inr(TANDEM_PRICE, 0)}' in text)
ok('a very large size', 'is very large' in text)
ok('the same line twice', 'on the quotation twice' in text)
ok('a bigger discount than usual', '25% discount; your quotations usually have' in text)
ok('the AI gets the lines and what\'s already found, not the customer', 'Room: Master Bedroom' in prompt
   and 'Wardrobe:' in prompt and 'very large' in prompt and 'Checky' not in prompt and '9000000977' not in prompt)
ok('fixes and checks before ideas', text.index('is very large') < text.index('drawers but no cabinets'))

answers.append('fail')
with app.app_context():
    before = T.left()[0]
r = c.post(f'/projects/{pid}/check')
with app.app_context():
    ok('the AI can\'t answer: the exact checks still shown, said so, not counted', 'Only the quick checks ran' in r.text
       and 'is very large' in r.text and T.left()[0] == before)

staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
ok('staff without access to the quotation can\'t check it', staff.post(f'/projects/{pid}/check').status_code == 403)
ok('a GET goes back to the quotation', c.get(f'/projects/{pid}/check').status_code == 302)

os.environ['DEMO_MODE'] = '1'
with app.app_context():
    ok('always off in the public demo', not T.available('draft') and not T.available('check'))
os.environ.pop('DEMO_MODE')

# ── Plans with AI and bought AI uses (app/subscription.py, plan.html): what a payment adds, its emails and receipt ──
import tempfile, glob, email as _email, email.policy as _policy
from unittest import mock
from flask import render_template
from app import subscription as SUB
outbox_dir = tempfile.mkdtemp()
os.environ.update(MAIL_OUTBOX_DIR=outbox_dir, OPERATOR_EMAIL='op@quote-room.test')
with app.app_context():
    ok('prices: ₹599 a month / ₹5,999 a year, with AI ₹749 / ₹7,499, 40 AI uses ₹99 (6-month kept for old records)',
       {k: SUB.prices()[k] for k in ('1m', '1y', '1m_ai', '1y_ai', 'ai40', '6m')} == {
           '1m': 599, '1y': 5999, '1m_ai': 749, '1y_ai': 7499, 'ai40': 99, '6m': 4999})
    ok('plan names', [PM.short(k) for k in ('1m', '6m', '1y_ai', 'ai40')] == ['1 month', '6 months', '12 months with AI',
                                                                             '40 AI uses'])
    PM.save_plan('1y', PM.today(), PM.add_length(PM.today(), '1y')); db.session.commit(); PM.g.pop('plan_status', None)
    set_used(20, 0)
    before = PM.load_status(on=PM.today())
    SUB._add_here({'plan': 'ai40'})
    PM.g.pop('plan_status', None)
    after = PM.load_status(on=PM.today())
    ok('40 AI uses bought: added, the plan and its dates untouched', T.pool()['credits'] == 40 and T.pool()['left'] == 40
       and (after.plan, after.ends_on) == (before.plan, before.ends_on))
    SUB._add_here({'plan': '1y_ai'})
    PM.g.pop('plan_status', None)
    st = PM.load_status(on=PM.today())
    ok('the 12-month plan with AI: added on from the end date, now with AI (100 a month)', st.plan == '1y_ai'
       and st.ends_on == PM.add_length(before.ends_on, '1y') and T.pool()['allowance'] == 100)
    st2 = PM.renew('6m'); db.session.commit()
    ok('renewing a plan with AI by 6 months keeps it with AI', st2.plan == '6m_ai')
    row = {'id': 1, 'slug': 'demo', 'plan': 'ai40', 'amount_paise': 9900, 'receipt_no': 'QR2611-0001', 'paid_at': None,
           'payment_id': 'pay_1', 'paid_by': 'admin', 'business_name': 'Demo Interiors', 'email': 'owner@demo.test',
           'payer_name': 'Asha Demo', 'source': 'app', 'plan_start': None, 'plan_end': None}
    with mock.patch.object(SUB, '_app_link', lambda slug, path='': 'https://demo.quote-room.test'):
        SUB.notify_paid(row)
    mails = [_email.message_from_bytes(open(f, 'rb').read(), policy=_policy.default) for f in sorted(glob.glob(outbox_dir + '/*.eml'))]
    to_owner = next((m for m in mails if m['To'] == 'owner@demo.test'), None)
    to_op = next((m for m in mails if m['To'] == 'op@quote-room.test'), None)
    body = to_owner.get_body(('plain',)).get_content() if to_owner else ''
    ok('emails for 40 AI uses: to the business (with the receipt, no plan dates) and a note to the operator',
       to_owner is not None and to_owner['Subject'] == 'Payment received: 40 more AI uses' and '₹99' in body
       and 'Plan:' not in body and any(p.get_filename() == 'QuoteRoom-receipt-QR2611-0001.pdf' for p in to_owner.iter_attachments())
       and to_op is not None and 'paid ₹99 for 40 AI uses' in to_op.get_body(('plain',)).get_content()
       and '40 AI uses added to their app' in to_op.get_body(('plain',)).get_content())
    ok('the receipt PDF for 40 AI uses', SUB.receipt_pdf(row).read()[:4] == b'%PDF')
    with mock.patch.object(SUB, 'enabled', lambda: True):
        PM.save_plan('trial', PM.today(), PM.today()); PM.g.pop('plan_status', None)
        trial_can = T.pool()['can_buy']
        PM.save_plan('1y', PM.today(), PM.add_length(PM.today(), '1y')); db.session.commit(); PM.g.pop('plan_status', None)
        paid_can = T.pool()['can_buy']
    ok('a trial can\'t buy AI uses (it chooses a plan); a paid plan can, where paying in the app is on',
       not trial_can and paid_can)
with app.test_request_context('/plan'):
    from flask_login import login_user
    from app.models import User
    login_user(User.query.filter_by(username='demo-admin').first())
    PM.g.pop('plan_status', None)
    with mock.patch.object(SUB, 'enabled', lambda: True):
        pool = T.pool()
    from app import pricing as _pricing
    _plan_vars = dict(pricing=_pricing, pricing_data=_pricing.load(), offered=_pricing.offered())
    page = render_template('plan/plan.html', status=PM.load_status(), prices=SUB.prices(), payments=[], key_id='rzp',
                           ai_pool=pool, ai_allowance={k: T.allowance(k) for k in T.ALLOWANCE}, addon='ai40',
                           addon_uses=40, ai_on=True, **_plan_vars)
    page_off = render_template('plan/plan.html', status=PM.load_status(), prices=SUB.prices(), payments=[], key_id='rzp',
                               ai_pool=pool, ai_allowance={k: T.allowance(k) for k in T.ALLOWANCE}, addon='ai40',
                               addon_uses=40, ai_on=False, **_plan_vars)
    page_lower = render_template('plan/plan.html', status=PM.load_status(), prices=SUB.prices(), payments=[], key_id='rzp',
                                 ai_pool=pool, ai_allowance={k: T.allowance(k) for k in T.ALLOWANCE}, addon='ai40',
                                 addon_uses=40, ai_on=False, autopay={'plan': '1m', 'amount_paise': 69900, 'status': 'active'},
                                 lower_price={'paying': 699, 'now': 599}, **_plan_vars)
ok('price lowered since their autopay started: the bar shows what they pay and how to switch (no days lost)',
   '₹699 a month' in page_lower and 'now ₹599' in page_lower
   and 'Cancel autopay, then Start autopay again' in page_lower and 'no days are lost' in page_lower)
ok('Your plan: four plans (20 or 100 AI uses a month) and Buy 40 AI uses · ₹99',
   all(p in page for p in ('₹599', '₹5,999', '₹749', '₹7,499', "startAutopay('1m'", "startAutopay('1m_ai'",
                           "buyPlan('1y_ai'", "buyPlan('ai40'"))
   and 'Buy 40 AI uses · ₹99' in page and '20 AI uses a month' in page and '100 AI uses a month' in page)
ok('…with every AI helper switched off: only the two plans, nothing about AI', '₹7,499' not in page_off
   and 'AI uses' not in page_off and '₹5,999' in page_off and "startAutopay('1m'" in page_off)
with app.app_context():
    PM.save_plan('', None, None); db.session.commit()
