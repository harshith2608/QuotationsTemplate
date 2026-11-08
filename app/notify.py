"""Instant alerts to the operator's Telegram: a new trial, a booked call, a payment. Short, with the phone number
(tap it in Telegram to call), a WhatsApp button and a button to the console.

    TELEGRAM_BOT_TOKEN=<from @BotFather>      TELEGRAM_CHAT_ID=<your chat: console → Features → Telegram alerts>
    CONSOLE_URL=https://ops.quote-room.co.in   (optional: the "Open in console" button)
Set on the console (trials, payments, website call bookings) and on the trials app (calls booked in the app).
Nothing is sent without both; a failure is logged and never stops what the business was doing.
"""
import json
import os
import urllib.parse
import urllib.request
from html import escape

API = 'https://api.telegram.org/bot{token}/{method}'


def _env(name):
    return (os.environ.get(name) or '').strip()


def enabled():
    return bool(_env('TELEGRAM_BOT_TOKEN') and _env('TELEGRAM_CHAT_ID'))


def _call(method, payload=None, token=None):
    url = API.format(token=token or _env('TELEGRAM_BOT_TOKEN'), method=method)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def send(title, lines=(), phone='', console_path='', chat_id=None):
    """One alert: a bold title, a few lines, the phone (tap to call), and WhatsApp / console buttons. True if sent."""
    if not (_env('TELEGRAM_BOT_TOKEN') and (chat_id or _env('TELEGRAM_CHAT_ID'))):
        return False
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if len(digits) == 10:
        digits = '91' + digits
    text = '<b>' + escape(title) + '</b>'
    body = [escape(str(l)) for l in lines if l]
    if digits:
        body.append(f'📞 +{digits[:2]} {digits[2:7]} {digits[7:]}')
    if body:
        text += '\n' + '\n'.join(body)
    buttons = []
    if digits:
        buttons.append({'text': 'WhatsApp', 'url': f'https://wa.me/{digits}'})
    console = _env('CONSOLE_URL').rstrip('/')
    if console and console_path:
        buttons.append({'text': 'Open in console', 'url': console + console_path})
    payload = {'chat_id': chat_id or _env('TELEGRAM_CHAT_ID'), 'text': text, 'parse_mode': 'HTML',
               'disable_web_page_preview': True}
    if buttons:
        payload['reply_markup'] = {'inline_keyboard': [buttons]}
    try:
        return bool(_call('sendMessage', payload).get('ok'))
    except Exception as exc:
        try:
            from flask import current_app
            current_app.logger.warning('Telegram alert failed: %s', exc)
        except Exception:
            pass
        return False


def find_chats():
    """[(chat_id, name)] of chats that have messaged the bot lately (console → Features: find your chat ID)."""
    found = {}
    for u in (_call('getUpdates').get('result') or []):
        chat = (u.get('message') or u.get('channel_post') or {}).get('chat') or {}
        if chat.get('id'):
            found[chat['id']] = chat.get('title') or ' '.join(filter(None, (chat.get('first_name'), chat.get('last_name')))) \
                or chat.get('username') or str(chat['id'])
    return list(found.items())
