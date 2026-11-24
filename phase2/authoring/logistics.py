"""Logistics: parcel dispatch dates and charges, and proof-of-delivery audit."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import math
import random

from .core import YES_NO, Code, Date, DateTime, Id, Int, Money, Qty, Table, Text, half_up, out_date, out_num, task

CUTOFF = {('D1', 'REG'): 14 * 60 + 30, ('D1', 'EXP'): 16 * 60, ('D2', 'REG'): 15 * 60, ('D2', 'EXP'): 17 * 60 + 30}
HOLIDAYS = [['D1', date(2026, 11, 20)], ['D2', date(2026, 11, 19)], ['ALL', date(2026, 11, 24)]]
RATES = {'REG': (40, 30), 'EXP': (70, 45)}
WEIGHT = Qty({'KG': (['kg', 'KG'], ['किलो', 'कि.ग्रा.']), 'G': (['g', 'gm'], ['ग्राम'])})


def parcel_dispatch():
    tid = '11-parcel-dispatch'
    rng = random.Random(tid)
    parcels = []
    for index in range(96):
        depot = rng.choice(['D1', 'D2'])
        service = rng.choice(['REG', 'REG', 'EXP'])
        day = date(2026, 11, 14) + timedelta(days=rng.randint(0, 10))
        cut = CUTOFF[(depot, service)]
        minutes = rng.choice([cut, cut, cut + 1, cut - 1, rng.randint(6 * 60, 22 * 60 + 59)])
        booked = datetime(day.year, day.month, day.day) + timedelta(minutes=minutes)
        grams = rng.choice([rng.randint(1, 40) * 50, rng.randint(2, 60) * 100, rng.randint(1, 24) * 500])
        weight = (Decimal(grams), 'G') if grams < 1000 and rng.random() < 0.7 else (Decimal(grams) / 1000, 'KG')
        dims = (rng.randint(10, 60), rng.randint(8, 45), rng.randint(5, 40))
        cod = rng.random() < 0.3
        value = rng.choice([rng.randint(2, 140) * 10, rng.randint(150, 900) * 10 + 5]) if cod else rng.randint(1, 50) * 100
        parcels.append([f'P{index + 1:04d}', depot, service, booked, weight, dims, cod, value])
    amendments = []
    picks = rng.sample(parcels, 10)
    for p in picks[:3]:
        amendments.append([p[0], 'SET_SERVICE', 'EXP' if p[2] == 'REG' else 'REG', None])
    for p in picks[3:6]:
        amendments.append([p[0], 'SET_WEIGHT', None, (Decimal(rng.randint(3, 30)) / 2, 'KG')])
    for p in picks[6:9]:
        amendments.append([p[0], 'CANCEL', None, None])
    amendments.append([picks[0][0], 'SET_SERVICE', picks[0][2], None])
    amendments = [[seq, *row] for seq, row in enumerate(amendments, 1)]
    file_amends = amendments[:]
    rng.shuffle(file_amends)

    def kg(weight):
        return weight[0] / 1000 if weight[1] == 'G' else weight[0]

    def solve(off=frozenset()):
        data = {p[0]: {'depot': p[1], 'service': p[2], 'booked': p[3], 'weight': p[4], 'dims': p[5], 'cod': p[6],
                       'value': p[7], 'cancel': False} for p in parcels}
        if 'amend' not in off:
            for _, key, act, service, weight in sorted(file_amends):
                if act == 'SET_SERVICE':
                    data[key]['service'] = service
                elif act == 'SET_WEIGHT':
                    data[key]['weight'] = weight
                else:
                    data[key]['cancel'] = True

        def business(depot, day):
            if day.weekday() == 6 and 'sunday' not in off:
                return False
            if 'holidays' in off:
                return True
            return not any(d == day and h in (depot, 'ALL') for h, d in HOLIDAYS)

        answer = []
        for key, item in data.items():
            if item['cancel']:
                continue
            depot, service = item['depot'], item['service']
            cut = CUTOFF[('D1', service) if 'depot_cutoff' in off else (depot, service)]
            day = item['booked'].date()
            minutes = item['booked'].hour * 60 + item['booked'].minute
            on_time = minutes < cut if 'cutoff_exclusive' in off else minutes <= cut
            if not (business(depot, day) and on_time):
                day += timedelta(days=1)
                while not business(depot, day):
                    day += timedelta(days=1)
            actual = kg(item['weight'])
            l, w, h = item['dims']
            volumetric = Decimal(l * w * h) / 5000
            charge_kg = actual if 'volumetric' in off else max(actual, volumetric)
            steps = charge_kg * 2
            halves = int(half_up(steps)) if 'round_nearest' in off else math.ceil(steps)
            halves = max(halves, 1)
            first, extra = RATES[service]
            charge = first + extra * (halves - 1)
            if item['cod'] and 'cod_off' not in off:
                charge += 30 if 'cod_flat' in off else max(30, int(half_up(Decimal(item['value']) * 2 / 100)))
            answer.append([key, out_date(day), out_num(Decimal(halves) / 2, 1), str(charge)])
        return answer

    service = Code({'REG': (['REG', 'Regular'], ['सामान्य']), 'EXP': (['EXP', 'Express'], ['एक्सप्रेस'])})
    action = Code({'SET_SERVICE': (['SET_SERVICE'], ['सेवा बदलें']), 'SET_WEIGHT': (['SET_WEIGHT'], ['वज़न बदलें']),
                   'CANCEL': (['CANCEL'], ['रद्द'])})
    depot_code = Code({'D1': (['D1'], ['D1']), 'D2': (['D2'], ['D2']), 'ALL': (['ALL'], ['सभी'])})

    def dims_text(d):
        return {'en': f'{d[0]}x{d[1]}x{d[2]} cm', 'hi': f'{d[0]}×{d[1]}×{d[2]} सेमी'}

    tables = [
        Table('holidays', [('depot', 'डिपो', depot_code), ('date', 'तारीख', Date())], HOLIDAYS, tid),
        Table('parcels', [('parcel', 'पार्सल', Id()), ('depot', 'डिपो', depot_code), ('service', 'सेवा', service),
                          ('booked', 'बुकिंग समय', DateTime()), ('weight', 'वज़न', WEIGHT), ('dimensions', 'माप', Text()),
                          ('cod', 'कैश ऑन डिलीवरी', YES_NO), ('declared_value', 'घोषित मूल्य', Money())],
              [[p[0], p[1], p[2], p[3], p[4], dims_text(p[5]), p[6], p[7]] for p in parcels], tid),
        Table('amendments', [('seq', 'क्रम', Int()), ('parcel', 'पार्सल', Id()), ('action', 'कार्रवाई', action),
                             ('service', 'सेवा', service), ('weight', 'वज़न', WEIGHT)], file_amends, tid),
    ]
    notice = {
        'en': """Plan dispatch dates and charges for parcels booked 14-24 November 2026.
