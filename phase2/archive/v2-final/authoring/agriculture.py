"""Agriculture: procurement payout with moisture cuts, and seed-lot allocation."""

from datetime import date, timedelta
from decimal import Decimal
import math
import random

from .core import Code, Date, Id, Int, Money, Num, Qty, Table, Text, half_up, out_num, task

WEIGHT = Qty({'KG': (['kg', 'KG'], ['किलो', 'कि.ग्रा.']), 'QTL': (['qtl', 'quintal'], ['क्विंटल']),
              'T': (['t', 'tonne'], ['टन'])})
FACTOR = {'KG': Decimal(1), 'QTL': Decimal(100), 'T': Decimal(1000)}
NAMES = ['Ramesh', 'Suresh', 'Kamla', 'Harpal', 'Geeta', 'Mohan', 'Sunita', 'Baldev', 'Rajesh', 'Anita',
         'Jagdish', 'Savitri', 'Om Prakash', 'Pushpa', 'Mahendra', 'Usha', 'Kishan', 'Rekha', 'Satpal', 'Meena',
         'Dharam', 'Lalita', 'Vijay', 'Santosh', 'Ranjit', 'Kusum', 'Bhagwan', 'Shanti', 'Naresh', 'Phoolwati']
NAMES_HI = ['रमेश', 'सुरेश', 'कमला', 'हरपाल', 'गीता', 'मोहन', 'सुनीता', 'बलदेव', 'राजेश', 'अनीता', 'जगदीश', 'सावित्री',
            'ओम प्रकाश', 'पुष्पा', 'महेंद्र', 'उषा', 'किशन', 'रेखा', 'सतपाल', 'मीना', 'धरम', 'ललिता', 'विजय', 'संतोष',
            'रणजीत', 'कुसुम', 'भगवान', 'शांति', 'नरेश', 'फूलवती']
MERGES = [('F012', 'F007'), ('F007', 'F003'), ('F021', 'F004'), ('F025', 'F016'), ('F030', 'F002')]


def as_kg(weight):
    return weight[0] * FACTOR[weight[1]]


