"""Clinic: rebooking appointments during doctor leave, and lab result flagging."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import random

from .core import YES_NO, Code, Date, DateTime, Id, Int, Num, Table, Text, half_up, out_num, task

DOCTORS = [('DR1', 'GEN', 'Dr. Mehra', 'डॉ. मेहरा'), ('DR2', 'GEN', 'Dr. Iqbal', 'डॉ. इक़बाल'),
           ('DR3', 'PED', 'Dr. Rao', 'डॉ. राव'), ('DR4', 'PED', 'Dr. Sen', 'डॉ. सेन'),
           ('DR5', 'ORTHO', 'Dr. Gill', 'डॉ. गिल'), ('DR6', 'ORTHO', 'Dr. Nair', 'डॉ. नायर')]
LEAVE = [['DR1', date(2026, 11, 18)], ['DR1', date(2026, 11, 19)], ['DR3', date(2026, 11, 18)],
         ['DR5', date(2026, 11, 19)]]
REFERENCE = date(2026, 11, 18)


def age_on(dob, day):
    return day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))


def appointment_rebooking():
    tid = '13-appointment-rebooking'
    rng = random.Random(tid)
    specialty = {d[0]: d[1] for d in DOCTORS}
    patients = []
    special_dobs = [date(1966, 11, 18), date(1966, 11, 19), date(1966, 12, 2), date(1960, 5, 4), date(1950, 1, 9)]
    for index in range(56):
        if index < len(special_dobs):
            dob = special_dobs[index]
        else:
            dob = date(rng.randint(1940, 2022), rng.randint(1, 12), rng.randint(1, 28))
        pregnant = 18 <= age_on(dob, REFERENCE) <= 40 and rng.random() < 0.25
        patients.append([f'PT{index + 1:03d}', dob, pregnant])
    days = [date(2026, 11, 18) + timedelta(days=d) for d in range(4)]
    appointments = []
    taken = set()
    for index in range(96):
        doctor = rng.choice(DOCTORS)[0]
        if index < 30:
            doctor, day = rng.choice(LEAVE)
        else:
            day = rng.choice(days)
        while True:
            minutes = rng.randint(36, 69) * 15
            if (doctor, day, minutes) not in taken:
                taken.add((doctor, day, minutes))
                break
        start = datetime(day.year, day.month, day.day) + timedelta(minutes=minutes)
        patient = ['PT002', 'PT003', 'PT001', 'PT002'][index] if index < 4 else rng.choice(patients)[0]
        appointments.append([None, patient, doctor, start, 'ACCESS' if rng.random() < 0.2 else 'NONE'])
    appointments.sort(key=lambda a: (a[3], a[2]))
    rng.shuffle(appointments)
    for index, row in enumerate(appointments):
        row[0] = f'AP{index + 1:03d}'
    slots = []
    for index in range(58):
        doctor = rng.choice(DOCTORS)[0]
        day = rng.choice(days)
        while True:
            minutes = rng.randint(36, 69) * 15
            if (doctor, day, minutes) not in taken:
                taken.add((doctor, day, minutes))
                break
        slots.append([doctor, datetime(day.year, day.month, day.day) + timedelta(minutes=minutes),
                      'ACCESS' if rng.random() < 0.3 else 'STD'])
    slots.sort(key=lambda s: (s[1], s[0]))
    rng.shuffle(slots)
    slots = [[f'SL{i + 1:03d}', *s] for i, s in enumerate(slots)]
    on_leave = {(d, day) for d, day in LEAVE}
    info = {p[0]: p for p in patients}

    def solve(off=frozenset()):
        affected = [a for a in appointments if (a[2], a[3].date()) in on_leave]
        kept_days = {}
        for a in appointments:
            if a not in affected:
                kept_days.setdefault(a[1], set()).add(a[3].date())

        def elderly(patient):
            dob = info[patient][1]
            age = REFERENCE.year - dob.year if 'age_year' in off else age_on(dob, REFERENCE)
            return age >= 60

        if 'priority' in off:
            order = sorted(affected, key=lambda a: (a[3], a[0]))
        else:
            order = sorted(affected, key=lambda a: (not info[a[1]][2], not elderly(a[1]), a[3], a[0]))
        used = set()
        result = {}
        for appt, patient, doctor, start, needs in order:
            options = []
            for slot, sdoctor, sstart, kind in slots:
                if slot in used:
                    continue
                if specialty[sdoctor] != specialty[doctor] and 'specialty' not in off:
                    continue
                if (sdoctor, sstart.date()) in on_leave and 'leave_slots' not in off:
                    continue
                if sstart < start and 'before_original' not in off:
                    continue
                if needs == 'ACCESS' and kind != 'ACCESS':
                    continue
                if needs == 'NONE' and kind != 'STD' and 'access_any' not in off:
                    continue
                if sstart.date() in kept_days.get(patient, set()) and 'same_day' not in off:
                    continue
                options.append((sstart, slot, sdoctor))
            if options:
                sstart, slot, sdoctor = min(options)
                used.add(slot)
                kept_days.setdefault(patient, set()).add(sstart.date())
                result[appt] = [appt, slot, sdoctor, 'REBOOKED']
            else:
                result[appt] = [appt, '', '', 'WAITLIST']
        return [result[a[0]] for a in sorted(affected, key=lambda a: a[0])]

    needs = Code({'ACCESS': (['ACCESS', 'wheelchair'], ['व्हीलचेयर', 'सुगम्य']), 'NONE': (['NONE', 'none'], ['कोई नहीं'])})
    kind = Code({'ACCESS': (['ACCESS'], ['सुगम्य']), 'STD': (['STD', 'standard'], ['सामान्य'])})
    spec = Code({'GEN': (['GEN', 'General medicine'], ['सामान्य चिकित्सा']), 'PED': (['PED', 'Paediatrics'], ['बाल रोग']),
                 'ORTHO': (['ORTHO', 'Orthopaedics'], ['हड्डी रोग'])})
    tables = [
        Table('doctors', [('doctor', 'डॉक्टर', Id()), ('specialty', 'विशेषज्ञता', spec), ('name', 'नाम', Text())],
              [[d[0], d[1], {'en': d[2], 'hi': d[3]}] for d in DOCTORS], tid),
        Table('leave', [('doctor', 'डॉक्टर', Id()), ('date', 'तारीख', Date())], LEAVE, tid),
        Table('patients', [('patient', 'मरीज़', Id()), ('date_of_birth', 'जन्म तिथि', Date()),
                           ('pregnant', 'गर्भवती', YES_NO)], patients, tid),
        Table('appointments', [('appointment', 'अपॉइंटमेंट', Id()), ('patient', 'मरीज़', Id()), ('doctor', 'डॉक्टर', Id()),
                               ('start', 'समय', DateTime()), ('access_need', 'पहुँच ज़रूरत', needs)], appointments, tid),
        Table('free_slots', [('slot', 'स्लॉट', Id()), ('doctor', 'डॉक्टर', Id()), ('start', 'समय', DateTime()),
                             ('kind', 'प्रकार', kind)], slots, tid),
    ]
    notice = {
        'en': """Rebook the appointments cancelled by doctor leave.