1. Apply amendments.csv in ascending seq order (the file is not sorted): SET_SERVICE replaces the service, SET_WEIGHT replaces the weight, and CANCEL cancels the parcel. Leave cancelled parcels out of the output.
2. A depot works every day except Sundays and its holidays in holidays.csv (depot ALL means both depots).
3. Same-day cutoffs, inclusive: D1 REG 14:30, D1 EXP 16:00, D2 REG 15:00, D2 EXP 17:30. A parcel booked on a working day at or before its cutoff is dispatched that day. Otherwise it is dispatched on the next working day of its depot.
4. Chargeable weight = the larger of the actual weight in kg (1000 g = 1 kg) and the volumetric weight (length × width × height in cm / 5000), rounded up to the next multiple of 0.5 kg (an exact multiple stays as it is).
5. Charge: REG Rs 40 for the first 0.5 kg plus Rs 30 for each further 0.5 kg; EXP Rs 70 for the first 0.5 kg plus Rs 45 for each further 0.5 kg. Cash-on-delivery parcels add the larger of Rs 30 and 2% of the declared value, rounded half up to whole rupees.
6. Report each remaining parcel: dispatch_date (YYYY-MM-DD), chargeable_kg with one decimal place, and charge in whole rupees.""",
        'hi': """14-24 नवंबर 2026 को बुक हुए पार्सलों की भेजने की तारीख और शुल्क तय करें।
