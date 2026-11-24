"""Schools: transport roster after circulars, and exam room allocation."""

from datetime import date, timedelta
import random

from .core import YES_NO, Code, Date, Id, Int, Table, Text, out_date, task

PLACES = [('Gandhi Chowk', 'गांधी चौक'), ('Railway Colony', 'रेलवे कॉलोनी'), ('Civil Lines', 'सिविल लाइंस'),
          ('Shiv Mandir', 'शिव मंदिर'), ('Old Bazaar', 'पुराना बाज़ार'), ('Nehru Nagar', 'नेहरू नगर'),
          ('Water Tank', 'पानी की टंकी'), ('Bus Stand', 'बस अड्डा'), ('Post Office', 'डाकघर'),
          ('Sabzi Mandi', 'सब्ज़ी मंडी'), ('Police Line', 'पुलिस लाइन'), ('Ram Bagh', 'राम बाग़'),
          ('Hospital Road', 'अस्पताल रोड'), ('Sector 4', 'सेक्टर 4'), ('Patel Park', 'पटेल पार्क'),
          ('Mill Gate', 'मिल गेट'), ('Kali Bari', 'काली बाड़ी'), ('Canal Bridge', 'नहर पुल'),
          ('Tehsil Office', 'तहसील कार्यालय'), ('Lal Kothi', 'लाल कोठी')]
SEATS = {'R1': 26, 'R2': 33, 'R3': 20, 'R4': 22}
OVERFLOW = 12


