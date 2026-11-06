"""Numbers the Indian way: 15,50,000.00 (lakh and crore grouping), for amounts, quantities and areas everywhere: the
PDFs, the app's pages (the `inr` template filter), messages and emails."""


def inr(value, dp=2):
    """1550000 → '15,50,000.00'; dp=0 → '15,50,000'; negative numbers keep their sign. None → ''."""
    if value is None:
        return ''
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f'{abs(number):.{dp}f}'
    whole, _, fraction = text.partition('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        whole = ','.join(([head] if head else []) + pairs + [tail])
    out = whole + (f'.{fraction}' if fraction else '')
    return f'-{out}' if number < 0 and float(text) != 0 else out