1. amendments.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है): "सेवा बदलें" सेवा बदलता है, "वज़न बदलें" वज़न बदलता है, और "रद्द" पार्सल रद्द करता है। रद्द पार्सलों को आउटपुट में शामिल न करें।
2. डिपो रविवार और holidays.csv में दी गई अपनी छुट्टियों को छोड़कर हर दिन काम करता है ("सभी" का मतलब दोनों डिपो)।
3. उसी दिन भेजने की अंतिम समय-सीमा (उस समय सहित): D1 सामान्य (REG) 14:30, D1 एक्सप्रेस (EXP) 16:00, D2 सामान्य 15:00, D2 एक्सप्रेस 17:30। कामकाजी दिन पर समय-सीमा तक या उससे पहले बुक हुआ पार्सल उसी दिन भेजा जाता है। वरना वह अपने डिपो के अगले कामकाजी दिन भेजा जाता है।
4. शुल्क योग्य वज़न = किलो में असली वज़न (1000 ग्राम = 1 किलो) और आयतनी वज़न (सेमी में लंबाई × चौड़ाई × ऊँचाई / 5000) में से जो बड़ा हो, उसे 0.5 किलो के अगले गुणज तक ऊपर राउंड करें (जो पहले से गुणज हो वह वैसा ही रहेगा)।
5. शुल्क: सामान्य के लिए पहले 0.5 किलो के 40 रुपये और हर अगले 0.5 किलो के 30 रुपये; एक्सप्रेस के लिए पहले 0.5 किलो के 70 रुपये और हर अगले 0.5 किलो के 45 रुपये। कैश ऑन डिलीवरी पार्सल पर 30 रुपये और घोषित मूल्य के 2% (पूरे रुपये में राउंड हाफ़ अप) में से जो बड़ा हो, वह जुड़ता है।
6. हर बचे हुए पार्सल की रिपोर्ट दें: dispatch_date (YYYY-MM-DD), chargeable_kg एक दशमलव स्थान के साथ, और charge पूरे रुपये में।""",
    }
    return task(
        id=tid, title='Parcel dispatch and charges', domain='logistics',
        goals={'en': 'Work out the dispatch date and charge for every parcel booking.',
               'hi': 'हर पार्सल बुकिंग की भेजने की तारीख और शुल्क निकालें।',
               'hinglish': 'Har parcel booking ki dispatch date aur charge nikalo.'},
        notice=notice, tables=tables, output=['parcel', 'dispatch_date', 'chargeable_kg', 'charge'],
        numeric=['chargeable_kg', 'charge'], answer=solve(), solve=solve,
        ablations=['amend', 'cutoff_exclusive', 'holidays', 'sunday', 'depot_cutoff', 'volumetric', 'round_nearest',
                   'cod_off', 'cod_flat'])


AUDIT_DATE = date(2026, 11, 16)


def delivery_audit():
    tid = '12-delivery-audit'
    rng = random.Random(tid)
    items = [('Rice 5 kg bag', 'चावल 5 किलो थैला'), ('Cooking oil 1 L', 'खाने का तेल 1 लीटर'),
             ('Soap bar', 'साबुन की टिकिया'), ('Tea 250 g', 'चाय 250 ग्राम'), ('Biscuit pack', 'बिस्कुट पैकेट'),
             ('Toothpaste', 'टूथपेस्ट'), ('Notebook', 'कॉपी'), ('Detergent 1 kg', 'डिटर्जेंट 1 किलो'),
             ('Salt 1 kg', 'नमक 1 किलो'), ('Matchbox', 'माचिस'), ('Candles', 'मोमबत्ती'), ('Sugar 1 kg', 'चीनी 1 किलो')]
    skus = [[f'K{i + 1:02d}', {'en': en, 'hi': hi}, rng.choice([6, 10, 12, 24])] for i, (en, hi) in enumerate(items)]
    per_box = {s[0]: s[2] for s in skus}
    lines = []
    receipts = []
    counter = 0

    def receipt(shipment, sku, kind, units, signed=True, when=None, boxed=None):
        nonlocal counter
        counter += 1
        when = when or date(2026, 11, 9) + timedelta(days=rng.randint(0, 7))
        size = per_box[sku]
        use_box = boxed if boxed is not None else (units % size == 0 and units > 0 and rng.random() < 0.5)
        qty, unit = (units // size, 'BOX') if use_box else (units, 'UNIT')
        receipts.append([f'R{counter:04d}', shipment, sku, kind, qty, unit, signed, when])

    scenarios = (['match'] * 18 + ['short'] * 10 + ['excess'] * 6 + ['none'] * 4 + ['unsigned'] * 4 + ['late'] * 4
                 + ['zero'] * 3 + ['returns'] * 6 + ['return_only'] * 2)
    rng.shuffle(scenarios)
    for index, scenario in enumerate(scenarios):
        shipment = f'SH{index // 4 + 1:02d}'
        used = {line[2] for line in lines if line[1] == shipment}
        sku = rng.choice([s[0] for s in skus if s[0] not in used])
        size = per_box[sku]
        qty = size * rng.randint(2, 15)
        lines.append([f'M{index + 1:03d}', shipment, sku, qty])
        if scenario == 'match':
            first = size * rng.randint(1, qty // size)
            receipt(shipment, sku, 'RECEIPT', first)
            if first < qty:
                receipt(shipment, sku, 'RECEIPT', qty - first)
        elif scenario == 'short':
            receipt(shipment, sku, 'RECEIPT', qty - rng.randint(1, size))
        elif scenario == 'excess':
            receipt(shipment, sku, 'RECEIPT', qty + size)
        elif scenario == 'unsigned':
            receipt(shipment, sku, 'RECEIPT', qty, signed=False)
        elif scenario == 'late':
            receipt(shipment, sku, 'RECEIPT', qty, when=AUDIT_DATE + timedelta(days=rng.randint(1, 3)))
            receipt(shipment, sku, 'RECEIPT', size, when=AUDIT_DATE)
        elif scenario == 'zero':
            receipt(shipment, sku, 'RECEIPT', 0, boxed=False)
        elif scenario == 'returns':
            receipt(shipment, sku, 'RECEIPT', qty)
            receipt(shipment, sku, 'RETURN', size * rng.randint(1, 2))
        elif scenario == 'return_only':
            receipt(shipment, sku, 'RETURN', size)
    rng.shuffle(receipts)
    for index, row in enumerate(receipts):
        row[0] = f'R{index + 1:04d}'
    amendments = []
    signed_rows = [r for r in receipts if r[6] and r[3] == 'RECEIPT' and r[7] <= AUDIT_DATE and r[4] > 0]
    for r in rng.sample(signed_rows, 4):
        amendments.append([r[0], 'SET_QTY', r[4] + rng.choice([-1, 1, 2])])
    unsigned = [r for r in receipts if not r[6]]
    amendments.append([unsigned[0][0], 'SIGNED', None])
    for r in rng.sample(signed_rows, 2):
        amendments.append([r[0], 'VOID', None])
    amendments = [[seq, *row] for seq, row in enumerate(amendments, 1)]
    file_amends = amendments[:]
    rng.shuffle(file_amends)

    def solve(off=frozenset()):
        data = {r[0]: {'shipment': r[1], 'sku': r[2], 'kind': r[3], 'qty': r[4], 'unit': r[5], 'signed': r[6],
                       'date': r[7], 'void': False} for r in receipts}
        if 'amend' not in off:
            for _, key, act, qty in sorted(file_amends):
                if act == 'SET_QTY':
                    data[key]['qty'] = qty
                elif act == 'SIGNED':
                    data[key]['signed'] = True
                else:
                    data[key]['void'] = True
        answer = []
        for line, shipment, sku, ordered in lines:
            total = 0
            proof = False
            for item in data.values():
                if (item['shipment'], item['sku']) != (shipment, sku) or item['void']:
                    continue
                if not item['signed'] and 'unsigned' not in off:
                    continue
                if item['date'] > AUDIT_DATE and 'cutoff' not in off:
                    continue
                units = item['qty'] * (per_box[sku] if item['unit'] == 'BOX' and 'boxes' not in off else 1)
                if item['kind'] == 'RECEIPT':
                    total += units
                    if units > 0 or 'zero_proof' not in off:
                        proof = True
                else:
                    if 'returns' not in off:
                        total -= units
                    if 'return_proof' in off:
                        proof = True
            if not proof:
                answer.append([line, '', '', 'NO_PROOF'])
                continue
            diff = total - ordered
            answer.append([line, str(total), str(diff), 'SHORT' if diff < 0 else 'EXCESS' if diff > 0 else 'MATCH'])
        return answer

    kind = Code({'RECEIPT': (['RECEIPT', 'Receipt'], ['प्राप्ति']), 'RETURN': (['RETURN', 'Return'], ['वापसी'])})
    unit = Code({'UNIT': (['units', 'pcs'], ['नग', 'पीस']), 'BOX': (['boxes', 'box'], ['डिब्बे', 'डिब्बा'])})
    action = Code({'SET_QTY': (['SET_QTY'], ['मात्रा बदलें']), 'SIGNED': (['SIGNED'], ['हस्ताक्षर दर्ज']),
                   'VOID': (['VOID'], ['रद्द'])})
    tables = [
        Table('skus', [('sku', 'एसकेयू', Id()), ('item', 'सामान', Text()), ('units_per_box', 'प्रति डिब्बा नग', Int())],
              skus, tid),
        Table('manifest', [('line', 'पंक्ति', Id()), ('shipment', 'खेप', Id()), ('sku', 'एसकेयू', Id()),
                           ('units', 'नग', Int())], lines, tid),
        Table('receipts', [('receipt', 'रसीद', Id()), ('shipment', 'खेप', Id()), ('sku', 'एसकेयू', Id()),
                           ('kind', 'प्रकार', kind), ('quantity', 'मात्रा', Int()), ('unit', 'इकाई', unit),
                           ('signed', 'हस्ताक्षरित', YES_NO), ('date', 'तारीख', Date())], receipts, tid),
        Table('amendments', [('seq', 'क्रम', Int()), ('receipt', 'रसीद', Id()), ('action', 'कार्रवाई', action),
                             ('quantity', 'मात्रा', Int())], file_amends, tid),
    ]
    notice = {
        'en': """Audit proof of delivery for the ration-shop dispatches. The audit covers receipts dated up to and including 16 November 2026.
