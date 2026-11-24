"""Municipal: ward water-supply schedule after notices, and grievance de-duplication with SLAs."""

from datetime import date, datetime, timedelta
import random

from .core import YES_NO, Code, Date, DateTime, Id, Int, Table, Text, Time, out_date, out_datetime, out_time, task

WARDS = [f'W{i:02d}' for i in range(1, 13)]
DAYS = [date(2026, 11, 18) + timedelta(days=d) for d in range(5)]


def water_schedule():
    tid = '09-water-schedule'
    rng = random.Random(tid)
    schedule = []
    for ward in WARDS:
        for day in DAYS:
            if rng.random() < 0.08:
                schedule.append([ward, day, None, None])
                continue
            start = rng.randint(20, 64) * 15
            schedule.append([ward, day, start, start + rng.choice([90, 105, 120, 135, 150, 180, 240])])
    rng.shuffle(schedule)
    notices = []

    def add(ward, day, action, start=None, end=None, minutes=None, signed=True):
        notices.append([ward, day, action, start, end, minutes, signed])

    add('ALL', DAYS[2], 'EXTEND', minutes=30)
    for _ in range(9):
        start = rng.randint(22, 70) * 15
        add(rng.choice(WARDS), rng.choice(DAYS), 'SET', start, start + rng.choice([60, 90, 120, 135, 180]))
    for _ in range(5):
        add(rng.choice(WARDS), rng.choice(DAYS), 'CANCEL')
    for _ in range(6):
        add(rng.choice(WARDS), rng.choice(DAYS), 'EXTEND', minutes=rng.choice([15, 30, 45, 60]))
    for _ in range(7):
        start = rng.randint(22, 70) * 15
        choice = rng.random()
        if choice < 0.4:
            add(rng.choice(WARDS), rng.choice(DAYS), 'CANCEL', signed=False)
        elif choice < 0.7:
            add(rng.choice(WARDS), rng.choice(DAYS), 'SET', start, start + 60, signed=False)
        else:
            add('ALL', rng.choice(DAYS), 'EXTEND', minutes=60, signed=False)
    rng.shuffle(notices)
    # Deliberate sequences: cancel then restore; extend after cancel; a cut to exactly 120 minutes.
    add('W03', DAYS[1], 'CANCEL')
    add('W03', DAYS[1], 'EXTEND', minutes=60)
    add('W05', DAYS[3], 'CANCEL')
    add('W05', DAYS[3], 'SET', 19 * 60 + 30, 21 * 60)
    add('W08', DAYS[0], 'SET', 6 * 60, 8 * 60)
    add('ALL', DAYS[4], 'CANCEL', signed=False)
    add('W11', DAYS[4], 'SET', 16 * 60 + 45, 18 * 60 + 30)
    add('W11', DAYS[4], 'SET', 5 * 60 + 30, 6 * 60 + 15)
    rows = [[f'N{i + 1:03d}', *n] for i, n in enumerate(notices)]
    file_rows = rows[:]
    rng.shuffle(file_rows)

    def solve(off=frozenset()):
        plan = {(w, d): (s, e) for w, d, s, e in schedule}
        base = dict(plan)
        cancelled_once = set()
        ordered = file_rows if 'order' in off else rows
        for number, ward, day, action, start, end, minutes, signed in ordered:
            if not signed and 'unsigned' not in off:
                continue
            if ward == 'ALL':
                targets = [] if 'all' in off else WARDS
            else:
                targets = [ward]
            for w in targets:
                key = (w, day)
                if action == 'SET':
                    if 'cancel_permanent' in off and key in cancelled_once:
                        continue
                    plan[key] = (start, end)
                elif action == 'CANCEL':
                    plan[key] = (None, None)
                    cancelled_once.add(key)
                else:
                    s, e = plan[key]
                    if s is None:
                        if 'extend_cancelled' in off and base[key][0] is not None:
                            plan[key] = (base[key][0], base[key][1] + minutes)
                        continue
                    plan[key] = (s, e + minutes)
        answer = []
        for ward in WARDS:
            for day in DAYS:
                s, e = plan[(ward, day)]
                minutes = 0 if s is None else e - s
                short = minutes <= 120 if 'tanker_inclusive' in off else minutes < 120
                answer.append([ward, out_date(day), '' if s is None else out_time(s), '' if e is None else out_time(e),
                               str(minutes), 'YES' if short else 'NO'])
        return answer

    action = Code({'SET': (['SET', 'set window'], ['समय तय करें']), 'CANCEL': (['CANCEL', 'cancel'], ['आपूर्ति रद्द']),
                   'EXTEND': (['EXTEND', 'extend'], ['समय बढ़ाएँ'])})
    tables = [
        Table('schedule', [('ward', 'वार्ड', Id()), ('date', 'तारीख', Date()), ('start', 'शुरू', Time()),
                           ('end', 'समाप्त', Time())], schedule, tid),
        Table('notices', [('notice', 'सूचना', Id()), ('ward', 'वार्ड', Id()), ('date', 'तारीख', Date()),
                          ('action', 'कार्रवाई', action), ('start', 'शुरू', Time()), ('end', 'समाप्त', Time()),
                          ('minutes', 'मिनट', Int()), ('signed', 'हस्ताक्षरित', YES_NO)], file_rows, tid),
    ]
    notice = {
        'en': """Publish the final water-supply plan for 18-22 November 2026.
1. Each ward has at most one supply window per day. A blank start and end in schedule.csv means no supply that day.
2. Only signed notices have any effect. Apply them in notice-number order (the file is not sorted). Ward ALL means every ward on that date.
3. SET replaces that day's window with the given start and end (this also restores supply after a cancellation). CANCEL removes the supply for that day. EXTEND moves the end later by the given minutes; it has no effect on a day that currently has no supply.
4. Report every ward and date: start and end as HH:MM in 24-hour time (blank if there is no supply), minutes of supply (0 if none), and tanker = YES if the day has less than 120 minutes of supply, otherwise NO.""",
        'hi': """18-22 नवंबर 2026 की जल आपूर्ति की अंतिम योजना जारी करें।
1. हर वार्ड में एक दिन में ज़्यादा से ज़्यादा एक आपूर्ति अवधि होती है। schedule.csv में शुरू और समाप्त खाली हों तो उस दिन आपूर्ति नहीं है।
2. सिर्फ़ हस्ताक्षरित सूचनाओं का असर होता है। उन्हें सूचना संख्या के क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है)। वार्ड ALL का मतलब है उस तारीख को सभी वार्ड।
3. "समय तय करें" उस दिन की अवधि को दिए गए शुरू और समाप्त समय से बदल देता है (रद्द होने के बाद यह आपूर्ति फिर शुरू भी कर देता है)। "आपूर्ति रद्द" उस दिन की आपूर्ति हटा देता है। "समय बढ़ाएँ" समाप्ति को दिए गए मिनट जितना आगे बढ़ाता है; जिस दिन उस समय आपूर्ति नहीं है, उस पर इसका कोई असर नहीं होता।
4. हर वार्ड और तारीख की रिपोर्ट दें: start और end 24-घंटे के HH:MM रूप में (आपूर्ति न हो तो खाली), आपूर्ति के मिनट (न हो तो 0), और tanker = YES अगर उस दिन 120 मिनट से कम आपूर्ति है, वरना NO।""",
    }
    return task(
        id=tid, title='Ward water-supply plan', domain='municipal',
        goals={'en': 'Publish the final water-supply plan for every ward and day, including where tankers are needed.',
               'hi': 'हर वार्ड और दिन की जल आपूर्ति की अंतिम योजना जारी करें, और बताएँ कि टैंकर कहाँ चाहिए।',
               'hinglish': 'Har ward aur din ka final water-supply plan banao, aur batao kahan tanker chahiye.'},
        notice=notice, tables=tables, output=['ward', 'date', 'start', 'end', 'minutes', 'tanker'], key_columns=2,
        numeric=['minutes'], answer=solve(), solve=solve,
        ablations=['unsigned', 'order', 'all', 'cancel_permanent', 'extend_cancelled', 'tanker_inclusive'])