def grower_payout():
    tid = '05-grower-payout'
    rng = random.Random(tid)
    farmers = [[f'F{i + 1:03d}', {'en': NAMES[i], 'hi': NAMES_HI[i]}] for i in range(30)]
    deliveries = []
    special = [Decimal('14.0'), Decimal('14.4'), Decimal('14.5'), Decimal('20.0'), Decimal('20.1'),
               Decimal('19.9'), Decimal('16.7'), Decimal('22.4')]
    for index in range(120):
        kg = rng.randint(30, 250) * 10
        unit = rng.choice(['KG', 'KG', 'QTL', 'T'])
        moisture = special[index % 8] if index % 5 == 0 else Decimal(rng.randint(100, 215)) / 10
        when = date(2026, 11, 10) if index % 9 == 0 else date(2026, 11, 3) + timedelta(days=rng.randint(0, 14))
        farmer = rng.choice([f'F{rng.randint(1, 29):03d}', rng.choice(MERGES)[0]])
        deliveries.append([f'D{index + 1:04d}', farmer, when, rng.choice('AABBC'),
                           (Decimal(kg) / FACTOR[unit], unit), moisture])
    advances = []
    for index in range(26):
        farmer = rng.choice([f'F{rng.randint(1, 30):03d}', rng.choice(MERGES)[0]])
        advances.append([f'A{index + 1:03d}', farmer, date(2026, 10, 1) + timedelta(days=rng.randint(0, 40)),
                         rng.randint(10, 160) * 500])
    advances.append(['A027', 'F029', date(2026, 10, 12), 400000])
    amendments = []
    picks = rng.sample(deliveries, 9)
    for d in picks[:3]:
        kg = as_kg(d[4]) + rng.choice([-150, -60, 80, 230])
        amendments.append([d[0], 'SET_WEIGHT', (kg / 100, 'QTL'), None])
    for d in picks[3:6]:
        amendments.append([d[0], 'SET_MOISTURE', None, Decimal(rng.choice([135, 152, 205, 199])) / 10])
    for d in picks[6:8]:
        amendments.append([d[0], 'VOID', None, None])
    amendments.append([picks[3][0], 'SET_MOISTURE', None, Decimal('13.8')])
    amendments = [[seq, *row] for seq, row in enumerate(amendments, 1)]
    file_amends = amendments[:]
    rng.shuffle(file_amends)
    merge_rows = [[old, new] for old, new in MERGES]

    def solve(off=frozenset()):
        target = dict(MERGES) if 'merge' not in off else {}

        def final(farmer):
            if 'merge_once' in off:
                return target.get(farmer, farmer)
            while farmer in target:
                farmer = target[farmer]
            return farmer

        data = {d[0]: {'farmer': d[1], 'date': d[2], 'grade': d[3], 'weight': d[4], 'moisture': d[5], 'void': False}
                for d in deliveries}
        if 'amend' not in off:
            for _, key, act, weight, moisture in sorted(file_amends):
                if act == 'SET_WEIGHT':
                    data[key]['weight'] = weight
                elif act == 'SET_MOISTURE':
                    data[key]['moisture'] = moisture
                else:
                    data[key]['void'] = True
        totals = {}
        for key, item in data.items():
            farmer = final(item['farmer'])
            entry = totals.setdefault(farmer, {'kg': Decimal(0), 'gross': Decimal(0), 'advance': 0})
            if item['void']:
                continue
            m = item['moisture']
            if m > 20 or ('reject_inclusive' in off and m >= 20):
                continue
            steps = 0
            if m > 14:
                ratio = (m - 14) / Decimal('0.5')
                steps = int(half_up(ratio)) if 'moisture_round' in off else math.floor(ratio)
            kg = item['weight'][0] if 'units' in off else as_kg(item['weight'])
            accepted = kg * (100 - steps) / 100
            switch = item['date'] < date(2026, 11, 10) if 'rate_date' in off else item['date'] <= date(2026, 11, 10)
            rate = (2400 if switch else 2550) - {'A': 0, 'B': 120, 'C': 300}[item['grade']]
            value = accepted / 100 * rate
            entry['kg'] += accepted
            entry['gross'] += value if 'round_total' in off else half_up(value)
        for _, farmer, _, amount in advances:
            totals.setdefault(final(farmer), {'kg': Decimal(0), 'gross': Decimal(0), 'advance': 0})['advance'] += amount
        answer = []
        for farmer in sorted(totals):
            item = totals[farmer]
            gross = int(half_up(item['gross']))
            recovered = item['advance'] if 'advance_cap' in off else min(item['advance'], gross)
            answer.append([farmer, out_num(item['kg'], 1), str(gross), str(recovered), str(gross - recovered),
                           str(item['advance'] - recovered)])
        return answer

    grade = Code({'A': (['A', 'Grade A'], ['A', 'ग्रेड A']), 'B': (['B', 'Grade B'], ['B', 'ग्रेड B']),
                  'C': (['C', 'Grade C'], ['C', 'ग्रेड C'])})
    action = Code({'SET_WEIGHT': (['SET_WEIGHT'], ['वज़न बदलें']), 'SET_MOISTURE': (['SET_MOISTURE'], ['नमी बदलें']),
                   'VOID': (['VOID'], ['रद्द'])})
    tables = [
        Table('farmers', [('farmer', 'किसान', Id()), ('name', 'नाम', Text())], farmers, tid),
        Table('registry_merges', [('old_farmer', 'पुराना किसान', Id()), ('merged_into', 'नया किसान', Id())],
              merge_rows, tid),
        Table('deliveries', [('receipt', 'रसीद', Id()), ('farmer', 'किसान', Id()), ('date', 'तारीख', Date()),
                             ('grade', 'ग्रेड', grade), ('weight', 'वज़न', WEIGHT), ('moisture_pct', 'नमी प्रतिशत', Num(1))],
              deliveries, tid),
        Table('advances', [('advance', 'अग्रिम', Id()), ('farmer', 'किसान', Id()), ('date', 'तारीख', Date()),
                           ('amount', 'राशि', Money())], advances, tid),
        Table('amendments', [('seq', 'क्रम', Int()), ('receipt', 'रसीद', Id()), ('action', 'कार्रवाई', action),
                             ('weight', 'वज़न', WEIGHT), ('moisture_pct', 'नमी प्रतिशत', Num(1))], file_amends, tid),
    ]
    notice = {
        'en': """Compute the paddy procurement payout for November 2026.
1. Apply amendments.csv in ascending seq order (the file is not sorted): SET_WEIGHT replaces the weight, SET_MOISTURE replaces the moisture, and VOID cancels the receipt. A later change to the same field overrides an earlier one.
2. Registry merges: an old farmer ID is replaced by merged_into. Follow merges until you reach an ID that is not merged (a merge can point to an ID that was itself merged). Report only final IDs.
3. Convert weights to kg: 1 qtl (quintal) = 100 kg and 1 t (tonne) = 1000 kg.
4. Moisture: at 14.0% or below there is no cut. Above 14.0% and up to 20.0%, the weight cut is 1% for every full 0.5 percentage point above 14.0 (14.4% gives 0%, 14.5% gives 1%, 16.7% gives 5%). Above 20.0% the receipt is rejected and contributes nothing. accepted kg = weight in kg × (100 - cut) / 100.
5. Rate per quintal of accepted weight: grade A is Rs 2,400 for deliveries up to and including 10 November 2026 and Rs 2,550 from 11 November. Grade B is Rs 120 less and grade C Rs 300 less than grade A on the same date.
6. Value each receipt as accepted kg / 100 × rate and round it half up to whole rupees. gross is the sum of a farmer's rounded receipt values.
7. Advances are recovered from gross: recovered = the smaller of total advances and gross. net_payable = gross - recovered. outstanding = total advances - recovered.
8. Report every final farmer ID that has a delivery (even a voided or rejected one) or an advance: accepted_kg is the total accepted kg with one decimal place (round half up).""",
        'hi': """नवंबर 2026 की धान खरीद का भुगतान निकालें।
1. amendments.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है): "वज़न बदलें" वज़न बदलता है, "नमी बदलें" नमी बदलता है, और "रद्द" रसीद को रद्द करता है। एक ही फ़ील्ड का बाद वाला बदलाव पहले वाले की जगह लेता है।
2. रजिस्टर विलय: पुरानी किसान आईडी की जगह "नया किसान" वाली आईडी लें। विलय की कड़ी तब तक आगे बढ़ाएँ जब तक ऐसी आईडी न मिले जिसका विलय नहीं हुआ है (एक विलय ऐसी आईडी की ओर इशारा कर सकता है जिसका खुद विलय हुआ है)। सिर्फ़ अंतिम आईडी की रिपोर्ट दें।
3. वज़न को किलो में बदलें: 1 क्विंटल = 100 किलो और 1 टन = 1000 किलो।
4. नमी: 14.0% या उससे कम पर कोई कटौती नहीं। 14.0% से ज़्यादा और 20.0% तक, 14.0 से ऊपर हर पूरे 0.5 प्रतिशत अंक के लिए वज़न में 1% कटौती (14.4% पर 0%, 14.5% पर 1%, 16.7% पर 5%)। 20.0% से ज़्यादा नमी पर रसीद अस्वीकार है और उसका कोई योगदान नहीं। स्वीकृत किलो = किलो में वज़न × (100 - कटौती) / 100।
5. स्वीकृत वज़न की प्रति क्विंटल दर: ग्रेड A के लिए 10 नवंबर 2026 तक (उस दिन सहित) की आवक पर 2,400 रुपये और 11 नवंबर से 2,550 रुपये। उसी तारीख पर ग्रेड B, ग्रेड A से 120 रुपये कम और ग्रेड C 300 रुपये कम है।
6. हर रसीद का मूल्य = स्वीकृत किलो / 100 × दर, पूरे रुपये में राउंड हाफ़ अप। gross किसान की राउंड की गई रसीद राशियों का योग है।
7. अग्रिम gross से वसूला जाता है: recovered = कुल अग्रिम और gross में से जो छोटा हो। net_payable = gross - recovered। outstanding = कुल अग्रिम - recovered।
8. हर उस अंतिम किसान आईडी की रिपोर्ट दें जिसकी कोई आवक (रद्द या अस्वीकार भी) या अग्रिम हो: accepted_kg कुल स्वीकृत किलो है, एक दशमलव स्थान तक (राउंड हाफ़ अप)।""",
    }
    return task(
        id=tid, title='Paddy procurement payout', domain='agriculture',
        goals={'en': 'Compute the November procurement payout and advance recovery for every grower.',
               'hi': 'हर किसान के लिए नवंबर की खरीद का भुगतान और अग्रिम वसूली निकालें।',
               'hinglish': 'Har grower ke liye November procurement payout aur advance recovery nikalo.'},
        notice=notice, tables=tables,
        output=['farmer', 'accepted_kg', 'gross', 'recovered', 'net_payable', 'outstanding'],
        numeric=['accepted_kg', 'gross', 'recovered', 'net_payable', 'outstanding'], answer=solve(), solve=solve,
        ablations=['merge', 'merge_once', 'amend', 'moisture_round', 'reject_inclusive', 'units', 'rate_date',
                   'round_total', 'advance_cap'])