1. Apply amendments.csv in ascending seq order (the file is not sorted): SET_QTY replaces the quantity, SIGNED marks the receipt as signed, and VOID cancels it.
2. A receipt row counts only if it is signed, not voided, and dated on or before 16 November 2026. Match receipts to manifest lines by shipment and SKU.
3. Convert boxes to units with units_per_box from skus.csv.
4. received_units = units on counted RECEIPT rows minus units on counted RETURN rows.
5. A line has proof only if it has at least one counted RECEIPT row. A signed receipt for 0 units is still proof. RETURN rows alone are not proof.
6. Report every manifest line. Without proof: status NO_PROOF with received_units and difference blank. With proof: difference = received_units - manifest units, and status SHORT if negative, EXCESS if positive, MATCH if zero.""",
        'hi': """राशन दुकानों को भेजे गए माल की डिलीवरी के प्रमाण की जाँच करें। जाँच में 16 नवंबर 2026 तक (उस दिन सहित) की रसीदें शामिल हैं।
1. amendments.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है): "मात्रा बदलें" मात्रा बदलता है, "हस्ताक्षर दर्ज" रसीद को हस्ताक्षरित मानता है, और "रद्द" उसे रद्द करता है।
2. रसीद की पंक्ति तभी गिनी जाएगी जब वह हस्ताक्षरित हो, रद्द न हो, और उसकी तारीख 16 नवंबर 2026 या उससे पहले की हो। रसीदों को खेप और एसकेयू से मैनिफ़ेस्ट की पंक्तियों से मिलाएँ।
3. skus.csv में दिए "प्रति डिब्बा नग" से डिब्बों को नग में बदलें।
4. received_units = गिनी गई प्राप्ति पंक्तियों के नग घटा गिनी गई वापसी पंक्तियों के नग।
5. किसी पंक्ति का प्रमाण तभी है जब उसकी कम से कम एक प्राप्ति पंक्ति गिनी जाए। 0 नग की हस्ताक्षरित प्राप्ति भी प्रमाण है। सिर्फ़ वापसी पंक्तियाँ प्रमाण नहीं हैं।
6. मैनिफ़ेस्ट की हर पंक्ति की रिपोर्ट दें। प्रमाण न हो तो status NO_PROOF लिखें और received_units और difference खाली छोड़ें। प्रमाण हो तो difference = received_units - मैनिफ़ेस्ट के नग, और status ऋणात्मक पर SHORT, धनात्मक पर EXCESS, और शून्य पर MATCH।""",
    }
    return task(
        id=tid, title='Proof-of-delivery audit', domain='logistics',
        goals={'en': 'Audit the proof of delivery for every manifest line in the ration-shop dispatches.',
               'hi': 'राशन दुकानों को भेजे गए माल की हर मैनिफ़ेस्ट पंक्ति के लिए डिलीवरी के प्रमाण की जाँच करें।',
               'hinglish': 'Ration-shop dispatches ki har manifest line ke liye proof of delivery audit karo.'},
        notice=notice, tables=tables, output=['line', 'received_units', 'difference', 'status'],
        numeric=['received_units', 'difference'], answer=solve(), solve=solve,
        ablations=['amend', 'unsigned', 'cutoff', 'boxes', 'returns', 'zero_proof', 'return_proof'])


TASKS = [parcel_dispatch, delivery_audit]