def bus_roster():
    tid = '03-bus-roster'
    rng = random.Random(tid)
    stops = []
    for index, (en, hi) in enumerate(PLACES):
        stops.append([f'ST{index + 1:02d}', {'en': en, 'hi': hi}, f'R{index // 5 + 1}', index % 5 + 1])
    route_of = {s[0]: s[2] for s in stops}
    order_of = {s[0]: s[3] for s in stops}
    weights = [6, 5, 7, 5, 6, 5, 6, 4, 5, 6, 5, 6, 5, 7, 6, 4, 6, 5, 6, 5]
    students = []
    sid = 0
    # Sibling groups share a stop.
    for group in range(18):
        stop = rng.choices([s[0] for s in stops], weights)[0]
        for _ in range(rng.choice([2, 3, 3, 4])):
            sid += 1
            students.append([f'S{sid:03d}', rng.randint(1, 12), stop, f'SG{group + 1:02d}', rng.random() < 0.12])
    # A low-priority sibling unit that will not fit in the last seats of its route.
    for _ in range(4):
        sid += 1
        students.append([f'S{sid:03d}', 12, 'ST09', 'SG19', False])
    while sid < 118:
        sid += 1
        students.append([f'S{sid:03d}', rng.randint(1, 12), rng.choices([s[0] for s in stops], weights)[0], None,
                         rng.random() < 0.1])
    rng.shuffle(students)
    loner = next(s for s in students if s[2] == 'ST07' and s[3] is None) if any(
        s[2] == 'ST07' and s[3] is None for s in students) else None
    if loner is None:
        loner = next(s for s in students if s[3] is None)
        loner[2] = 'ST07'
    start = date(2026, 11, 2)
    circulars = [
        ['C01', 'MOVE', 'ST03', 'ST08', None, None, True],
        ['C02', 'CLOSE', 'ST12', None, None, None, True],
        ['C03', 'MOVE', 'ST15', 'ST01', None, None, False],
        ['C04', 'MOVE', 'ST07', 'ST17', loner[0], None, True],
        ['C05', 'CANCEL', None, None, None, 'C01', True],
        ['C06', 'CLOSE', 'ST11', None, None, None, True],
        ['C07', 'CANCEL', None, None, None, 'C04', False],
        ['C08', 'MOVE', 'ST18', 'ST04', None, None, True],
        ['C09', 'CLOSE', 'ST20', None, None, None, True],
        ['C10', 'MOVE', 'ST05', 'ST09', None, None, True],
        ['C11', 'MOVE', 'ST14', 'ST02', None, None, True],
        ['C12', 'CLOSE', 'ST16', None, None, None, False],
        ['C13', 'CLOSE', 'ST08', None, None, None, True],
    ]
    circular_rows = [[c[0], start + timedelta(days=i), c[6], c[1], c[2], c[3], c[4], c[5]]
                     for i, c in enumerate(circulars)]
    file_rows = circular_rows[:]
    rng.shuffle(file_rows)

    def solve(off=frozenset()):
        active = [c for c in sorted(circular_rows) if c[2] or 'unsigned' in off]
        voided = set() if 'cancel' in off else {c[7] for c in active if c[3] == 'CANCEL'}
        current = {s[0]: s[2] for s in students}
        closed = set()
        for number, _, _, action, stop, new_stop, student, _ in active:
            if number in voided or action == 'CANCEL':
                continue
            if action == 'MOVE':
                for key in current:
                    if current[key] == stop and (student is None or key == student):
                        current[key] = new_stop
            else:
                closed.add(stop)
                route, order = route_of[stop], order_of[stop]
                lower = [s[0] for s in stops if s[2] == route and s[3] < order and
                         ('close_static' in off or s[0] not in closed)]
                higher = [s[0] for s in stops if s[2] == route and s[3] > order and
                          ('close_static' in off or s[0] not in closed)]
                lower.sort(key=lambda k: -order_of[k])
                higher.sort(key=lambda k: order_of[k])
                choices = (higher + lower) if 'close_up' in off else (lower + higher)
                if 'close_static' in off:
                    choices = [k for k in choices if abs(order_of[k] - order) == 1] or choices
                target = choices[0]
                for key in current:
                    if current[key] == stop:
                        current[key] = target
        info = {s[0]: s for s in students}
        units = {}
        for s in students:
            label = s[3] if s[3] and 'siblings' not in off else s[0]
            units.setdefault(label, []).append(s[0])

        def priority(members):
            if 'priority' in off:
                return (min(members),)
            return (0 if any(info[m][4] for m in members) else 1, min(info[m][1] for m in members), min(members))

        bus = {}
        overflow = []
        for route in ('R1', 'R2', 'R3', 'R4'):
            mine = [u for u in units.values() if route_of[current[u[0]]] == route]
            mine.sort(key=priority)
            seats = 10 ** 6 if 'capacity' in off else SEATS[route]
            stuck = False
            for members in mine:
                if len(members) <= seats and not stuck:
                    seats -= len(members)
                    for m in members:
                        bus[m] = route
                else:
                    stuck = 'stop_at_misfit' in off
                    overflow.append(members)
        if 'ov_order' not in off:
            overflow.sort(key=priority)
        seats = OVERFLOW
        for members in overflow:
            if len(members) <= seats:
                seats -= len(members)
                for m in members:
                    bus[m] = 'OV'
            else:
                for m in members:
                    bus[m] = 'WAITLIST'
        return [[s, current[s], route_of[current[s]], bus[s]] for s in sorted(current)]

    action = Code({'MOVE': (['MOVE', 'move'], ['स्थानांतरण']), 'CLOSE': (['CLOSE', 'close'], ['बंद']),
                   'CANCEL': (['CANCEL', 'cancel'], ['निरस्त'])})
    tables = [
        Table('stops', [('stop', 'स्टॉप', Id()), ('name', 'नाम', Text()), ('route', 'रूट', Id()),
                        ('order', 'क्रम', Int())], stops, tid),
        Table('students', [('student', 'विद्यार्थी', Id()), ('grade', 'कक्षा', Int()), ('stop', 'स्टॉप', Id()),
                           ('sibling_group', 'भाई-बहन समूह', Id()), ('needs_assistance', 'सहायता आवश्यक', YES_NO)],
              students, tid),
        Table('circulars', [('circular', 'परिपत्र', Id()), ('issued', 'जारी तिथि', Date()), ('signed', 'हस्ताक्षरित', YES_NO),
                            ('action', 'कार्रवाई', action), ('stop', 'स्टॉप', Id()), ('new_stop', 'नया स्टॉप', Id()),
                            ('student', 'विद्यार्थी', Id()), ('cancels', 'निरस्त परिपत्र', Id())], file_rows, tid),
    ]
    notice = {
        'en': f"""Rebuild the transport roster after this term's circulars.
1. Only signed circulars have any effect. A signed CANCEL circular voids the circular named in its cancels column; a voided circular has no effect.
2. Apply the remaining MOVE and CLOSE circulars in circular-number order (the file is not sorted), each to the stops as they stand at that point.
3. MOVE: riders at stop move to new_stop. If the student column is filled, only that student moves.
4. CLOSE: the stop closes and its riders move to the nearest open stop with a lower order number on the same route; if there is none, to the nearest open stop with a higher order number. A closed stop stays closed.
5. A student's route is the route of their final stop. Each route has one bus with this many seats: R1 {SEATS['R1']}, R2 {SEATS['R2']}, R3 {SEATS['R3']}, R4 {SEATS['R4']}.
6. Sibling groups always ride together and are seated as one unit. A student without a sibling group is a unit of one. On each route, take units in priority order: units with any student needing assistance first, then the lowest grade in the unit, then the lowest student ID in the unit. Seat each unit if all its members fit in the remaining seats; otherwise send the unit to overflow and continue with the next unit.
7. The overflow bus OV has {OVERFLOW} seats. Take all overflow units from every route in the same priority order and seat each unit that fits completely; units that do not fit get WAITLIST.
8. Report every student with their final stop, route, and bus (the route code, OV or WAITLIST).""",
        'hi': f"""इस सत्र के परिपत्रों के बाद परिवहन सूची दोबारा बनाएँ।
1. सिर्फ़ हस्ताक्षरित परिपत्रों का असर होता है। हस्ताक्षरित "निरस्त" परिपत्र, "निरस्त परिपत्र" कॉलम में लिखे परिपत्र को रद्द कर देता है; रद्द परिपत्र का कोई असर नहीं होता।
2. बचे हुए "स्थानांतरण" और "बंद" परिपत्रों को परिपत्र संख्या के क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है)। हर परिपत्र को उस समय की स्थिति पर लागू करें।
3. स्थानांतरण: स्टॉप के यात्री नए स्टॉप पर चले जाते हैं। अगर विद्यार्थी कॉलम भरा है, तो सिर्फ़ वही विद्यार्थी जाएगा।
4. बंद: स्टॉप बंद हो जाता है और उसके यात्री उसी रूट पर कम क्रम संख्या वाले सबसे नज़दीकी खुले स्टॉप पर जाते हैं; ऐसा कोई स्टॉप न हो तो ज़्यादा क्रम संख्या वाले सबसे नज़दीकी खुले स्टॉप पर। बंद स्टॉप बंद ही रहता है।
5. विद्यार्थी का रूट उसके अंतिम स्टॉप का रूट है। हर रूट पर एक बस है, जिसमें इतनी सीटें हैं: R1 {SEATS['R1']}, R2 {SEATS['R2']}, R3 {SEATS['R3']}, R4 {SEATS['R4']}।
6. एक भाई-बहन समूह के विद्यार्थी हमेशा साथ जाते हैं और एक इकाई के रूप में बैठाए जाते हैं। बिना भाई-बहन समूह वाला विद्यार्थी अकेले एक इकाई है। हर रूट पर इकाइयों को इस प्राथमिकता से लें: पहले वे इकाइयाँ जिनमें किसी को सहायता चाहिए, फिर इकाई की सबसे छोटी कक्षा, फिर इकाई की सबसे छोटी विद्यार्थी आईडी। अगर इकाई के सभी सदस्य बची सीटों में आ जाएँ तो उसे बैठाएँ; वरना उसे ओवरफ़्लो में भेजें और अगली इकाई पर जाएँ।
7. ओवरफ़्लो बस OV में {OVERFLOW} सीटें हैं। सभी रूटों की ओवरफ़्लो इकाइयों को इसी प्राथमिकता क्रम में लें और जो इकाई पूरी आ जाए उसे बैठाएँ; जो न आए उसे WAITLIST दें।
8. हर विद्यार्थी का अंतिम स्टॉप, रूट और बस (रूट कोड, OV या WAITLIST) बताएँ।""",
    }
    return task(
        id=tid, title='School bus roster', domain='schools',
        goals={'en': 'Produce the final bus roster for every student after the transport circulars.',
               'hi': 'परिवहन परिपत्रों के बाद हर विद्यार्थी की अंतिम बस सूची तैयार करें।',
               'hinglish': 'Transport circulars ke baad har student ka final bus roster banao.'},
        notice=notice, tables=tables, output=['student', 'stop', 'route', 'bus'], answer=solve(), solve=solve,
        ablations=['unsigned', 'cancel', 'close_up', 'close_static', 'capacity', 'siblings', 'priority',
                   'stop_at_misfit', 'ov_order'])