VARIETIES = {'WHEAT': ('Wheat HD-2967', 'गेहूँ HD-2967'), 'MUSTARD': ('Mustard RH-725', 'सरसों RH-725'),
             'GRAM': ('Gram GNG-2144', 'चना GNG-2144'), 'LENTIL': ('Lentil L-4727', 'मसूर L-4727')}
DISTRIBUTION = date(2026, 11, 20)


def seed_allocation():
    tid = '06-seed-allocation'
    rng = random.Random(tid)
    pack_sizes = {'WHEAT': [20, 25, 40], 'MUSTARD': [2, 5], 'GRAM': [10, 20, 30], 'LENTIL': [5, 10, 15]}
    lots = []
    expiries = [date(2026, 11, 19), date(2026, 11, 20), date(2026, 11, 21), date(2026, 12, 15),
                date(2027, 1, 31), date(2027, 3, 31), date(2026, 11, 30), date(2027, 2, 28)]
    number = 0
    for variety in VARIETIES:
        for _ in range(6):
            number += 1
            lots.append([f'L{number:02d}', variety, rng.randint(10, 48), rng.choice(pack_sizes[variety]),
                         rng.choice(expiries), 'QUARANTINE' if rng.random() < 0.2 else 'OK'])
    lots.sort(key=lambda lot: lot[0])
    requests = []
    for index in range(72):
        variety = rng.choice(list(VARIETIES))
        step = 5 if variety != 'MUSTARD' else 1
        requests.append([f'R{index + 1:03d}', rng.choice(['SMALL', 'SMALL', 'OTHER']), variety,
                         rng.randint(2, 40) * step * (5 if variety == 'WHEAT' else 1),
                         date(2026, 11, 1) + timedelta(days=rng.randint(0, 15))])
    amendments = []
    held = [lot for lot in lots if lot[5] == 'QUARANTINE']
    for lot in held[:2]:
        amendments.append([lot[0], 'RELEASE', None])
    for lot in rng.sample([lot for lot in lots if lot[5] == 'OK'], 2):
        amendments.append([lot[0], 'HOLD', None])
    for lot in rng.sample(lots, 3):
        amendments.append([lot[0], 'SET_PACKS', lot[2] + rng.choice([-3, 4, 7])])
    amendments.append([amendments[0][0], 'HOLD', None])
    amendments = [[seq, *row] for seq, row in enumerate(amendments, 1)]
    file_amends = amendments[:]
    rng.shuffle(file_amends)

    def solve(off=frozenset()):
        state = {lot[0]: {'variety': lot[1], 'packs': lot[2], 'size': lot[3], 'expiry': lot[4], 'status': lot[5]}
                 for lot in lots}
        if 'amend' not in off:
            for _, key, act, packs in sorted(file_amends):
                if act == 'RELEASE':
                    state[key]['status'] = 'OK'
                elif act == 'HOLD':
                    state[key]['status'] = 'QUARANTINE'
                else:
                    state[key]['packs'] = packs

        def usable(item):
            if item['status'] != 'OK' and 'quarantine' not in off:
                return False
            if 'expiry' in off:
                return True
            return item['expiry'] > DISTRIBUTION if 'expiry_exclusive' in off else item['expiry'] >= DISTRIBUTION

        if 'priority' in off:
            order = sorted(requests, key=lambda r: (r[4], r[0]))
        else:
            order = sorted(requests, key=lambda r: (r[1] != 'SMALL', r[4], r[0]))
        result = {}
        for key, _, variety, kg, _ in order:
            need = kg
            given = 0
            used = []
            pool = [k for k in state if state[k]['variety'] == variety and usable(state[k])]
            pool.sort(key=(lambda k: k) if 'fefo' in off else (lambda k: (state[k]['expiry'], k)))
            for lot in pool:
                if need <= 0:
                    break
                item = state[lot]
                if item['packs'] <= 0:
                    continue
                wanted = need // item['size'] if 'floor_packs' in off else math.ceil(need / item['size'])
                packs = min(wanted, item['packs'])
                if packs <= 0:
                    continue
                item['packs'] -= packs
                given += packs * item['size']
                need -= packs * item['size']
                used.append(lot)
            result[key] = [key, str(given), '+'.join(used), str(max(kg - given, 0))]
        return [result[r[0]] for r in requests]

    variety = Code({code: ([code, en], [hi]) for code, (en, hi) in VARIETIES.items()})
    status = Code({'OK': (['OK', 'ok'], ['उपयोग योग्य']), 'QUARANTINE': (['QUARANTINE', 'Quarantine'], ['क्वारंटीन', 'रोक'])})
    category = Code({'SMALL': (['SMALL', 'Smallholder'], ['लघु किसान', 'छोटा किसान']), 'OTHER': (['OTHER', 'Other'], ['अन्य'])})
    action = Code({'RELEASE': (['RELEASE'], ['रोक हटाएँ']), 'HOLD': (['HOLD'], ['रोक लगाएँ']),
                   'SET_PACKS': (['SET_PACKS'], ['पैकेट संख्या बदलें'])})
    tables = [
        Table('lots', [('lot', 'लॉट', Id()), ('variety', 'किस्म', variety), ('packs', 'पैकेट', Int()),
                       ('kg_per_pack', 'प्रति पैकेट किलो', Int()), ('expiry', 'समाप्ति तिथि', Date()),
                       ('status', 'स्थिति', status)], lots, tid),
        Table('requests', [('request', 'माँग', Id()), ('category', 'श्रेणी', category), ('variety', 'किस्म', variety),
                           ('kg', 'किलो', Int()), ('requested_on', 'माँग तिथि', Date())], requests, tid),
        Table('amendments', [('seq', 'क्रम', Int()), ('lot', 'लॉट', Id()), ('action', 'कार्रवाई', action),
                             ('packs', 'पैकेट', Int())], file_amends, tid),
    ]
    notice = {
        'en': """Allocate certified seed for the distribution on 20 November 2026.
1. Apply amendments.csv in ascending seq order (the file is not sorted): RELEASE sets a lot's status to OK, HOLD sets it to QUARANTINE, and SET_PACKS replaces the number of packs.
2. A lot is usable only if its final status is OK and its expiry date is on or after 20 November 2026.
3. Serve requests in this order across all varieties: SMALL (smallholder) requests before OTHER, then by requested_on date, then by request ID. Each request takes the remaining stock of its own variety only.
4. Take lots in order of earliest expiry date (ties by lot ID). Packs cannot be split. From each lot take the smallest number of whole packs that covers the remaining need, or all of the lot's remaining packs if that is not enough, then move to the next lot. Stop when the need is covered.
5. Report every request: allocated_kg (packs taken × kg per pack, which can exceed the request), lots (the lots used, in the order used, joined with +, blank if none) and pending_kg (requested kg - allocated kg, or 0 if that would be negative).""",
        'hi': """20 नवंबर 2026 के वितरण के लिए प्रमाणित बीज आवंटित करें।
1. amendments.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है): "रोक हटाएँ" लॉट की स्थिति को उपयोग योग्य करता है, "रोक लगाएँ" उसे क्वारंटीन करता है, और "पैकेट संख्या बदलें" पैकेटों की संख्या बदलता है।
2. लॉट तभी इस्तेमाल हो सकता है जब उसकी अंतिम स्थिति उपयोग योग्य हो और उसकी समाप्ति तिथि 20 नवंबर 2026 या उसके बाद की हो।
3. सभी किस्मों की माँगें इस क्रम में पूरी करें: लघु किसान की माँगें "अन्य" से पहले, फिर माँग तिथि के क्रम में, फिर माँग आईडी के क्रम में। हर माँग सिर्फ़ अपनी किस्म के बचे हुए स्टॉक से ली जाएगी।
4. लॉट सबसे जल्दी समाप्ति तिथि के क्रम में लें (बराबरी पर लॉट आईडी के क्रम में)। पैकेट तोड़े नहीं जा सकते। हर लॉट से पूरे पैकेटों की वह सबसे छोटी संख्या लें जिससे बची हुई ज़रूरत पूरी हो जाए; अगर वह काफ़ी न हो, तो लॉट के सभी बचे पैकेट लें और अगले लॉट पर जाएँ। ज़रूरत पूरी होते ही रुक जाएँ।
5. हर माँग की रिपोर्ट दें: allocated_kg (लिए गए पैकेट × प्रति पैकेट किलो; यह माँग से ज़्यादा हो सकता है), lots (इस्तेमाल हुए लॉट, इस्तेमाल के क्रम में, + से जुड़े; कोई न हो तो खाली) और pending_kg (माँगा गया किलो - आवंटित किलो, और अगर यह ऋणात्मक हो तो 0)।""",
    }
    return task(
        id=tid, title='Seed lot allocation', domain='agriculture',
        goals={'en': 'Allocate certified seed lots to every farmer request for the 20 November distribution.',
               'hi': '20 नवंबर के वितरण के लिए किसानों की हर माँग को प्रमाणित बीज लॉट आवंटित करें।',
               'hinglish': '20 November distribution ke liye har farmer request ko certified seed lots allot karo.'},
        notice=notice, tables=tables, output=['request', 'allocated_kg', 'lots', 'pending_kg'],
        numeric=['allocated_kg', 'pending_kg'], answer=solve(), solve=solve,
        ablations=['amend', 'quarantine', 'expiry', 'expiry_exclusive', 'priority', 'fefo', 'floor_packs'])


TASKS = [grower_payout, seed_allocation]
