"""Tutorial part 11: Online payments with Razorpay (keys, test connection, payment link, the payment records itself).

Continues on the local tutorial app after part 12 (Meena Iyer's confirmed wardrobe quotation, nothing paid yet), with
Razorpay TEST keys saved in Payment Settings by the owner. Recorded in two halves, because the test payment on
Razorpay's page is made by a person:

    python tools/tutorials/part11_online_payments.py http://localhost:5093 <workdir> <admin password> link
        (records up to the payment page and writes <workdir>/part11/link.txt; pay that link in test mode)
    python tools/tutorials/part11_online_payments.py http://localhost:5093 <workdir> <admin password> paid
        (after Razorpay's "paid" message has reached the app: records the payment on the quotation)

Razorpay can't reach a local app, so for recording, the "paid" webhook for the real test payment is delivered by
tools/tutorials/replay_razorpay_webhook.py. The app is started with a sitecustomize that turns off Razorpay's SMS and
email for test links, so no one is messaged. Keys are blanked and the Razorpay account name shows the fictional business.
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD, PHASE = sys.argv[1:5]
BUSINESS = 'Sharma Interiors'
ADVANCE = '25000'


class MaskedRecorder(Recorder):
    """Also blanks API keys and secrets, and shows the fictional business on Razorpay's pages."""
    account = None

    def _mask_local(self):
        super()._mask_local()
        self.page.evaluate("""([account, business]) => {
            document.querySelectorAll('input').forEach(el => {
                if (/^rzp_(test|live)_/.test(el.value)) el.value = 'rzp_test_••••••••••••';
            });
            const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while (walk.nextNode()) {
                const n = walk.currentNode;
                n.nodeValue = n.nodeValue.replace(/\\b[0-9a-f]{40,64}\\b/g, '••••••••••••••••');
                if (account && n.nodeValue.toUpperCase().includes(account)) {
                    n.nodeValue = n.nodeValue.replace(new RegExp(account, 'ig'), business);
                }
            }
        }""", [self.account, BUSINESS])
        if self.account and 'razorpay.com' in self.page.url:
            self.page.evaluate("""([letter, business]) => {
                const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (walk.nextNode()) {
                    const n = walk.currentNode;
                    if (n.nodeValue.trim() === letter && n.parentElement && n.parentElement.children.length === 0) n.nodeValue = business[0];
                }
            }""", [self.account[0], BUSINESS])
        for frame in self.page.frames[1:]:
            if self.account and 'razorpay.com' in frame.url:
                try:
                    frame.evaluate("""([account, business]) => {
                        const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                        while (walk.nextNode()) {
                            const n = walk.currentNode;
                            if (n.nodeValue.toUpperCase().includes(account)) n.nodeValue = n.nodeValue.replace(new RegExp(account, 'ig'), business);
                            else if (n.nodeValue.trim() === account[0] && n.parentElement && n.parentElement.children.length === 0) n.nodeValue = business[0];
                        }
                    }""", [self.account, BUSINESS])
                except Exception:
                    pass


def open_menu_item(rec, page, label, caption):
    rec.tap(page.locator('.navbar-toggler'), caption)
    rec.tap(page.locator('#navbarMain a.nav-link', has_text=label).last, caption, wait=900)


def meena(page):
    page.goto(BASE + '/projects?q=Meena')
    return BASE + page.locator('a[href^="/projects/"]', has_text='View').first.get_attribute('href')


def phase_link(page, browser, rec):
    page.goto(BASE + '/projects')
    rec.shot('Let customers pay you online, by UPI, card or net banking.', 2.4)
    open_menu_item(rec, page, 'Payment Settings', 'Open the menu → Payment Settings.')
    rec.tap(page.locator('details.ki-guide summary'), 'A step-by-step guide shows you how. About 10 minutes, once.',
            after_hold=2.4)
    rec.shot('Sign up at razorpay.com and start in Test mode: fake money, to try it safely.', 3.0)
    key = page.locator('#razorpay_key_id')
    rec.scroll_to(key, 'Paste your Razorpay API Key ID and Secret here.', offset=200)
    rec.shot('Paste your Razorpay API Key ID and Secret here.', 2.4)
    hook = page.locator('#webhook_secret')
    rec.scroll_to(hook, 'Then add a webhook in Razorpay: copy this address and secret.', offset=260)
    rec.shot('Then add a webhook in Razorpay: copy this address and secret.', 3.0)
    rec.shot('That is how Razorpay tells QuoteRoom a customer has paid.', 2.4)
    page.evaluate('window.scrollTo(0, 0)')
    page.wait_for_timeout(300)
    rec.tap(page.locator('button, a', has_text='Test connection').first, 'Tap Test connection.', wait=4000, after_hold=2.6)

    page.goto(meena(page))
    rec.shot("Meena confirmed her wardrobe. Time for the advance.", 2.2)
    amount = page.locator('#payLinkAmount')
    rec.scroll_to(amount, 'Type the amount to collect: the advance, a stage payment, or the full balance.', offset=360)
    rec.type(amount, ADVANCE, 'Type the amount to collect: the advance, a stage payment, or the full balance.', per_frame=1)
    rec.tap(page.locator('#genPayLinkBtn'), 'Tap Payment Link.', wait=6000, after_hold=2.6)
    link = page.locator('#payLinkResult a').first.get_attribute('href')
    rec.shot('Send it on WhatsApp or by email. Or use Payment reminder.', 2.4)

    cust = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
    crec = MaskedRecorder(cust, rec.dir, rec.chapter, rec.title)
    crec.items, crec.account = rec.items, rec.account
    cust.goto(link)
    cust.wait_for_timeout(5000)
    crec.shot('Meena opens the link on her phone…', 2.4)
    crec.tap(cust.get_by_text('Proceed to Pay'), '…and pays by UPI, card or net banking.', wait=7000, after_hold=2.6)
    rec.save()
    with open(os.path.join(rec.dir, 'link.txt'), 'w') as f:
        f.write(link + '\n')
    print('pay this test link:', link)


def phase_paid(page, rec):
    page.goto(BASE + '/projects')
    rec.shot('A few seconds later…', 1.6)
    rec.tap(page.locator('a[href*="notifications"]').first, 'You get a notification: payment received.', wait=1200, after_hold=2.8)
    page.goto(meena(page))
    rec.shot('…and it is already recorded on the quotation.', 2.0)
    pay = page.get_by_text('Razorpay', exact=False).first
    rec.scroll_to(pay, 'Recorded automatically, marked Razorpay, with the new balance.', offset=300)
    rec.shot('Recorded automatically, marked Razorpay, with the new balance.', 3.2)
    rec.shot('No typing payments in. No checking your bank app.', 2.4)
    rec.shot('When you are ready, switch Razorpay to Live mode and save the live keys.', 3.0)
    rec.save()


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
        page.goto(BASE + '/login')
        page.fill('input[name=username]', 'admin')
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)
        rec = MaskedRecorder(page, os.path.join(WORK, 'part11'), 11, 'Online payments')
        rec.account = os.environ.get('RAZORPAY_ACCOUNT_NAME', '').upper() or None
        if PHASE == 'link':
            phase_link(page, browser, rec)
        else:
            with open(os.path.join(rec.dir, 'timeline.json')) as f:
                rec.items = json.load(f)['items']
            phase_paid(page, rec)
        browser.close()


if __name__ == '__main__':
    run()
