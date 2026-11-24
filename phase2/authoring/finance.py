"""Finance: UPI settlement close and GST payables register."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
import random
import re

from .core import YES_NO, Code, Date, Id, Int, Money, Table, Text, half_up, out_num, task

CLOSE = date(2026, 11, 15)


def utr(rng, used):
    while True:
        value = str(rng.randint(10 ** 11, 10 ** 12 - 1))
        if value not in used:
            used.add(value)
            return value


def upi_settlement():
    tid = '01-upi-settlement'
    rng = random.Random(tid)
    invoices = []
    for index in range(36):
        issued = date(2026, 11, 1) + timedelta(days=rng.randint(0, 13))
        amount = rng.choice([rng.randint(8, 600) * 10, rng.randint(100, 900) * 10 + 5,
                             rng.randint(10000, 180000)])
        invoices.append([f'INV-{101 + index:04d}', f'C{rng.randint(1, 12):02d}', issued, amount])
    used = set()
    pays = []

    def pay(inv, when, amount):
        pays.append({'utr': utr(rng, used), 'kind': 'PAY', 'invoice': inv, 'ref': None,
                     'date': when, 'amount': amount, 'note': None})

    scenarios = ['full'] * 12 + ['split'] * 9 + ['partial'] * 5 + ['unpaid'] * 3 + ['over'] * 4 + ['late'] * 3
    rng.shuffle(scenarios)
    for (inv, _, issued, amount), kind in zip(invoices, scenarios):
        when = min(issued + timedelta(days=rng.randint(0, 3)), CLOSE)
        if kind == 'full':
            pay(inv, when, amount)
        elif kind == 'split':
            first = amount * rng.randint(3, 7) // 10
            pay(inv, when, first)
            pay(inv, min(when + timedelta(days=rng.randint(0, 2)), CLOSE), amount - first)
        elif kind == 'partial':
            pay(inv, when, amount * rng.randint(4, 8) // 10)
        elif kind == 'over':
            pay(inv, when, amount + rng.randint(5, 50) * 10)
        elif kind == 'late':
            pay(inv, CLOSE + timedelta(days=rng.randint(1, 3)), amount)
    # Boundary dates: some payments land exactly on the close date.
    for item in rng.sample([p for p in pays if p['date'] < CLOSE], 4):
        item['date'] = CLOSE
    numbers = [row[0] for row in invoices]
    for item in rng.sample(pays, 9):
        item['note'] = {'en': f"UPI ref for {item['invoice']}", 'hi': f"{item['invoice']} के लिए यूपीआई भुगतान"}
        item['invoice'] = None
    for item in rng.sample([p for p in pays if p['invoice'] and not p['note']], 6):
        other = rng.choice([n for n in numbers if n != item['invoice']])
        item['note'] = {'en': f'customer also mentioned {other}', 'hi': f'ग्राहक ने {other} का भी ज़िक्र किया'}
    for item in pays:
        if item['note'] is None and rng.random() < 0.3:
            item['note'] = {'en': 'UPI collect', 'hi': 'यूपीआई कलेक्ट'}

    counted = [p for p in pays if p['date'] <= CLOSE]
    late = [p for p in pays if p['date'] > CLOSE]
    revs = []
    targets = rng.sample(counted, 8) + late[:1]
    for index, original in enumerate(targets):
        when = original['date'] + timedelta(days=rng.randint(0, 1))
        if index == 0:
            when = CLOSE + timedelta(days=1)
        revs.append({'utr': utr(rng, used), 'kind': 'REV', 'invoice': None, 'ref': original['utr'],
                     'date': when, 'amount': max(10, original['amount'] * rng.randint(1, 4) // 10 // 10 * 10),
                     'note': {'en': 'chargeback', 'hi': 'चार्जबैक'}})

    amendments = []
    plain_pays = [p for p in counted if p['utr'] not in {t['utr'] for t in targets}]
    pick = rng.sample(plain_pays, 12)
    for item in pick[:5]:
        amendments.append([item['utr'], 'SET_AMOUNT', item['amount'] + rng.randint(-20, 20) * 10 or 100, None])
    twice = pick[0]
    amendments.append([twice['utr'], 'SET_AMOUNT', twice['amount'] + 990, None])
    for item in pick[5:8]:
        amendments.append([item['utr'], 'SET_INVOICE', None, rng.choice(numbers)])
    blank_note = next(p for p in pays if p['invoice'] is None and p['date'] <= CLOSE and p not in pick)
    amendments.append([blank_note['utr'], 'SET_INVOICE', None, rng.choice(numbers)])
    for item in pick[8:10] + [targets[1]]:
        amendments.append([item['utr'], 'VOID', None, None])
    amendments.append([revs[2]['utr'], 'VOID', None, None])
    seqs = list(range(1, len(amendments) + 1))
    # The second SET_AMOUNT on the same UTR must carry the higher seq and appear earlier in the file.
    amend_rows = [[seq, *row] for seq, row in zip(seqs, amendments)]
    file_amends = amend_rows[:]
    rng.shuffle(file_amends)
    if file_amends.index(amend_rows[5]) > file_amends.index(amend_rows[0]):
        a, b = file_amends.index(amend_rows[5]), file_amends.index(amend_rows[0])
        file_amends[a], file_amends[b] = file_amends[b], file_amends[a]

    rows = pays + revs
    rng.shuffle(rows)
    for original in rng.sample(pays[:30], 5) + [revs[3]]:
        position = rows.index(original)
        rows.insert(rng.randint(position + 1, len(rows)), dict(original))

    def solve(off=frozenset()):
        entries = []
        seen = set()
        for row in rows:
            if row['utr'] in seen and 'dedup' not in off:
                continue
            seen.add(row['utr'])
            entries.append({**row, 'void': False})
        by_utr = {}
        for entry in entries:
            by_utr.setdefault(entry['utr'], []).append(entry)
        order = file_amends if 'seq' in off else sorted(file_amends)
        if 'amend' not in off:
            for _, code, action, amount, inv in order:
                for entry in by_utr[code]:
                    if action == 'SET_AMOUNT':
                        entry['amount'] = amount
                    elif action == 'SET_INVOICE':
                        entry['invoice'] = inv
                    else:
                        entry['void'] = True

        def in_window(entry):
            if 'cutoff' in off:
                return True
            return entry['date'] < CLOSE if 'cutoff_exclusive' in off else entry['date'] <= CLOSE

        def invoice_of(entry):
            note = re.search(r'INV-\d{4}', entry['note']['en']) if entry['note'] else None
            if 'note_first' in off and note:
                return note[0]
            if entry['invoice']:
                return entry['invoice']
            return None if 'note' in off or not note else note[0]

        def counts(entry):
            return not entry['void'] and in_window(entry)

        net = {row[0]: 0 for row in invoices}
        for entry in entries:
            if entry['kind'] == 'PAY' and counts(entry) and invoice_of(entry) in net:
                net[invoice_of(entry)] += entry['amount']
        if 'reversals' not in off:
            for entry in entries:
                if entry['kind'] != 'REV' or not counts(entry):
                    continue
                original = by_utr[entry['ref']][0]
                if not counts(original) and 'rev_orig' not in off:
                    continue
                if invoice_of(original) in net:
                    net[invoice_of(original)] -= entry['amount']
        answer = []
        for inv, _, _, amount in invoices:
            received = net[inv]
            status = ('UNPAID' if received <= 0 else 'PARTIAL' if received < amount
                      else 'PAID' if received == amount else 'OVERPAID')
            answer.append([inv, str(received), str(max(amount - received, 0)), status])
        return answer

    kind = Code({'PAY': (['PAY', 'Payment'], ['भुगतान']), 'REV': (['REV', 'Reversal'], ['वापसी'])})
    action = Code({'SET_AMOUNT': (['SET_AMOUNT'], ['राशि बदलें']), 'SET_INVOICE': (['SET_INVOICE'], ['बिल बदलें']),
                   'VOID': (['VOID', 'void'], ['रद्द'])})
    tables = [
        Table('invoices', [('invoice', 'बिल संख्या', Id()), ('customer', 'ग्राहक', Id()),
                           ('issued', 'जारी तिथि', Date()), ('amount', 'राशि', Money())], invoices, tid),
        Table('payments', [('utr', 'यूटीआर', Id()), ('kind', 'प्रकार', kind), ('invoice', 'बिल संख्या', Id()),
                           ('reverses_utr', 'मूल यूटीआर', Id()), ('paid_on', 'तारीख', Date()),
                           ('amount', 'राशि', Money()), ('note', 'टिप्पणी', Text())],
              [[r['utr'], r['kind'], r['invoice'], r['ref'], r['date'], r['amount'], r['note']] for r in rows], tid),
        Table('amendments', [('seq', 'क्रम', Int()), ('utr', 'यूटीआर', Id()), ('action', 'कार्रवाई', action),
                             ('amount', 'राशि', Money()), ('invoice', 'बिल संख्या', Id())], file_amends, tid),
    ]
    notice = {
        'en': """Close the UPI collections for 1-15 November 2026.
