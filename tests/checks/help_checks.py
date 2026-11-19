"""Help (/help, app/manual.py, app/help_bp.py): the manual with a search box for everyone; Ask answers from it with
the AI (faked here), within a daily limit per person."""
import json
from unittest import mock
from app import create_app, manual, help_bp

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
admin, staff = app.test_client(), app.test_client()
admin.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})

ids = [a['id'] for a in manual.ARTICLES]
ok('every article has an id, title, summary, tags and steps; ids are unique', len(ids) == len(set(ids))
   and all(a.get('title') and a.get('summary') and a.get('tags') and a.get('steps') for a in manual.ARTICLES))
with app.test_request_context():
    from flask import url_for
    bad = []
    for a in manual.ARTICLES:
        try:
            url_for(a['link'], **({'tab': a['tab']} if a.get('tab') else {}))
        except Exception:
            bad.append(a['id'])
ok('every article links to a real page', not bad)

page = admin.get('/help').text
ok('Help page for admins, in the menu', 'id="helpQ"' in page and "Change your rates" in page and '/help' in admin.get('/projects').text)
sp = staff.get('/help').text
ok('employees get it too, without admin-only articles', sp.count('"id":') > 5 and 'Change your rates' not in sp
   and 'Ask your admin to see the rates' in sp)
ok('features that are off are left out (approvals)', 'Approve employees' not in page)
ok('no AI key: no Ask button (search still works)', 'id="helpAsk"' not in page)

class Fake:
    def __init__(self, ans): self.parsed_output, self.usage = ans, None
with mock.patch.object(help_bp, 'ask_available', return_value=True):
    ok('with the AI key: Ask is shown', 'id="helpAsk"' in admin.get('/help').text)
    calls = []
    def parse(**kw):
        calls.append(kw)
        return Fake(help_bp.Answer(found=True, intro='Here is how.', steps=['Open the quotation.', 'Tap Edit.'],
                                   article_ids=['discount', 'nope']))
    client = mock.MagicMock(); client.messages.parse.side_effect = parse
    with mock.patch('anthropic.Anthropic', return_value=client):
        r = admin.post('/help/ask', json={'q': 'how to give discount'})
        d = r.get_json()
        ok('Ask answers with steps and links only to real articles', d['found'] and d['steps'] == ['Open the quotation.', 'Tap Edit.']
           and [x['id'] for x in d['related']] == ['discount'] and d['related'][0]['url'])
        sysmsg = calls[0]['system'][0]
        ok('… the manual goes to the AI (cached) with the question', 'Give a discount' in sysmsg['text']
           and sysmsg.get('cache_control') and calls[0]['messages'][0]['content'] == 'how to give discount')
        staff.post('/help/ask', json={'q': 'how to change rates'})
        ok('… an employee\'s manual has no admin-only articles', 'Change your rates' not in calls[-1]['system'][0]['text'])
        ok('too short a question is refused', admin.post('/help/ask', json={'q': 'a'}).status_code == 400)
        with mock.patch.object(help_bp, '_asks_left', return_value=0):
            ok('daily limit', admin.post('/help/ask', json={'q': 'how to give discount'}).status_code == 429)
    client.messages.parse.side_effect = RuntimeError('down')
    with mock.patch('anthropic.Anthropic', return_value=client):
        ok('the AI failing gives a friendly message', admin.post('/help/ask', json={'q': 'how to give discount'}).status_code == 502)
ok('without the AI key Ask is refused', admin.post('/help/ask', json={'q': 'how to give discount'}).status_code == 400)
ok('signed out: no Help', app.test_client().get('/help').status_code in (302, 401))