1. An appointment is cancelled if its doctor is on leave (leave.csv) on the appointment date. All other appointments are kept.
2. Rebook cancelled appointments one at a time in this priority order: pregnant patients first, then patients aged 60 or over on 18 November 2026 (age in completed years from date_of_birth), then the earlier original start time, then the lower appointment ID.
3. Each takes the earliest eligible free slot (ties by slot ID). A slot is eligible only if: its doctor has the same specialty as the original doctor; its doctor is not on leave that date; it starts at or after the original start time; it is an ACCESS slot when the patient needs access (wheelchair) and a STD slot otherwise (ACCESS slots are reserved); it has not been given to an earlier rebooking; and the patient has no kept appointment and no earlier rebooking on the same calendar day.
4. If no slot is eligible the appointment gets WAITLIST.
5. Report only the cancelled appointments: slot and doctor of the new booking and status REBOOKED, or blank slot and doctor with status WAITLIST.""",
        'hi': """डॉक्टर की छुट्टी से रद्द हुए अपॉइंटमेंट दोबारा बुक करें।
1. कोई अपॉइंटमेंट रद्द है अगर उसकी तारीख को उसका डॉक्टर छुट्टी पर (leave.csv) है। बाकी सभी अपॉइंटमेंट बने रहते हैं।
2. रद्द अपॉइंटमेंट एक-एक करके इस प्राथमिकता से दोबारा बुक करें: पहले गर्भवती मरीज़, फिर वे मरीज़ जिनकी उम्र 18 नवंबर 2026 को 60 साल या उससे ज़्यादा है (जन्म तिथि से पूरे किए गए साल), फिर पहले वाला मूल समय, फिर छोटी अपॉइंटमेंट आईडी।
3. हर अपॉइंटमेंट सबसे पहला योग्य खाली स्लॉट लेता है (बराबरी पर स्लॉट आईडी के क्रम में)। स्लॉट तभी योग्य है जब: उसके डॉक्टर की विशेषज्ञता मूल डॉक्टर जैसी हो; उसका डॉक्टर उस तारीख को छुट्टी पर न हो; वह मूल समय पर या उसके बाद शुरू हो; मरीज़ को पहुँच (व्हीलचेयर) की ज़रूरत हो तो वह सुगम्य (ACCESS) स्लॉट हो, वरना सामान्य (STD) स्लॉट हो (सुगम्य स्लॉट आरक्षित हैं); वह किसी पहले की दोबारा बुकिंग को न दिया गया हो; और उसी कैलेंडर दिन मरीज़ का कोई बना हुआ अपॉइंटमेंट या पहले की दोबारा बुकिंग न हो।
4. कोई स्लॉट योग्य न हो तो अपॉइंटमेंट को WAITLIST मिलेगा।
5. सिर्फ़ रद्द अपॉइंटमेंट की रिपोर्ट दें: नई बुकिंग का slot और doctor और status REBOOKED, या खाली slot और doctor के साथ status WAITLIST।""",
    }
    return task(
        id=tid, title='Appointment rebooking', domain='clinic',
        goals={'en': 'Rebook every appointment cancelled by doctor leave, or waitlist it.',
               'hi': 'डॉक्टर की छुट्टी से रद्द हर अपॉइंटमेंट को दोबारा बुक करें, या उसे प्रतीक्षा सूची में डालें।',
               'hinglish': 'Doctor leave se cancel hue har appointment ko rebook karo, ya waitlist mein daalo.'},
        notice=notice, tables=tables, output=['appointment', 'slot', 'doctor', 'status'], answer=solve(), solve=solve,
        ablations=['priority', 'age_year', 'specialty', 'leave_slots', 'before_original', 'access_any', 'same_day'])


TESTS = {'GLU': ('Glucose (fasting)', 'ग्लूकोज़ (खाली पेट)'), 'HB': ('Hemoglobin', 'हीमोग्लोबिन'),
         'K': ('Potassium', 'पोटैशियम'), 'CREAT': ('Creatinine', 'क्रिएटिनिन')}
UNITS = {'GLU': {'MGDL': Decimal(1), 'MMOLL': Decimal(18)}, 'HB': {'GDL': Decimal(1), 'GL': Decimal('0.1')},
         'K': {'MMOLL': Decimal(1), 'MEQL': Decimal(1)}, 'CREAT': {'MGDL': Decimal(1), 'UMOLL': 1 / Decimal('88.4')}}
PLACES = {'GLU': 0, 'HB': 1, 'K': 1, 'CREAT': 2}


def classify(test, value, sex, child, off):
    critical = 'critical' not in off
    if test == 'GLU':
        if critical and value < 54:
            return 'CRITICAL_LOW'
        if critical and value > 400:
            return 'CRITICAL_HIGH'
        low, high = Decimal(70), Decimal(99)
    elif test == 'K':
        if critical and value < Decimal('2.8'):
            return 'CRITICAL_LOW'
        if critical and value > Decimal('6.2'):
            return 'CRITICAL_HIGH'
        low, high = Decimal('3.5'), Decimal('5.0')
    elif test == 'HB':
        if critical and value < 7:
            return 'CRITICAL_LOW'
        if child and 'child' not in off:
            low, high = Decimal('11.5'), Decimal('15.5')
        elif sex == 'F' and 'sex' not in off:
            low, high = Decimal('12.0'), Decimal('15.5')
        else:
            low, high = Decimal('13.0'), Decimal('17.0')
    else:
        if child and 'child' not in off:
            low, high = Decimal('0.30'), Decimal('0.70')
        elif sex == 'F' and 'sex' not in off:
            low, high = Decimal('0.60'), Decimal('1.10')
        else:
            low, high = Decimal('0.70'), Decimal('1.30')
    return 'LOW' if value < low else 'HIGH' if value > high else 'NORMAL'


def lab_flags():
    tid = '14-lab-flags'
    rng = random.Random(tid)
    patients = []
    for index in range(26):
        dob = date(rng.choice([rng.randint(1945, 2000), rng.randint(2009, 2020)]), rng.randint(1, 12), rng.randint(1, 28))
        patients.append([f'LP{index + 1:03d}', rng.choice('MF'), dob])
    patients[0][2] = date(2008, 11, 16)
    patients[1][2] = date(2008, 11, 20)
    canonical = {
        'GLU': [Decimal(v) for v in ('48', '53.6', '54', '69.6', '70', '88', '99', '99.4', '99.5', '126', '180', '402')],
        'HB': [Decimal(v) for v in ('6.9', '9.8', '11.4', '11.6', '11.96', '12.04', '12.96', '13.4', '15.45', '15.6', '16.9', '17.04')],
        'K': [Decimal(v) for v in ('2.7', '2.84', '3.2', '3.46', '3.5', '4.1', '4.96', '5.04', '5.6', '6.24', '6.3')],
        'CREAT': [Decimal(v) for v in ('0.28', '0.45', '0.58', '0.62', '0.695', '0.705', '0.9', '1.06', '1.104', '1.304', '1.5', '2.4')],
    }
    results = []
    for patient, _, _ in patients:
        for test in rng.sample(list(TESTS), rng.randint(2, 3)):
            for _ in range(rng.randint(1, 3)):
                value = rng.choice(canonical[test])
                unit = rng.choice(list(UNITS[test]))
                factor = UNITS[test][unit]
                shown = value / factor
                if test == 'GLU' and unit == 'MMOLL':
                    shown = half_up(shown, 2)
                elif test == 'CREAT' and unit == 'UMOLL':
                    shown = half_up(value * Decimal('88.4'), 0)
                elif test == 'HB' and unit == 'GL':
                    shown = value * 10
                when = datetime(2026, 11, rng.randint(10, 16), rng.randint(7, 20), rng.choice([0, 15, 30, 45]))
                results.append([patient, test, when, shown.normalize() if shown == shown.to_integral_value() else shown, unit])
    rng.shuffle(results)
    results = [[f'LR{i + 1:04d}', *r] for i, r in enumerate(results)]
    corrections = []
    picks = rng.sample(results, 9)
    for r in picks[:5]:
        corrections.append([r[0], 'SET_VALUE', rng.choice(canonical[r[2]]), next(iter(UNITS[r[2]]))])
    for r in picks[5:]:
        corrections.append([r[0], 'VOID', None, None])
    corrections = [[seq, *row] for seq, row in enumerate(corrections, 1)]
    file_corrections = corrections[:]
    rng.shuffle(file_corrections)
    info = {p[0]: p for p in patients}

    def solve(off=frozenset()):
        data = {r[0]: {'patient': r[1], 'test': r[2], 'when': r[3], 'value': r[4], 'unit': r[5], 'void': False}
                for r in results}
        if 'corrections' not in off:
            for _, key, act, value, unit in sorted(file_corrections):
                if act == 'SET_VALUE':
                    data[key]['value'], data[key]['unit'] = value, unit
                else:
                    data[key]['void'] = True
        chosen = {}
        for key in sorted(data):
            item = data[key]
            if item['void']:
                continue
            group = (item['patient'], item['test'])
            rank = (item['when'], key)
            if group not in chosen or (rank < chosen[group][0] if 'earliest' in off else rank > chosen[group][0]):
                chosen[group] = (rank, item)
        answer = []
        for (patient, test), (_, item) in sorted(chosen.items()):
            factor = Decimal(1) if 'convert' in off else UNITS[test][item['unit']]
            value = Decimal(item['value']) * factor
            rounded = half_up(value, PLACES[test])
            _, sex, dob = info[patient]
            child = age_on(dob, item['when'].date()) < 18
            flag = classify(test, value if 'unrounded' in off else rounded, sex, child, off)
            answer.append([patient, test, out_num(rounded, PLACES[test]), flag])
        return answer

    test = Code({code: ([code, en], [hi]) for code, (en, hi) in TESTS.items()})
    unit = Code({'MGDL': (['mg/dL'], ['mg/dL', 'मि.ग्रा./डे.ली.']), 'MMOLL': (['mmol/L'], ['mmol/L', 'मि.मोल/ली.']),
                 'GDL': (['g/dL'], ['g/dL', 'ग्रा./डे.ली.']), 'GL': (['g/L'], ['g/L', 'ग्रा./ली.']),
                 'UMOLL': (['µmol/L', 'umol/L'], ['µmol/L', 'माइक्रोमोल/ली.']), 'MEQL': (['mEq/L'], ['mEq/L', 'मि.इक्वि./ली.'])})
    sex = Code({'M': (['M', 'Male'], ['पुरुष', 'पु.']), 'F': (['F', 'Female'], ['महिला', 'म.'])})
    action = Code({'SET_VALUE': (['SET_VALUE'], ['मान बदलें']), 'VOID': (['VOID'], ['रद्द'])})
    tables = [
        Table('patients', [('patient', 'मरीज़', Id()), ('sex', 'लिंग', sex), ('date_of_birth', 'जन्म तिथि', Date())],
              patients, tid),
        Table('results', [('result', 'परिणाम', Id()), ('patient', 'मरीज़', Id()), ('test', 'जाँच', test),
                          ('collected', 'नमूना समय', DateTime()), ('value', 'मान', Num(None)), ('unit', 'इकाई', unit)],
              results, tid),
        Table('corrections', [('seq', 'क्रम', Int()), ('result', 'परिणाम', Id()), ('action', 'कार्रवाई', action),
                              ('value', 'मान', Num(None)), ('unit', 'इकाई', unit)], file_corrections, tid),
    ]
    notice = {
        'en': """Prepare the latest lab result and flag for each patient and test.