LANDMARKS = [
    ('L01', ['Hanuman Mandir', 'Hanuman Temple', 'हनुमान मंदिर']),
    ('L02', ['Clock Tower', 'Ghanta Ghar', 'घंटाघर', 'घंटा घर']),
    ('L03', ['Main Market', 'Bada Bazaar', 'बड़ा बाज़ार', 'मेन मार्केट']),
    ('L04', ['Govt School', 'Sarkari School', 'सरकारी स्कूल']),
    ('L05', ['Bus Depot', 'Roadways Depot', 'बस डिपो', 'रोडवेज़ डिपो']),
    ('L06', ['Water Tank', 'Paani Tanki', 'पानी की टंकी']),
    ('L07', ['Railway Crossing', 'Phatak', 'रेलवे फाटक', 'फाटक']),
    ('L08', ['Masjid Chowk', 'Jama Masjid Chowk', 'मस्जिद चौक']),
    ('L09', ['Gurudwara Road', 'गुरुद्वारा रोड']),
    ('L10', ['Sabzi Mandi', 'Vegetable Market', 'सब्ज़ी मंडी']),
    ('L11', ['Community Hall', 'Baraat Ghar', 'बारात घर', 'सामुदायिक भवन']),
    ('L12', ['Petrol Pump', 'पेट्रोल पंप']),
]
SLA = {'GARBAGE': 24, 'DRAIN': 48, 'STREETLIGHT': 72, 'WATER_LEAK': 12}
DEPARTMENT = {'GARBAGE': 'SANITATION', 'DRAIN': 'DRAINAGE', 'STREETLIGHT': 'ELECTRICAL', 'WATER_LEAK': 'WATER'}
AUDIT = datetime(2026, 11, 17, 18, 0)


