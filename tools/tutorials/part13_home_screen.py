"""Tutorial part 13: QuoteRoom on your home screen (Android and iPhone), opening like an app with your logo.

The browser's own menus can't be captured from a web page, so those steps are plain drawn mock-ups (no browser or
phone maker's branding) over a real screenshot of the app. The icon and name on the home screen are the app's real
ones (/manifest.webmanifest, /app-icon-512.png). Continues on the local tutorial app (any state after part 1).

    python tools/tutorials/part13_home_screen.py http://localhost:5093 <workdir> <admin password>
"""
import base64
import os
import sys

from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]

CSS = '''
  * { box-sizing: border-box; }
  body { margin: 0; width: 390px; height: 844px; overflow: hidden; font: 15px/1.4 -apple-system, system-ui, sans-serif; }
  .bg { position: absolute; inset: 0; background-size: cover; }
  .dim { position: absolute; inset: 0; background: rgba(0,0,0,.38); }
  .menu { position: absolute; top: 10px; right: 8px; width: 240px; background: #fff; border-radius: 14px;
          box-shadow: 0 8px 30px rgba(0,0,0,.3); padding: 6px 0; }
  .menu div, .sheet .row { padding: 13px 18px; color: #1c1c1e; display: flex; justify-content: space-between; }
  .hl { background: #e6f4f1; font-weight: 700; }
  .sheet { position: absolute; left: 8px; right: 8px; bottom: 10px; background: #f2f2f7; border-radius: 16px; padding: 10px 0 6px;
           box-shadow: 0 -6px 30px rgba(0,0,0,.25); }
  .sheet .title { text-align: center; color: #6e6e73; font-size: 13px; padding: 0 0 8px; }
  .sheet .group { background: #fff; margin: 6px 10px; border-radius: 12px; overflow: hidden; }
  .sheet .row + .row { border-top: 1px solid #e5e5ea; }
  .bar { position: absolute; left: 0; right: 0; height: 52px; background: #f7f7f8; border-top: 1px solid #d1d1d6;
         display: flex; align-items: center; justify-content: space-around; color: #3a3a3c; font-size: 22px; }
  .dialog { position: absolute; left: 30px; right: 30px; top: 300px; background: #fff; border-radius: 16px; padding: 20px;
            box-shadow: 0 8px 30px rgba(0,0,0,.3); }
  .dialog .ic { width: 56px; height: 56px; border-radius: 14px; overflow: hidden; float: left; margin-right: 14px; }
  .dialog .ic img { width: 100%; }
  .dialog .btns { clear: both; display: flex; justify-content: flex-end; gap: 22px; padding-top: 18px; font-weight: 700; color: #0f766e; }
  .home { position: absolute; inset: 0; background: linear-gradient(160deg, #23395d, #3d6b75 55%, #8aa79a); }
  .grid { position: absolute; top: 90px; left: 26px; right: 26px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 26px 18px; }
  .app { display: flex; flex-direction: column; align-items: center; gap: 6px; color: #fff; font-size: 11.5px; text-align: center; }
  .tile { width: 62px; height: 62px; border-radius: 16px; background: rgba(255,255,255,.22); overflow: hidden; }
  .tile img { width: 100%; height: 100%; }
  .time { position: absolute; top: 14px; left: 30px; color: #fff; font-weight: 700; }
'''


def page_html(body):
    return f'<html><head><meta name="viewport" content="width=390"><style>{CSS}</style></head><body>{body}</body></html>'


def data_url(path_or_bytes, mime='image/png'):
    raw = path_or_bytes if isinstance(path_or_bytes, bytes) else open(path_or_bytes, 'rb').read()
    return f'data:{mime};base64,' + base64.b64encode(raw).decode()


def part13(page, mock):
    rec = Recorder(page, os.path.join(WORK, 'part13'), 13, 'On your home screen')
    page.goto(BASE + '/projects')
    rec.shot('Open QuoteRoom in one tap, like an app.', 2.4)
    shot = os.path.join(rec.dir, 'app.png')
    page.screenshot(path=shot)
    app_bg = data_url(shot)
    name = page.evaluate('document.querySelector(\'meta[name="apple-mobile-web-app-title"]\').content')
    icon = data_url(page.request.get(BASE + '/app-icon-512.png').body())

    mrec = Recorder(mock, rec.dir, rec.chapter, rec.title)
    mrec.items = rec.items
    bg = f'<div class="bg" style="background-image:url({app_bg})"></div>'

    # Android (Chrome)
    mock.set_content(page_html(bg + '<div class="bar" style="top:0;justify-content:flex-end;padding-right:18px" id="dots">⋮</div>'))
    mrec.tap(mock.locator('#dots'), 'Android (Chrome): tap the three-dot menu, top right.', after_hold=0.6)
    mock.set_content(page_html(bg + '<div class="dim"></div><div class="menu"><div>New tab</div><div>History</div>'
                               '<div>Downloads</div><div class="hl" id="add">Add to Home screen</div><div>Settings</div></div>'))
    mrec.tap(mock.locator('#add'), 'Tap Add to Home screen (or Install app).', after_hold=0.6)
    mock.set_content(page_html(bg + f'<div class="dim"></div><div class="dialog"><div class="ic"><img src="{icon}"></div>'
                               f'<b>Add to Home screen</b><br>{name}<div class="btns"><span>Cancel</span><span id="ok">Add</span></div></div>'))
    mrec.tap(mock.locator('#ok'), 'Tap Add. That is it.', after_hold=1.0)

    # iPhone (Safari)
    mock.set_content(page_html(bg + '<div class="bar" style="bottom:0"><span>‹</span><span>›</span><span id="share">⇪</span>'
                               '<span>☐</span><span>⧉</span></div>'))
    mrec.tap(mock.locator('#share'), 'iPhone (Safari): tap the Share button.', after_hold=0.6)
    mock.set_content(page_html(bg + '<div class="dim"></div><div class="sheet"><div class="title">Share</div>'
                               '<div class="group"><div class="row">Copy <span>⧉</span></div><div class="row">Add Bookmark <span>☆</span></div>'
                               '<div class="row hl" id="add">Add to Home Screen <span>⊞</span></div></div></div>'))
    mrec.tap(mock.locator('#add'), 'Scroll down, tap Add to Home Screen, then Add.', after_hold=1.0)

    # Home screen
    tiles = ''.join('<div class="app"><div class="tile"></div>&nbsp;</div>' for _ in range(10))
    mine = f'<div class="app" id="mine"><div class="tile"><img src="{icon}"></div>{name}</div>'
    mock.set_content(page_html(f'<div class="home"><div class="time">9:41</div><div class="grid">{tiles}{mine}</div></div>'))
    mrec.shot('Your logo and your name, right on the home screen.', 2.6)
    mrec.tap(mock.locator('#mine'), 'One tap…', after_hold=0.4)
    page.goto(BASE + '/projects')
    rec.shot('…and it opens full screen, straight to your quotations. No app store.', 3.0)
    rec.shot('Each person in your team can do this on their own phone.', 2.6)
    rec.save()


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(BASE + '/login')
        page.fill('input[name=username]', 'admin')
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)
        part13(page, ctx.new_page())
        browser.close()


if __name__ == '__main__':
    run()