1. A payment is identified by its UTR. If the same UTR appears more than once with identical details, it is a repeated transmission: count it once.
2. If the invoice column of a PAY row is blank, use the INV number written in its note. When the invoice column is filled it is authoritative, even if the note mentions another invoice.
3. Apply amendments.csv in ascending seq order; the file is not sorted. SET_AMOUNT replaces the amount, SET_INVOICE replaces the invoice, and VOID cancels the payment or reversal with that UTR. If several amendments change the same field, the highest seq wins.
4. A REV row reverses part of the payment named in reverses_utr. It reduces the received amount of that payment's invoice, using the payment's amended invoice.
5. Only rows dated on or before 15 November 2026 count. A reversal counts only if the payment it reverses also counts.
6. Report every invoice in invoices.csv. net_received = counted payments minus counted reversals. due = invoice amount minus net_received, or 0 if that would be negative. status is UNPAID if net_received is 0 or less, PARTIAL if it is below the invoice amount, PAID if it is equal, and OVERPAID if it is above.""",
        'hi': """1 से 15 नवंबर 2026 तक के यूपीआई संग्रह का हिसाब बंद करें।
1. हर भुगतान की पहचान उसके यूटीआर से होती है। अगर एक ही यूटीआर बिल्कुल समान विवरण के साथ एक से ज़्यादा बार आए, तो वह दोबारा भेजी गई प्रविष्टि है: उसे सिर्फ़ एक बार गिनें।
2. अगर भुगतान वाली पंक्ति में बिल संख्या खाली है, तो उसकी टिप्पणी में लिखी INV संख्या लें। बिल संख्या भरी हो तो वही मान्य है, भले ही टिप्पणी में किसी दूसरे बिल का ज़िक्र हो।
3. amendments.csv को क्रम (seq) के बढ़ते क्रम में लागू करें; फ़ाइल क्रमबद्ध नहीं है। "राशि बदलें" राशि को बदल देता है, "बिल बदलें" बिल संख्या को बदल देता है, और "रद्द" उस यूटीआर वाले भुगतान या वापसी को रद्द करता है। अगर कई संशोधन एक ही फ़ील्ड बदलें, तो सबसे बड़े क्रम वाला मान्य है।
4. वापसी वाली पंक्ति "मूल यूटीआर" में दिए गए भुगतान का कुछ हिस्सा लौटाती है। यह उस भुगतान के बिल की प्राप्त राशि घटाती है, और बिल वही माना जाएगा जो संशोधनों के बाद उस भुगतान का है।
5. सिर्फ़ 15 नवंबर 2026 या उससे पहले की तारीख वाली पंक्तियाँ गिनी जाएँगी। वापसी तभी गिनी जाएगी जब उससे जुड़ा भुगतान भी गिना जाए।
6. invoices.csv के हर बिल की रिपोर्ट दें। net_received = गिने गए भुगतान घटा गिनी गई वापसी। due = बिल की राशि घटा net_received, और अगर यह ऋणात्मक हो तो 0। status: net_received 0 या उससे कम हो तो UNPAID, बिल की राशि से कम हो तो PARTIAL, बराबर हो तो PAID, और ज़्यादा हो तो OVERPAID।""",
    }
    return task(
        id=tid, title='UPI settlement close', domain='finance',
        goals={'en': 'Close the shop\'s UPI collections and report the settled position of every invoice.',
               'hi': 'दुकान के यूपीआई संग्रह का हिसाब बंद करें और हर बिल की निपटान स्थिति बताएँ।',
               'hinglish': 'Shop ke UPI collections ka hisaab close karo aur har invoice ki settlement position batao.'},
        notice=notice, tables=tables, output=['invoice', 'net_received', 'due', 'status'],
        numeric=['net_received', 'due'], answer=solve(), solve=solve,
        ablations=['dedup', 'note', 'note_first', 'amend', 'seq', 'cutoff', 'cutoff_exclusive', 'reversals', 'rev_orig'])


STATES = ['27', '29', '07', '09', '24', '33', '19', '06']
RATES = {'FOOD': 5, 'PACKAGING': 12, 'ELECTRICAL': 18, 'SERVICES': 18}


def gstin(rng, state):
    letters = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
    pan = ''.join(rng.choice(letters) for _ in range(5)) + f'{rng.randint(0, 9999):04d}' + rng.choice(letters)
    return state + pan + '1Z' + rng.choice(letters + '0123456789')


def norm_invoice(text):
    text = re.sub(r'[\s/-]', '', text).upper()
    return re.sub(r'\d+', lambda m: str(int(m[0])), text)


def gst_payables():
    tid = '02-gst-payables'
    rng = random.Random(tid)
    names = [('Sharma Traders', 'शर्मा ट्रेडर्स'), ('Gupta Packaging', 'गुप्ता पैकेजिंग'),
             ('Verma Electricals', 'वर्मा इलेक्ट्रिकल्स'), ('Patel Foods', 'पटेल फ़ूड्स'),
             ('Iyer Services', 'अय्यर सर्विसेज़'), ('Khan Supplies', 'ख़ान सप्लाइज़'),
             ('Das Logistics', 'दास लॉजिस्टिक्स'), ('Mehta Agro', 'मेहता एग्रो')]
    tds_flags = [True, False, True, False, True, False, False, False]
    suppliers = [[f'S{i + 1:02d}', {'en': en, 'hi': hi}, STATES[i], tds_flags[i]]
                 for i, (en, hi) in enumerate(names)]
    gst_ids = {s[0]: gstin(rng, s[2]) for s in suppliers}
    prefixes = {s[0]: rng.choice(['INV', 'SI', 'BILL']) for s in suppliers}
    categories = list(RATES)
    entries = []
    counter = {s[0]: rng.randint(10, 60) for s in suppliers}

    def surface(prefix, number):
        return rng.choice([f'{prefix}-{number:04d}', f'{prefix.lower()} {number}', f'{prefix}/{number:03d}',
                           f'{prefix.title()}-{number}'])

    def add(supplier, number, when=None, taxable=None):
        when = when or date(2026, 11, 1) + timedelta(days=rng.randint(0, 19))
        if taxable is None:
            taxable = rng.choice([rng.randint(40, 600) * 50 + 25, rng.randint(200, 3000) * 10,
                                  rng.randint(20, 300) * 20 + 10])
        entries.append({'supplier': supplier, 'number': surface(prefixes[supplier], number), 'date': when,
                        'category': rng.choice(categories), 'taxable': taxable, 'gstin': gst_ids[supplier]})

    for s in suppliers:
        heavy = s[3]
        for _ in range(rng.randint(8, 10) if heavy else rng.randint(4, 6)):
            counter[s[0]] += 1
            add(s[0], counter[s[0]], taxable=rng.randint(80, 300) * 50 + 25 if heavy else None)
    rng.shuffle(entries)
    # Resubmitted duplicates: same supplier and number written differently.
    for original in rng.sample(entries, 8):
        number = int(re.search(r'\d+', original['number'])[0])
        copy = dict(original, number=surface(prefixes[original['supplier']], number),
                    date=original['date'] + timedelta(days=rng.randint(0, 3)))
        entries.insert(rng.randint(entries.index(original) + 1, len(entries)), copy)
    # Decoys: same digits for another supplier, and a number that only shares a prefix.
    decoy = entries[3]
    other = next(s[0] for s in suppliers if s[0] != decoy['supplier'])
    entries.append(dict(decoy, supplier=other, gstin=gst_ids[other]))
    number = int(re.search(r'\d+', entries[5]['number'])[0])
    entries.append(dict(entries[5], number=surface(prefixes[entries[5]['supplier']], number * 10)))
    for index, entry in enumerate(entries):
        entry['entry'] = f'E{index + 1:03d}'
    bad = rng.sample(entries, 7)
    for item in bad[:4]:
        wrong = rng.choice([s for s in STATES if s != item['gstin'][:2]])
        item['gstin'] = wrong + item['gstin'][2:]
    for item in bad[4:]:
        item['gstin'] = item['gstin'][:-1]
    for item in rng.sample(entries, 10):
        value = item['gstin']
        item['gstin'] = rng.choice([value.lower(), value[:2] + ' ' + value[2:12] + ' ' + value[12:]])

    amendments = []
    pool = [e for e in entries if e not in bad]
    for item in rng.sample(pool, 5):
        amendments.append([item['entry'], 'SET_TAXABLE', item['taxable'] + rng.randint(1, 40) * 50, None])
    amendments.append([bad[0]['entry'], 'SET_GSTIN', None, gst_ids[bad[0]['supplier']]])
    dup_originals = {}
    for e in entries:
        dup_originals.setdefault((e['supplier'], norm_invoice(e['number'])), []).append(e)
    groups = [g for g in dup_originals.values() if len(g) > 1]
    amendments.append([groups[0][0]['entry'], 'CANCEL', None, None])
    amendments.append([rng.choice(pool)['entry'], 'CANCEL', None, None])
    amendments = [[seq, *row] for seq, row in enumerate(amendments, 1)]
    file_amends = amendments[:]
    rng.shuffle(file_amends)

    supplier_info = {s[0]: s for s in suppliers}

    def solve(off=frozenset()):
        data = {e['entry']: dict(e) for e in entries}
        cancelled = set()
        if 'amend' not in off:
            for _, entry, act, taxable, gid in sorted(file_amends):
                if act == 'SET_TAXABLE':
                    data[entry]['taxable'] = taxable
                elif act == 'SET_GSTIN':
                    data[entry]['gstin'] = gid
                else:
                    cancelled.add(entry)
        decision = {}
        ordered = sorted(data, key=lambda k: int(k[1:]), reverse='dup_latest' in off)
        seen = {}
        for key in ordered:
            if key in cancelled:
                decision[key] = 'CANCELLED'
                if 'cancel_first' not in off:
                    continue
            item = data[key]
            number = item['number'].strip().upper() if 'normalize' in off else norm_invoice(item['number'])
            group = (item['supplier'], number)
            if group in seen and 'dup' not in off:
                decision.setdefault(key, 'HOLD_DUP')
                continue
            seen[group] = key
            if key in cancelled:
                continue
            code = item['gstin'].replace(' ', '').upper()
            state = supplier_info[item['supplier']][2]
            if 'gstin' not in off and (len(code) != 15 or not code.startswith(state)):
                decision[key] = 'HOLD_GSTIN'
            else:
                decision[key] = 'PAY'
        rounding = (lambda v: D2(v).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)) if 'bankers' in off else half_up
        tds = {key: 0 for key in data}
        for supplier, _, _, flag in suppliers:
            if not flag or 'tds_never' in off:
                continue
            mine = [k for k in data if data[k]['supplier'] == supplier and decision[k] == 'PAY']
            mine.sort(key=(lambda k: int(k[1:])) if 'tds_order_entry' in off else
                      (lambda k: (data[k]['date'], int(k[1:]))))
            total = 0
            crossed = False
            for k in mine:
                total += data[k]['taxable']
                if 'tds_all' in off or (crossed if 'tds_after' in off else total > 50000):
                    tds[k] = int(rounding(D2(data[k]['taxable']) * 2 / 100))
                crossed = crossed or total > 50000
        answer = []
        for key in sorted(data, key=lambda k: int(k[1:])):
            if decision[key] != 'PAY':
                answer.append([key, decision[key], '0', '0', '0'])
                continue
            taxable = data[key]['taxable']
            gst = int(rounding(D2(taxable) * RATES[data[key]['category']] / 100))
            answer.append([key, 'PAY', str(gst), str(tds[key]), str(taxable + gst - tds[key])])
        return answer

    category = Code({'FOOD': (['FOOD', 'Food'], ['खाद्य']), 'PACKAGING': (['PACKAGING', 'Packaging'], ['पैकेजिंग']),
                     'ELECTRICAL': (['ELECTRICAL', 'Electrical'], ['बिजली सामान']),
                     'SERVICES': (['SERVICES', 'Services'], ['सेवाएँ'])})
    action = Code({'SET_TAXABLE': (['SET_TAXABLE'], ['कर योग्य मूल्य बदलें']), 'SET_GSTIN': (['SET_GSTIN'], ['जीएसटीआईएन बदलें']),
                   'CANCEL': (['CANCEL', 'cancel'], ['रद्द'])})
    tables = [
        Table('suppliers', [('supplier', 'आपूर्तिकर्ता', Id()), ('name', 'नाम', Text()),
                            ('state_code', 'राज्य कोड', Id(noisy=False)), ('tds_applicable', 'टीडीएस लागू', YES_NO)],
              suppliers, tid),
        Table('invoices', [('entry', 'प्रविष्टि', Id()), ('supplier', 'आपूर्तिकर्ता', Id()),
                           ('supplier_invoice_no', 'आपूर्तिकर्ता बिल संख्या', Text()), ('invoice_date', 'बिल तिथि', Date()),
                           ('category', 'श्रेणी', category), ('taxable_value', 'कर योग्य मूल्य', Money()),
                           ('gstin', 'जीएसटीआईएन', Text())],
              [[e['entry'], e['supplier'], e['number'], e['date'], e['category'], e['taxable'], e['gstin']]
               for e in entries], tid),
        Table('amendments', [('seq', 'क्रम', Int()), ('entry', 'प्रविष्टि', Id()), ('action', 'कार्रवाई', action),
                             ('taxable_value', 'कर योग्य मूल्य', Money()), ('gstin', 'जीएसटीआईएन', Text())],
              file_amends, tid),
    ]
    notice = {
        'en': """Prepare the November 2026 accounts-payable register.