1. Apply corrections.csv in ascending seq order (the file is not sorted): SET_VALUE replaces the value and unit, and VOID removes the result.
2. For each patient and test, use the remaining result with the latest collection time (ties by the higher result ID). Report nothing for a patient and test with no remaining result.
3. Convert to the reporting unit: glucose in mg/dL (mmol/L × 18); hemoglobin in g/dL (g/L ÷ 10); potassium in mmol/L (mEq/L is the same number); creatinine in mg/dL (µmol/L ÷ 88.4).
4. Round half up: glucose to a whole number, hemoglobin and potassium to one decimal place, creatinine to two decimal places. Classify the rounded value and report it with exactly those decimals.
5. Reference ranges (inclusive): glucose 70-99; potassium 3.5-5.0; hemoglobin 13.0-17.0 for males, 12.0-15.5 for females, 11.5-15.5 for children; creatinine 0.70-1.30 for males, 0.60-1.10 for females, 0.30-0.70 for children. A child is under 18 years old on the collection date.
6. Critical values take precedence: glucose below 54 is CRITICAL_LOW and above 400 is CRITICAL_HIGH; potassium below 2.8 is CRITICAL_LOW and above 6.2 is CRITICAL_HIGH; hemoglobin below 7.0 is CRITICAL_LOW.
7. Otherwise the flag is LOW below the range, HIGH above it, and NORMAL inside it.""",
        'hi': """हर मरीज़ और जाँच का नवीनतम लैब परिणाम और उसका फ़्लैग तैयार करें।