ROOMS = [('R101', 24, True), ('R102', 30, False), ('R103', 36, True), ('R104', 40, False), ('R201', 48, False),
         ('R202', 60, True), ('R203', 20, True), ('LAB1', 32, True), ('HALL', 90, False)]


def exam_seating():
    tid = '04-exam-seating'
    rng = random.Random(tid)
    sessions = [(date(2026, 11, 23) + timedelta(days=d), s) for d in range(3) for s in ('AM', 'PM')]
    closures = [['HALL', sessions[1][0], 'PM'], ['HALL', sessions[4][0], 'AM'], ['R202', sessions[2][0], 'AM'],
                ['R103', sessions[0][0], 'AM'], ['LAB1', sessions[5][0], 'PM'], ['R201', sessions[3][0], 'PM']]
    subjects = [('Mathematics', 'गणित'), ('Science', 'विज्ञान'), ('Hindi', 'हिंदी'), ('English', 'अंग्रेज़ी'),
                ('Social Studies', 'सामाजिक विज्ञान'), ('Sanskrit', 'संस्कृत'), ('Computer', 'कंप्यूटर')]
    groups = []
    gid = 0
    for number, (day, session) in enumerate(sessions):
        load = 0
        target = 320 if number == 4 else rng.randint(200, 250)
        while load < target:
            gid += 1
            size = rng.choice([rng.randint(12, 30), rng.randint(12, 30), rng.randint(31, 55), rng.randint(60, 100)])
            subject = rng.choice(subjects)
            groups.append([f'G{gid:02d}', {'en': subject[0], 'hi': subject[1]}, day, session, size,
                           rng.random() < 0.25])
            load += size
    rng.shuffle(groups)
    changes = []
    picks = rng.sample(groups, 9)
    for g in picks[:4]:
        changes.append([g[0], 'SET_SIZE', g[4] + rng.choice([-9, -5, 6, 14, 25]), None, None])
    for g in picks[4:7]:
        day, session = rng.choice([s for s in sessions if s != (g[2], g[3])])
        changes.append([g[0], 'MOVE', None, day, session])
    for g in picks[7:]:
        changes.append([g[0], 'CANCEL', None, None, None])
    changes.append([picks[0][0], 'SET_SIZE', picks[0][4] + 31, None, None])
    changes = [[seq, *row] for seq, row in enumerate(changes, 1)]
    file_changes = changes[:]
    rng.shuffle(file_changes)

    def solve(off=frozenset()):
        data = {g[0]: {'date': g[2], 'session': g[3], 'size': g[4], 'step': g[5], 'cancel': False} for g in groups}
        if 'amend' not in off:
            for _, key, act, size, day, session in sorted(changes):
                if act == 'SET_SIZE':
                    data[key]['size'] = size
                elif act == 'MOVE':
                    data[key]['date'], data[key]['session'] = day, session
                else:
                    data[key]['cancel'] = True
        closed = set() if 'closures' in off else {(r, d, s) for r, d, s in closures}
        result = {}
        for day, session in sessions:
            mine = [k for k in data if (data[k]['date'], data[k]['session']) == (day, session) and not data[k]['cancel']]
            if 'order_id' in off:
                mine.sort()
            elif 'order_asc' in off:
                mine.sort(key=lambda k: (data[k]['size'], k))
            else:
                mine.sort(key=lambda k: (-data[k]['size'], k))
            used = set()
            for key in mine:
                need = data[key]['size']
                eligible = [r for r in ROOMS if r[0] not in used and (r[0], day, session) not in closed
                            and (r[2] or not data[key]['step'] or 'step_free' in off)]
                fits = [r for r in eligible if r[1] >= need]
                if fits:
                    choice = max(fits, key=lambda r: (r[1], r[0])) if 'largest_fit' in off else min(
                        fits, key=lambda r: (r[1], r[0]))
                    taken = [choice]
                else:
                    pool = sorted(eligible, key=lambda r: (r[1], r[0]) if 'split_smallest' in off else (-r[1], r[0]))
                    taken = []
                    total = 0
                    for room in pool:
                        if total >= need:
                            break
                        taken.append(room)
                        total += room[1]
                    if total < need and 'partial_unseated' not in off:
                        result[key] = ('', 'UNSEATED')
                        continue
                used.update(r[0] for r in taken)
                result[key] = ('+'.join(r[0] for r in taken), 'SEATED')
        answer = []
        for key in sorted(data):
            item = data[key]
            rooms, status = ('', 'CANCELLED') if item['cancel'] else result[key]
            answer.append([key, out_date(item['date']), item['session'], rooms, status])
        return answer

    session_code = Code({'AM': (['AM', 'Morning'], ['पूर्वाह्न', 'सुबह']), 'PM': (['PM', 'Afternoon'], ['अपराह्न', 'दोपहर'])})
    action = Code({'SET_SIZE': (['SET_SIZE'], ['संख्या बदलें']), 'MOVE': (['MOVE'], ['सत्र बदलें']),
                   'CANCEL': (['CANCEL'], ['रद्द'])})
    tables = [
        Table('rooms', [('room', 'कमरा', Id()), ('seats', 'सीटें', Int()), ('step_free', 'बिना सीढ़ी पहुँच', YES_NO)],
              [list(r) for r in ROOMS], tid),
        Table('closures', [('room', 'कमरा', Id()), ('date', 'तारीख', Date()), ('session', 'सत्र', session_code)],
              closures, tid),
        Table('groups', [('group', 'समूह', Id()), ('subject', 'विषय', Text()), ('date', 'तारीख', Date()),
                         ('session', 'सत्र', session_code), ('candidates', 'परीक्षार्थी', Int()),
                         ('needs_step_free', 'बिना सीढ़ी पहुँच चाहिए', YES_NO)], groups, tid),
        Table('changes', [('seq', 'क्रम', Int()), ('group', 'समूह', Id()), ('action', 'कार्रवाई', action),
                          ('candidates', 'परीक्षार्थी', Int()), ('date', 'तारीख', Date()), ('session', 'सत्र', session_code)],
              file_changes, tid),
    ]
    notice = {
        'en': """Allocate rooms for the end-of-term examinations.
1. Apply changes.csv in ascending seq order (the file is not sorted). SET_SIZE replaces the number of candidates, MOVE moves the group to the given date and session, and CANCEL cancels the group. Later changes to the same field override earlier ones.
2. Handle each session (date and AM/PM) separately. Within a session take the groups from the largest number of candidates to the smallest, breaking ties by group ID.
3. A room can hold only one group per session and cannot be used in a session listed in closures.csv. A group that needs step-free access can only use step-free rooms.
4. If at least one eligible room can seat the whole group, use the smallest such room (ties by room code).
5. Otherwise split the group: take eligible rooms from the most seats to the fewest (ties by room code) until the total seats cover the group. List the rooms in the order taken, joined with +.
6. If all eligible rooms together cannot seat the group, it is UNSEATED, rooms is blank, and it uses no rooms.
7. Report every group with its final date (YYYY-MM-DD), session (AM or PM), rooms and status (SEATED, UNSEATED or CANCELLED). Cancelled groups have blank rooms.""",
        'hi': """सत्रांत परीक्षाओं के लिए कमरे आवंटित करें।
1. changes.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है)। "संख्या बदलें" परीक्षार्थियों की संख्या बदलता है, "सत्र बदलें" समूह को दी गई तारीख और सत्र में ले जाता है, और "रद्द" समूह को रद्द करता है। एक ही फ़ील्ड के बाद वाले बदलाव पहले वालों की जगह लेते हैं।
2. हर सत्र (तारीख और पूर्वाह्न/अपराह्न) को अलग से देखें। एक सत्र में समूहों को सबसे ज़्यादा परीक्षार्थियों से सबसे कम की ओर लें; बराबरी होने पर समूह आईडी के क्रम में।
3. एक सत्र में एक कमरे में सिर्फ़ एक समूह बैठ सकता है, और closures.csv में दिए सत्र में वह कमरा इस्तेमाल नहीं हो सकता। जिस समूह को बिना सीढ़ी पहुँच चाहिए, वह सिर्फ़ बिना सीढ़ी पहुँच वाले कमरे ले सकता है।
4. अगर कम से कम एक योग्य कमरे में पूरा समूह बैठ सके, तो ऐसा सबसे छोटा कमरा लें (बराबरी पर कमरा कोड के क्रम में)।
5. वरना समूह को बाँटें: योग्य कमरों को सबसे ज़्यादा सीटों से सबसे कम की ओर लें (बराबरी पर कमरा कोड के क्रम में), जब तक कुल सीटें पूरे समूह के लिए काफ़ी न हो जाएँ। कमरों को लिए गए क्रम में + से जोड़कर लिखें।
6. अगर सभी योग्य कमरे मिलाकर भी समूह को नहीं बैठा सकते, तो वह UNSEATED है, rooms खाली है, और वह कोई कमरा नहीं लेता।
7. हर समूह की अंतिम तारीख (YYYY-MM-DD), सत्र (AM या PM; पूर्वाह्न = AM, अपराह्न = PM), कमरे और status (SEATED, UNSEATED या CANCELLED) बताएँ। रद्द समूहों के कमरे खाली रहेंगे।""",
    }
    return task(
        id=tid, title='Exam room allocation', domain='schools',
        goals={'en': 'Allocate examination rooms to every candidate group for the end-of-term exams.',
               'hi': 'सत्रांत परीक्षाओं के लिए परीक्षार्थियों के हर समूह को कमरे आवंटित करें।',
               'hinglish': 'End-of-term exams ke liye har candidate group ko exam rooms allot karo.'},
        notice=notice, tables=tables, output=['group', 'date', 'session', 'rooms', 'status'], answer=solve(),
        solve=solve, ablations=['amend', 'order_id', 'order_asc', 'largest_fit', 'step_free', 'closures',
                                'split_smallest', 'partial_unseated'])


TASKS = [bus_roster, exam_seating]