1. Apply amendments.csv in ascending seq order (the file is not sorted). SET_TAXABLE replaces the taxable value, SET_GSTIN replaces the GSTIN, and CANCEL cancels the entry.
2. A cancelled entry gets decision CANCELLED and takes no further part: it is never the original of a duplicate group and never counts towards TDS.
3. Duplicates: two remaining entries are the same invoice when they have the same supplier and the same normalized supplier invoice number. To normalize, remove spaces, hyphens and slashes, convert to upper case, and drop leading zeros from every run of digits (so "inv 42", "INV/042" and "INV-0042" are the same, but "INV-420" is not). The entry with the lowest entry number is the original; every other entry in the group is HOLD_DUP.
4. GSTIN check for originals: ignore spaces and letter case. The GSTIN must have exactly 15 characters and begin with the supplier's two-digit state code from suppliers.csv. Otherwise the decision is HOLD_GSTIN.
5. All other entries are PAY. GST = taxable value × category rate, rounded half up to whole rupees. Rates: FOOD 5%, PACKAGING 12%, ELECTRICAL 18%, SERVICES 18%.
6. TDS applies only to suppliers marked yes in suppliers.csv. Take that supplier's PAY entries in invoice-date order (ties by entry number) and keep a running total of taxable value. The entry that takes the running total above 50,000 and every later entry have TDS = 2% of their own taxable value, rounded half up to whole rupees. Earlier entries have TDS 0.
7. payable = taxable value + GST - TDS. For HOLD_DUP, HOLD_GSTIN and CANCELLED, write gst, tds and payable as 0. Report every entry.""",
        'hi': """नवंबर 2026 का देय खाता रजिस्टर तैयार करें।