def clamp(moment):
    """Keep generated times between 06:00 and 22:59 so every time form is unambiguous."""
    if moment.hour < 6:
        return moment.replace(hour=6, minute=moment.minute)
    if moment.hour > 22:
        return moment.replace(hour=22)
    return moment


def grievance_dedup():
    tid = '10-grievance-dedup'
    rng = random.Random(tid)
    alias_rows = [[alias, key] for key, aliases in LANDMARKS for alias in aliases]

    def noisy(alias):
        if not alias.isascii():
            return alias
        return rng.choice([alias, alias.lower(), alias.upper(), '  ' + alias, alias.replace(' ', '  ')])

    tickets = []

    def ticket(created, ward, landmark, category):
        resolved = None
        if rng.random() < 0.65:
            resolved = clamp(created + timedelta(hours=rng.choice([3, 8, 11, 20, 26, 30, 47, 50, 70, 80])))
            if resolved > AUDIT:
                resolved = None
        tickets.append({'created': created, 'ward': ward, 'landmark': noisy(rng.choice(dict(LANDMARKS)[landmark])),
                        'canonical': landmark, 'category': category, 'resolved': resolved})

    for _ in range(45):
        created = clamp(datetime(2026, 11, 12, 6) + timedelta(minutes=rng.randint(0, 5 * 24 * 60)))
        ward, landmark, category = f'W{rng.randint(1, 6)}', rng.choice(LANDMARKS)[0], rng.choice(list(SLA))
        ticket(created, ward, landmark, category)
        for offset in rng.sample([2, 9, 30, 47, 48, 49, 52, 70], rng.randint(0, 3)):
            later = created + timedelta(hours=offset)
            if 6 <= later.hour <= 22 and later < AUDIT:
                ticket(later, ward, landmark, category)
    for _ in range(25):
        created = clamp(datetime(2026, 11, 12, 6) + timedelta(minutes=rng.randint(0, 5 * 24 * 60)))
        ticket(created, f'W{rng.randint(1, 6)}', rng.choice(LANDMARKS)[0], rng.choice(list(SLA)))
    rng.shuffle(tickets)
    for index, item in enumerate(tickets):
        item['id'] = f'T{index + 1:04d}'
    amendments = []
    for item in rng.sample(tickets, 6):
        amendments.append([item['id'], 'SET_CATEGORY', rng.choice([c for c in SLA if c != item['category']])])
    for item in rng.sample(tickets, 4):
        amendments.append([item['id'], 'WITHDRAWN', None])
    amendments = [[seq, *row] for seq, row in enumerate(amendments, 1)]
    file_amends = amendments[:]
    rng.shuffle(file_amends)
    lookup = {' '.join(alias.split()).casefold(): key for alias, key in alias_rows}

    def solve(off=frozenset()):
        data = {t['id']: dict(t) for t in tickets}
        withdrawn = set()
        if 'amend' not in off:
            for _, key, act, category in sorted(file_amends):
                if act == 'SET_CATEGORY':
                    data[key]['category'] = category
                elif 'withdrawn' not in off:
                    withdrawn.add(key)
        clusters = []
        open_cluster = {}
        for key in sorted((k for k in data if k not in withdrawn), key=lambda k: (data[k]['created'], k)):
            item = data[key]
            text = ' '.join(item['landmark'].split()).casefold()
            place = text if 'alias' in off else lookup[text]
            group = (item['ward'], place, item['category'])
            current = open_cluster.get(group)
            if current:
                anchor = data[current[-1]]['created'] if 'window_chain' in off else data[current[0]]['created']
                gap = item['created'] - anchor
                limit = timedelta(hours=48)
                if gap < limit or (gap == limit and 'window_exclusive' not in off):
                    current.append(key)
                    continue
            current = [key]
            open_cluster[group] = current
            clusters.append(current)
        answer = []
        for members in sorted(clusters, key=lambda c: c[0]):
            head = data[members[0]]
            anchor = max(data[m]['created'] for m in members) if 'sla_member' in off else head['created']
            due = anchor + timedelta(hours=SLA[head['category']])
            times = [data[m]['resolved'] for m in members if data[m]['resolved']]
            resolved = (max(times) if 'resolved_latest' in off else min(times)) if times else None
            if resolved:
                breached = resolved > due
            else:
                breached = True if 'pending_breach' in off else due < AUDIT
            department = DEPARTMENT[head['category']]
            if head['category'] == 'GARBAGE' and head['ward'] in ('W5', 'W6') and 'dept_exception' not in off:
                department = 'CONTRACTOR'
            answer.append([members[0], str(len(members) - 1), department, out_datetime(due), 'YES' if breached else 'NO'])
        return answer

    category = Code({'GARBAGE': (['GARBAGE', 'Garbage'], ['कचरा']), 'DRAIN': (['DRAIN', 'Drain'], ['नाली']),
                     'STREETLIGHT': (['STREETLIGHT', 'Streetlight'], ['स्ट्रीटलाइट']),
                     'WATER_LEAK': (['WATER_LEAK', 'Water leak'], ['पानी रिसाव'])})
    action = Code({'SET_CATEGORY': (['SET_CATEGORY'], ['श्रेणी बदलें']), 'WITHDRAWN': (['WITHDRAWN'], ['शिकायत वापस'])})
    tables = [
        Table('landmarks', [('alias', 'उपनाम', Text()), ('landmark', 'स्थल', Id())], alias_rows, tid),
        Table('tickets', [('ticket', 'शिकायत', Id()), ('created', 'दर्ज समय', DateTime()), ('ward', 'वार्ड', Id()),
                          ('landmark', 'स्थल विवरण', Text()), ('category', 'श्रेणी', category),
                          ('resolved', 'निपटान समय', DateTime())],
              [[t['id'], t['created'], t['ward'], t['landmark'], t['category'], t['resolved']] for t in tickets], tid),
        Table('amendments', [('seq', 'क्रम', Int()), ('ticket', 'शिकायत', Id()), ('action', 'कार्रवाई', action),
                             ('category', 'श्रेणी', category)], file_amends, tid),
    ]
    notice = {
        'en': """Consolidate sanitation and civic grievances. The audit time is 2026-11-17 18:00.
1. Apply amendments.csv in ascending seq order (the file is not sorted): SET_CATEGORY replaces the category, and WITHDRAWN removes the ticket entirely.
2. Map each ticket's landmark text to a landmark code using landmarks.csv after trimming, collapsing repeated spaces and ignoring letter case.
3. Process the remaining tickets in order of creation time (ties by ticket ID). A ticket is a duplicate if it has the same ward, landmark code and category as an open cluster and was created no more than 48 hours (inclusive) after that cluster's first ticket. Otherwise it starts a new cluster, which replaces the earlier cluster for later tickets. The first ticket of a cluster is its canonical ticket.
4. SLA hours by category: GARBAGE 24, DRAIN 48, STREETLIGHT 72, WATER_LEAK 12. due = canonical ticket's creation time + SLA hours.
5. A cluster is resolved at the earliest resolved time among its tickets. breached = YES if it was resolved after due, or if it is unresolved and due is before the audit time; otherwise NO.
6. Department: GARBAGE goes to SANITATION, except in wards W5 and W6 where it goes to CONTRACTOR; DRAIN to DRAINAGE; STREETLIGHT to ELECTRICAL; WATER_LEAK to WATER. Use the canonical ticket's ward and category.
7. Report one row per cluster: the canonical ticket, duplicates (number of other tickets in the cluster), department, due as YYYY-MM-DD HH:MM, and breached.""",
        'hi': """सफ़ाई और नागरिक शिकायतों को एकत्र करें। जाँच का समय 2026-11-17 18:00 है।
1. amendments.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है): "श्रेणी बदलें" श्रेणी बदलता है, और "शिकायत वापस" उस शिकायत को पूरी तरह हटा देता है।
2. हर शिकायत के स्थल विवरण को landmarks.csv की मदद से स्थल कोड में बदलें; शुरुआत और आख़िर के स्पेस हटाएँ, लगातार स्पेस को एक करें और अक्षरों के छोटे-बड़े रूप को नज़रअंदाज़ करें।
3. बची हुई शिकायतों को दर्ज समय के क्रम में लें (बराबरी पर शिकायत आईडी के क्रम में)। कोई शिकायत डुप्लिकेट है अगर उसका वार्ड, स्थल कोड और श्रेणी किसी खुले समूह जैसा हो और वह उस समूह की पहली शिकायत के 48 घंटे के अंदर (48 घंटे सहित) दर्ज हुई हो। वरना वह नया समूह शुरू करती है, और आगे की शिकायतों के लिए यह नया समूह पुराने की जगह लेता है। समूह की पहली शिकायत उसकी मूल शिकायत है।
4. श्रेणी के हिसाब से SLA घंटे: कचरा (GARBAGE) 24, नाली (DRAIN) 48, स्ट्रीटलाइट (STREETLIGHT) 72, पानी रिसाव (WATER_LEAK) 12। due = मूल शिकायत का दर्ज समय + SLA घंटे।
5. समूह का निपटान उसकी शिकायतों में सबसे पहले निपटान समय पर माना जाएगा। breached = YES अगर निपटान due के बाद हुआ, या निपटान नहीं हुआ और due जाँच के समय से पहले है; वरना NO।
6. विभाग: कचरा SANITATION को जाता है, सिवाय वार्ड W5 और W6 के, जहाँ यह CONTRACTOR को जाता है; नाली DRAINAGE को; स्ट्रीटलाइट ELECTRICAL को; पानी रिसाव WATER को। मूल शिकायत का वार्ड और श्रेणी लें।
7. हर समूह की एक पंक्ति दें: मूल शिकायत, duplicates (समूह की बाकी शिकायतों की संख्या), department, due (YYYY-MM-DD HH:MM रूप में), और breached।""",
    }
    return task(
        id=tid, title='Grievance consolidation', domain='municipal',
        goals={'en': 'Consolidate duplicate civic grievances and report the SLA position of each cluster.',
               'hi': 'डुप्लिकेट नागरिक शिकायतों को एकत्र करें और हर समूह की SLA स्थिति बताएँ।',
               'hinglish': 'Duplicate civic complaints ko consolidate karo aur har cluster ki SLA position batao.'},
        notice=notice, tables=tables, output=['ticket', 'duplicates', 'department', 'due', 'breached'],
        numeric=['duplicates'], answer=solve(), solve=solve,
        ablations=['amend', 'withdrawn', 'alias', 'window_exclusive', 'window_chain', 'sla_member',
                   'resolved_latest', 'pending_breach', 'dept_exception'])


TASKS = [water_schedule, grievance_dedup]
