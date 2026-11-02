"""AI helpers on quotations (app/ai_tools.py): off unless switched on (AI_DRAFT=1 / AI_CHECK=1 here; the console's
switches in the shared app) with the API key. Draft from a message: the AI's answer becomes the new quotation form with
the business's own rates (never the AI's), lines without a size waiting to be filled in, the questions to ask; by-item
businesses get their own lines. Check before sending: exact checks (size, rate vs their own, discount, twice) plus
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

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
for k in ('AI_DRAFT', 'AI_CHECK', 'ANTHROPIC_API_KEY', 'DEMO_MODE'):
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

# ── Limit ──
with app.app_context():
    AppSetting.set(T.FEATURES['draft']['usage'], json.dumps({'trial': 999, __import__('datetime').datetime.utcnow().strftime('%Y-%m'): 999}))
    db.session.commit()
n = len(calls)
r = c.post('/projects/draft', data={'message': 'Wardrobe 9 x 7 in the master bedroom, acrylic finish please'})
ok('limit reached: said so, AI not called', len(calls) == n and 'used all of' in r.text)

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
ok('a rate different from the business\'s own', f'your usual rate is ₹{TANDEM_PRICE:,.0f}' in text)
ok('a very large size', 'is very large' in text)
ok('the same line twice', 'on the quotation twice' in text)
ok('a bigger discount than usual', '25% discount; your quotations usually have' in text)
ok('the AI gets the lines and what\'s already found, not the customer', 'Room: Master Bedroom' in prompt
   and 'Wardrobe:' in prompt and 'very large' in prompt and 'Checky' not in prompt and '9000000977' not in prompt)
ok('fixes and checks before ideas', text.index('is very large') < text.index('drawers but no cabinets'))

answers.append('fail')
with app.app_context():
    before = T.left('check')[0]
r = c.post(f'/projects/{pid}/check')
with app.app_context():
    ok('the AI can\'t answer: the exact checks still shown, said so, not counted', 'Only the quick checks ran' in r.text
       and 'is very large' in r.text and T.left('check')[0] == before)

staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
ok('staff without access to the quotation can\'t check it', staff.post(f'/projects/{pid}/check').status_code == 403)
ok('a GET goes back to the quotation', c.get(f'/projects/{pid}/check').status_code == 302)

os.environ['DEMO_MODE'] = '1'
with app.app_context():
    ok('always off in the public demo', not T.available('draft') and not T.available('check'))
os.environ.pop('DEMO_MODE')