1. amendments.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है)। "कर योग्य मूल्य बदलें" कर योग्य मूल्य को बदलता है, "जीएसटीआईएन बदलें" जीएसटीआईएन को बदलता है, और "रद्द" उस प्रविष्टि को रद्द करता है।
2. रद्द प्रविष्टि का decision CANCELLED होगा और आगे की किसी गणना में उसका कोई हिस्सा नहीं होगा: वह किसी डुप्लिकेट समूह की मूल प्रविष्टि नहीं बनेगी और टीडीएस की गिनती में नहीं जुड़ेगी।
3. डुप्लिकेट: बची हुई दो प्रविष्टियाँ एक ही बिल हैं अगर उनका आपूर्तिकर्ता और सामान्यीकृत आपूर्तिकर्ता बिल संख्या एक हो। सामान्यीकरण के लिए स्पेस, हाइफ़न और स्लैश हटाएँ, सब अक्षर बड़े (अपर केस) करें, और अंकों के हर समूह से शुरुआती शून्य हटाएँ (इसलिए "inv 42", "INV/042" और "INV-0042" एक ही हैं, पर "INV-420" अलग है)। सबसे छोटी प्रविष्टि संख्या वाली प्रविष्टि मूल है; समूह की बाकी हर प्रविष्टि HOLD_DUP है।
4. मूल प्रविष्टियों के जीएसटीआईएन की जाँच: स्पेस और अक्षरों के छोटे-बड़े रूप को नज़रअंदाज़ करें। जीएसटीआईएन में ठीक 15 अक्षर होने चाहिए और वह suppliers.csv में दिए आपूर्तिकर्ता के दो अंकों वाले राज्य कोड से शुरू होना चाहिए। वरना decision HOLD_GSTIN है।
5. बाकी सभी प्रविष्टियाँ PAY हैं। GST = कर योग्य मूल्य × श्रेणी की दर, पूरे रुपये में राउंड हाफ़ अप (0.5 या उससे ज़्यादा हो तो ऊपर)। दरें: खाद्य 5%, पैकेजिंग 12%, बिजली सामान 18%, सेवाएँ 18%।
6. टीडीएस सिर्फ़ उन्हीं आपूर्तिकर्ताओं पर लागू है जिनके आगे suppliers.csv में हाँ लिखा है। उस आपूर्तिकर्ता की PAY प्रविष्टियाँ बिल तिथि के क्रम में लें (तिथि बराबर हो तो प्रविष्टि संख्या के क्रम में) और कर योग्य मूल्य का चालू योग रखें। जिस प्रविष्टि से चालू योग 50,000 से ऊपर जाता है, उस पर और उसके बाद की हर प्रविष्टि पर TDS = उसके अपने कर योग्य मूल्य का 2%, पूरे रुपये में राउंड हाफ़ अप। उससे पहले की प्रविष्टियों पर TDS 0 है।
7. payable = कर योग्य मूल्य + GST - TDS। HOLD_DUP, HOLD_GSTIN और CANCELLED के लिए gst, tds और payable में 0 लिखें। हर प्रविष्टि की रिपोर्ट दें।""",
    }
    return task(
        id=tid, title='GST payables register', domain='finance',
        goals={'en': 'Build the November payables register with the decision and amounts for every supplier invoice entry.',
               'hi': 'नवंबर का देय रजिस्टर बनाएँ, जिसमें आपूर्तिकर्ताओं की हर बिल प्रविष्टि का निर्णय और राशि हो।',
               'hinglish': 'November ka payables register banao, har supplier invoice entry ka decision aur amounts ke saath.'},
        notice=notice, tables=tables, output=['entry', 'decision', 'gst', 'tds', 'payable'],
        numeric=['gst', 'tds', 'payable'], answer=solve(), solve=solve,
        ablations=['amend', 'cancel_first', 'dup', 'normalize', 'dup_latest', 'gstin', 'bankers', 'tds_never',
                   'tds_order_entry', 'tds_all', 'tds_after'])


def D2(value):
    return Decimal(str(value))


TASKS = [upi_settlement, gst_payables]
