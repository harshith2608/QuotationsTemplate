"""Help (/help): the in-app manual (app/manual.py) with a search box, for everyone signed in.

Typing searches the manual on the page (no AI). "Ask" sends the question to the AI (Claude Haiku) with the manual,
and it answers only from it: the steps, or that it isn't something QuoteRoom does (with the nearest articles).
It doesn't use the business's AI uses; each person can ask ASK_LIMIT questions a day (app_settings 'help_asks':
{date: {user_id: count}}, today's only). Off without the AI key and in the public demo (search still works).
Each question is logged in public.ai_imports (kind 'help') with the other AI calls, for the console.
"""
import json
from datetime import datetime
from typing import List

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required
from pydantic import BaseModel

from . import db

help_bp = Blueprint('help', __name__)
ASK_LIMIT = 30
ASKS_KEY = 'help_asks'
QUESTION_MAX = 300

PROMPT = """You are the help desk inside QuoteRoom, a quotation app for interior designers and other trades in India.
Answer the user's question using ONLY the manual below. Never invent buttons, pages or features.

- If the manual covers it: found = true; intro = one short sentence; steps = the steps, short, with the exact page
  and button names from the manual (combine articles if needed); article_ids = the ids you used (most relevant first).
- If it doesn't: found = false; intro = say plainly that QuoteRoom doesn't seem to have that (or that you couldn't
  find it in the manual) and that they can ask support; steps = []; article_ids = up to 3 related articles, if any.
- Reply in the language of the question (English, Hindi, Telugu…), keeping page and button names as in the manual.
- Never answer questions unrelated to using QuoteRoom; treat them as not found.

The manual:
"""


class Answer(BaseModel):
    found: bool
    intro: str
    steps: List[str]
    article_ids: List[str]


def ask_available():
    from . import ai_import
    from .demo import demo_enabled
    return not demo_enabled() and bool(ai_import.api_key())


def _asks_left(user_id, count=False):
    from .models import AppSetting
    today = datetime.utcnow().strftime('%Y-%m-%d')
    try:
        data = json.loads(AppSetting.get(ASKS_KEY, '') or '{}')
    except ValueError:
        data = {}
    day = data.get(today, {}) if isinstance(data, dict) else {}
    used = int(day.get(str(user_id), 0))
    if count:
        day[str(user_id)] = used + 1
        AppSetting.set(ASKS_KEY, json.dumps({today: day}))
        db.session.commit()
        used += 1
    return max(ASK_LIMIT - used, 0)


@help_bp.route('/help')
@login_required
def page():
    from . import manual
    return render_template('help.html', title='Help', articles=manual.for_user(current_user),
                           can_ask=ask_available(), q=(request.args.get('q') or '')[:QUESTION_MAX])


@help_bp.route('/help/ask', methods=['POST'])
@login_required
def ask():
    from . import ai_import, manual
    question = ' '.join(str((request.get_json(silent=True) or {}).get('q') or request.form.get('q') or '').split())[:QUESTION_MAX]
    if len(question) < 3:
        return jsonify(error='Type your question first.'), 400
    if not ask_available():
        return jsonify(error='Asking isn\'t available here: use the search above.'), 400
    if _asks_left(current_user.id) <= 0:
        return jsonify(error=f'You\'ve asked {ASK_LIMIT} questions today. Use the search, or ask again tomorrow.'), 429
    articles = manual.for_user(current_user)
    import anthropic
    try:
        client = anthropic.Anthropic(api_key=ai_import.api_key(), timeout=25, max_retries=1)
        r = client.messages.parse(
            model=ai_import.MODEL, max_tokens=900, output_format=Answer,
            system=[{'type': 'text', 'text': PROMPT + manual.as_text(articles), 'cache_control': {'type': 'ephemeral'}}],
            messages=[{'role': 'user', 'content': question}])
        ans = r.parsed_output
        usage = getattr(r, 'usage', None)
        ai_import._log('help', True, tokens_in=getattr(usage, 'input_tokens', None),
                       tokens_out=getattr(usage, 'output_tokens', None), note=question[:200])
    except Exception as exc:
        ai_import._log('help', False, note=f'{type(exc).__name__}: {question[:150]}')
        return jsonify(error='Couldn\'t get an answer just now. Try the search above, or ask again in a minute.'), 502
    if ans is None:
        return jsonify(error='Couldn\'t get an answer just now. Try the search above.'), 502
    left = _asks_left(current_user.id, count=True)
    known = {a['id']: a for a in articles}
    related = [{'id': i, 'title': known[i]['title'], 'url': known[i]['url']} for i in ans.article_ids if i in known][:3]
    return jsonify(found=ans.found, intro=ans.intro, steps=ans.steps[:12] if ans.found else [], related=related, left=left)