1. corrections.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है): "मान बदलें" मान और इकाई बदलता है, और "रद्द" परिणाम को हटा देता है।
2. हर मरीज़ और जाँच के लिए बचे हुए परिणामों में से सबसे बाद के नमूना समय वाला परिणाम लें (बराबरी पर बड़ी परिणाम आईडी वाला)। जिस मरीज़ और जाँच का कोई परिणाम न बचे, उसकी रिपोर्ट न दें।
3. रिपोर्ट की इकाई में बदलें: ग्लूकोज़ mg/dL में (mmol/L × 18); हीमोग्लोबिन g/dL में (g/L ÷ 10); पोटैशियम mmol/L में (mEq/L की संख्या वही रहती है); क्रिएटिनिन mg/dL में (µmol/L ÷ 88.4)।
4. राउंड हाफ़ अप करें: ग्लूकोज़ पूर्ण संख्या तक, हीमोग्लोबिन और पोटैशियम एक दशमलव स्थान तक, क्रिएटिनिन दो दशमलव स्थान तक। राउंड किए गए मान को वर्गीकृत करें और उसे ठीक इतने ही दशमलव स्थानों के साथ लिखें।
5. संदर्भ सीमाएँ (सीमा के मान सहित): ग्लूकोज़ 70-99; पोटैशियम 3.5-5.0; हीमोग्लोबिन पुरुषों के लिए 13.0-17.0, महिलाओं के लिए 12.0-15.5, बच्चों के लिए 11.5-15.5; क्रिएटिनिन पुरुषों के लिए 0.70-1.30, महिलाओं के लिए 0.60-1.10, बच्चों के लिए 0.30-0.70। बच्चा वह है जिसकी उम्र नमूना तारीख को 18 साल से कम हो।
6. गंभीर मान पहले देखें: ग्लूकोज़ 54 से कम हो तो CRITICAL_LOW और 400 से ज़्यादा हो तो CRITICAL_HIGH; पोटैशियम 2.8 से कम हो तो CRITICAL_LOW और 6.2 से ज़्यादा हो तो CRITICAL_HIGH; हीमोग्लोबिन 7.0 से कम हो तो CRITICAL_LOW।
7. वरना सीमा से कम पर LOW, ज़्यादा पर HIGH, और सीमा के अंदर NORMAL।""",
    }
    return task(
        id=tid, title='Lab result flags', domain='clinic',
        goals={'en': 'Report the latest lab value and flag for every patient and test.',
               'hi': 'हर मरीज़ और जाँच का नवीनतम लैब मान और फ़्लैग बताएँ।',
               'hinglish': 'Har patient aur test ka latest lab value aur flag batao.'},
        notice=notice, tables=tables, output=['patient', 'test', 'value', 'flag'], key_columns=2, numeric=['value'],
        answer=solve(), solve=solve,
        ablations=['corrections', 'earliest', 'convert', 'unrounded', 'child', 'sex', 'critical'])


TASKS = [appointment_rebooking, lab_flags]
