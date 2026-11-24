"""Archives: catalogue de-duplication by ISBN and edition, and digitization page audit."""

import random
import re

from .core import TO_DEV, Code, Id, Int, Table, Text, task

TITLES = [('गोदान', 'Godaan'), ('मधुशाला', 'Madhushala'), ('राग दरबारी', 'Raag Darbari'), ('तमस', 'Tamas'),
          ('मैला आँचल', 'Maila Aanchal'), ('गुनाहों का देवता', 'Gunahon Ka Devta'), ('कामायनी', 'Kamayani'),
          ('निर्मला', 'Nirmala'), ('आपका बंटी', 'Aapka Bunty'), ('चित्रलेखा', 'Chitralekha'), ('झूठा सच', 'Jhootha Sach'),
          ('कितने पाकिस्तान', 'Kitne Pakistan'), ('रश्मिरथी', 'Rashmirathi'), ('अंधा युग', 'Andha Yug'),
          ('शेखर: एक जीवनी', 'Shekhar Ek Jeevani'), ('सारा आकाश', 'Sara Akash'), ('आधा गाँव', 'Aadha Gaon'),
          ('महाभोज', 'Mahabhoj'), ('नदी के द्वीप', 'Nadi Ke Dweep'), ('बाणभट्ट की आत्मकथा', 'Banabhatta Ki Atmakatha'),
          ('कसप', 'Kasap'), ('दीवार में एक खिड़की रहती थी', 'Deewar Mein Ek Khidki Rehti Thi'), ('ग़बन', 'Gaban'),
          ('कर्मभूमि', 'Karmabhoomi'), ('पचपन खंभे लाल दीवारें', 'Pachpan Khambe Laal Deewarein'), ('उर्वशी', 'Urvashi'),
          ('मुझे चाँद चाहिए', 'Mujhe Chand Chahiye'), ('राग विराग', 'Raag Virag'), ('मृगनयनी', 'Mriganayani'),
          ('बूँद और समुद्र', 'Boond Aur Samudra')]
EDITION = Code({1: (['1st ed.', 'first edition', 'Ed. 1', '1'], ['पहला संस्करण', 'प्रथम संस्करण', 'संस्करण 1', '१']),
                2: (['2nd ed.', 'second edition', 'Ed. 2', '2'], ['दूसरा संस्करण', 'द्वितीय संस्करण', 'संस्करण 2', '२']),
                3: (['3rd ed.', 'third edition', 'Ed. 3', '3'], ['तीसरा संस्करण', 'तृतीय संस्करण', 'संस्करण 3', '३'])})


def check13(digits12):
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits12))
    return str((10 - total % 10) % 10)


def check10(digits9):
    total = sum(int(d) * (10 - i) for i, d in enumerate(digits9))
    value = (11 - total % 11) % 11
    return 'X' if value == 10 else str(value)


def to_isbn13(text, off=frozenset()):
    code = re.sub(r'[\s-]', '', text.upper().replace('ISBN', ''))
    if len(code) == 13 and code.isdigit():
        return code if 'checksum' in off or check13(code[:12]) == code[12] else None
    if len(code) == 10 and code[:9].isdigit() and (code[9].isdigit() or code[9] == 'X'):
        if 'isbn10' in off:
            return code
        if 'checksum' not in off and check10(code[:9]) != code[9]:
            return None
        body = '978' + code[:9]
        return body + check13(body)
    return None


def catalogue_merge():
    tid = '15-catalogue-merge'
    rng = random.Random(tid)
    records = []
    numbers = rng.sample(range(120, 4000), 120)
    used = 0

    def accession():
        nonlocal used
        used += 1
        return f'ACC-{numbers[used - 1]}'

    def render(isbn13, style):
        isbn10 = isbn13[3:12] + check10(isbn13[3:12])
        return [f'{isbn13[:3]}-{isbn13[3:5]}-{isbn13[5:9]}-{isbn13[9:12]}-{isbn13[12]}', isbn13,
                f'{isbn10[:2]}-{isbn10[2:6]}-{isbn10[6:9]}-{isbn10[9]}', isbn10, 'ISBN ' + isbn13][style]

    true_isbn = {}
    for index, (deva, latin) in enumerate(TITLES):
        body = '97881' + f'{rng.randint(0, 9999999):07d}'
        isbn13 = body + check13(body)
        for edition in range(1, rng.choice([2, 2, 3]) if index % 3 == 0 else 2):
            for _ in range(rng.choice([1, 2, 2, 3, 4])):
                title = deva if rng.random() < 0.55 else latin
                text = render(isbn13, rng.randrange(5))
                records.append([accession(), text, title, edition, rng.randint(1970, 2024), 'ACTIVE'])
                true_isbn[records[-1][0]] = isbn13
    # Records with a broken checksum and records with no ISBN at all.
    for row in rng.sample(records, 5):
        code = row[1]
        last = code[-1]
        row[1] = code[:-1] + ('0' if last != '0' else '1')
    for row in rng.sample([r for r in records if r[1][-1] != 'X'], 3):
        row[1] = ''
    for row in rng.sample(records, 4):
        row[5] = 'WITHDRAWN'
    rng.shuffle(records)
    amendments = []
    broken = [r for r in records if r[1] and to_isbn13(r[1]) is None]
    fixable = broken[0]
    good = true_isbn[fixable[0]]
    amendments.append([fixable[0], 'SET_ISBN', render(good, 2), None])
    for row in rng.sample(records, 3):
        amendments.append([row[0], 'SET_EDITION', None, 1 if row[3] != 1 else 2])
    for row in rng.sample(records, 2):
        amendments.append([row[0], 'WITHDRAW', None, None])
    amendments = [[seq, *row] for seq, row in enumerate(amendments, 1)]
    file_amends = amendments[:]
    rng.shuffle(file_amends)

    def number(acc):
        return acc if 'lexical' in off_flags[0] else int(acc.split('-')[1])

    off_flags = [frozenset()]

    def solve(off=frozenset()):
        off_flags[0] = off
        data = {r[0]: {'isbn': r[1], 'title': r[2], 'edition': r[3], 'status': r[5]} for r in records}
        if 'amend' not in off:
            for _, key, act, isbn, edition in sorted(file_amends):
                if act == 'SET_ISBN':
                    data[key]['isbn'] = isbn
                elif act == 'SET_EDITION':
                    data[key]['edition'] = edition
                else:
                    data[key]['status'] = 'WITHDRAWN'
        groups = {}
        for key, item in data.items():
            if item['status'] == 'WITHDRAWN' and 'withdrawn' not in off:
                continue
            isbn = to_isbn13(item['isbn'], off) if item['isbn'] else None
            edition = 0 if 'edition' in off else item['edition']
            group = (isbn, edition) if isbn else ('single', key)
            groups.setdefault(group, []).append(key)
        answer = []
        for group, members in groups.items():
            members.sort(key=number)
            deva = [m for m in members if re.search(r'[ऀ-ॿ]', data[m]['title'])]
            head = members[0] if 'deva' in off or not deva else deva[0]
            rest = [m for m in members if m != head]
            isbn = '' if group[0] == 'single' else group[0]
            answer.append([head, '+'.join(rest), isbn, str(data[head]['edition'])])
        answer.sort(key=lambda row: int(row[0].split('-')[1]))
        return answer

    status = Code({'ACTIVE': (['ACTIVE', 'active'], ['सक्रिय']), 'WITHDRAWN': (['WITHDRAWN', 'withdrawn'], ['वापस लिया गया'])})
    action = Code({'SET_ISBN': (['SET_ISBN'], ['आईएसबीएन बदलें']), 'SET_EDITION': (['SET_EDITION'], ['संस्करण बदलें']),
                   'WITHDRAW': (['WITHDRAW'], ['वापस लें'])})
    tables = [
        Table('records', [('accession', 'परिग्रहण संख्या', Id()), ('isbn', 'आईएसबीएन', Text()), ('title', 'शीर्षक', Text()),
                          ('edition', 'संस्करण', EDITION), ('year', 'वर्ष', Int()), ('status', 'स्थिति', status)],
              records, tid),
        Table('amendments', [('seq', 'क्रम', Int()), ('accession', 'परिग्रहण संख्या', Id()), ('action', 'कार्रवाई', action),
                             ('isbn', 'आईएसबीएन', Text()), ('edition', 'संस्करण', EDITION)], file_amends, tid),
    ]
    notice = {
        'en': """Merge duplicate catalogue records for the Hindi literature collection.
1. Apply amendments.csv in ascending seq order (the file is not sorted): SET_ISBN replaces the ISBN, SET_EDITION replaces the edition, and WITHDRAW withdraws the record.
2. Ignore WITHDRAWN records completely: they are never canonical and never listed as merged.
3. Normalize each ISBN: remove the word ISBN, spaces and hyphens. A 13-digit ISBN is valid if its ISBN-13 check digit is correct. A 10-character ISBN is valid if its ISBN-10 check digit is correct (the last character may be X); convert a valid ISBN-10 to ISBN-13 by prefixing 978 to its first nine digits and computing a new ISBN-13 check digit. Anything else, including a blank ISBN, is invalid.
4. Records with a valid ISBN are the same manifestation when they have the same ISBN-13 and the same edition number. A record with an invalid ISBN is never merged and forms a group on its own with isbn13 blank.
5. In each group the canonical record is the record with the lowest accession number (compare the numbers, so ACC-950 is lower than ACC-1203) whose title is in Devanagari script; if no title in the group is in Devanagari, the record with the lowest accession number.
6. Report one row per group: canonical accession, merged (the other accessions in ascending numeric order joined with +, blank if none), isbn13, and edition as a number.""",
        'hi': """हिंदी साहित्य संग्रह के डुप्लिकेट कैटलॉग रिकॉर्ड मिलाएँ।
1. amendments.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है): "आईएसबीएन बदलें" आईएसबीएन बदलता है, "संस्करण बदलें" संस्करण बदलता है, और "वापस लें" रिकॉर्ड को वापस ले लेता है।
2. "वापस लिया गया" रिकॉर्डों को पूरी तरह छोड़ दें: वे न कभी मूल (canonical) होंगे और न merged में लिखे जाएँगे।
3. हर आईएसबीएन को नॉर्मलाइज़ करें: ISBN शब्द, स्पेस और हाइफ़न हटाएँ। 13 अंकों का आईएसबीएन तभी मान्य है जब उसका ISBN-13 जाँच अंक सही हो। 10 अक्षरों का आईएसबीएन तभी मान्य है जब उसका ISBN-10 जाँच अंक सही हो (आख़िरी अक्षर X हो सकता है); मान्य ISBN-10 को ISBN-13 में बदलने के लिए उसके पहले नौ अंकों के आगे 978 लगाएँ और नया ISBN-13 जाँच अंक निकालें। बाकी सब, खाली आईएसबीएन भी, अमान्य है।
4. मान्य आईएसबीएन वाले रिकॉर्ड एक ही प्रकाशन हैं जब उनका ISBN-13 और संस्करण संख्या एक हो। अमान्य आईएसबीएन वाला रिकॉर्ड कभी नहीं मिलाया जाता; वह अकेले अपना समूह बनाता है और उसका isbn13 खाली रहता है।
5. हर समूह में मूल रिकॉर्ड वह है जिसकी परिग्रहण संख्या सबसे छोटी हो (संख्याओं की तुलना करें, इसलिए ACC-950, ACC-1203 से छोटा है) और जिसका शीर्षक देवनागरी लिपि में हो; अगर समूह का कोई शीर्षक देवनागरी में नहीं है, तो सबसे छोटी परिग्रहण संख्या वाला रिकॉर्ड।
6. हर समूह की एक पंक्ति दें: canonical परिग्रहण संख्या, merged (बाकी परिग्रहण संख्याएँ बढ़ते संख्यात्मक क्रम में + से जुड़ी, कोई न हो तो खाली), isbn13, और edition संख्या के रूप में।""",
    }
    return task(
        id=tid, title='Catalogue de-duplication', domain='archives',
        goals={'en': 'Merge the duplicate catalogue records and report one canonical record per manifestation.',
               'hi': 'डुप्लिकेट कैटलॉग रिकॉर्ड मिलाएँ और हर प्रकाशन का एक मूल रिकॉर्ड बताएँ।',
               'hinglish': 'Duplicate catalogue records merge karo aur har manifestation ka ek canonical record batao.'},
        notice=notice, tables=tables, output=['canonical', 'merged', 'isbn13', 'edition'], numeric=['edition'],
        answer=solve(), solve=solve,
        ablations=['amend', 'withdrawn', 'isbn10', 'checksum', 'edition', 'deva', 'lexical'])


ROMAN = ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x', 'xi', 'xii']


def digitization_audit():
    tid = '16-digitization-audit'
    rng = random.Random(tid)
    volumes = [['V1', 6, 34, '12'], ['V2', 9, 30, '8;21'], ['V3', 4, 38, '30']]
    expected = {}
    for volume, front, body, folds in volumes:
        sequence = ROMAN[:front]
        after = {int(x) for x in folds.split(';')}
        for page in range(1, body + 1):
            sequence.append(str(page))
            if page in after:
                sequence.append(f'{page}A')
        expected[volume] = sequence
    scans = []
    for volume, sequence in expected.items():
        for position, label in enumerate(sequence, 1):
            scans.append({'file': f'{volume}_{position:04d}.tif', 'volume': volume, 'position': position,
                          'label': label, 'kind': 'PAGE'})
    pages = [s for s in scans]
    for scan in rng.sample(pages, 6):
        scans.remove(scan)
    for scan in rng.sample([s for s in scans if s['kind'] == 'PAGE'], 5):
        position = scan['position'] + rng.choice([2, 3, 5])
        scans.append({'file': f"{scan['volume']}_{position:04d}b.tif", 'volume': scan['volume'], 'position': position,
                      'label': scan['label'], 'kind': 'PAGE'})
    by_volume = {}
    for scan in scans:
        by_volume.setdefault(scan['volume'], []).append(scan)
    for volume, items in by_volume.items():
        body = [s for s in items if s['label'].isdigit()]
        for _ in range(2):
            a, b = rng.sample(body, 2)
            a['label'], b['label'] = b['label'], a['label']
    rescans = []
    for scan in rng.sample([s for s in scans if s['label'].isdigit()], 4):
        wrong = str(int(scan['label']) + 1)
        replacement = dict(scan, file=scan['file'].replace('.tif', 'r.tif'))
        scan['label'] = wrong
        scans.append(replacement)
        rescans.append([scan['file'], replacement['file']])
    for volume in expected:
        for index in range(2):
            scans.append({'file': f'{volume}_T{index + 1:02d}.tif', 'volume': volume, 'position': None,
                          'label': '', 'kind': rng.choice(['BLANK', 'TARGET'])})
    rng.shuffle(scans)

    def shown(label, style):
        text = label.upper() if style % 4 == 1 and not label.isdigit() else label
        text = text.lower() if style % 4 == 2 else text
        if style % 3 == 0:
            text = text.translate(TO_DEV)
        return text

    for scan in scans:
        scan['shown'] = shown(scan['label'], rng.randrange(1000))
    rows = [[s['file'], s['volume'], s['kind'], s['shown']] for s in scans]

    def solve(off=frozenset()):
        replaced = set() if 'rescans' in off else {old for old, _ in rescans}
        sequences = {}
        for volume, front, body, folds in volumes:
            sequence = ROMAN[:front]
            after = set() if 'foldout' in off else {int(x) for x in folds.split(';')}
            for page in range(1, body + 1):
                sequence.append(str(page))
                if page in after:
                    sequence.append(f'{page}A')
            sequences[volume] = sequence

        def norm(text):
            text = text.strip()
            if 'digits' not in off:
                text = text.translate(str.maketrans('०१२३४५६७८९', '0123456789'))
            return text if 'case' in off else text.casefold()

        answer = []
        for volume, sequence in sequences.items():
            valid = [s for s in scans if s['volume'] == volume and s['kind'] == 'PAGE' and s['file'] not in replaced]
            for position, label in enumerate(sequence, 1):
                found = sorted(s['file'] for s in valid if norm(s['shown']) == norm(label))
                if not found:
                    status = 'MISSING'
                elif len(found) > 1:
                    status = 'DUPLICATE'
                else:
                    match = next(s for s in valid if s['file'] == found[0])
                    status = 'OK' if int(re.search(r'_(\d{4})', match['file'])[1]) == position else 'MISPLACED'
                answer.append([volume, str(position), label.upper() if not label.isdigit() else label, status,
                               '+'.join(found)])
        return answer

    kind = Code({'PAGE': (['PAGE', 'page'], ['पृष्ठ']), 'BLANK': (['BLANK', 'blank'], ['खाली पन्ना']),
                 'TARGET': (['TARGET', 'colour target'], ['रंग पट्टी'])})
    tables = [
        Table('volumes', [('volume', 'खंड', Id()), ('front_matter_pages', 'प्रारंभिक पृष्ठ', Int()),
                          ('body_pages', 'मुख्य पृष्ठ', Int()), ('foldouts_after', 'फ़ोल्डआउट किस पृष्ठ के बाद', Text())],
              volumes, tid),
        Table('scans', [('file', 'फ़ाइल', Id(noisy=False)), ('volume', 'खंड', Id()), ('kind', 'प्रकार', kind),
                        ('observed_label', 'दिखा पृष्ठ अंक', Text())], rows, tid),
        Table('rescans', [('replaced_file', 'बदली गई फ़ाइल', Id(noisy=False)), ('new_file', 'नई फ़ाइल', Id(noisy=False))],
              rescans, tid),
    ]
    notice = {
        'en': """Audit the digitized volumes before they go online.
1. Each volume's expected page sequence is: front matter pages numbered i, ii, iii, ... (lower-case Roman numerals, as many as front_matter_pages), then body pages 1, 2, 3, ... (body_pages). A foldout comes immediately after the body page it follows and is labelled with that page number plus A (a foldout after page 12 is 12A). foldouts_after lists those pages separated by semicolons. Positions are numbered from 1 through the whole expected sequence, front matter included.
2. A scan file name encodes its assigned position: V1_0007.tif, V1_0007b.tif and V1_0007r.tif are all assigned position 7.
3. Ignore BLANK and TARGET scans, and ignore every scan listed as replaced_file in rescans.csv (its new_file replaces it).
4. Compare labels after trimming spaces, ignoring letter case, and treating Devanagari digits as the same as ASCII digits (१२ is 12).
5. For every expected page: MISSING if no scan carries its label; DUPLICATE if more than one scan carries it; otherwise MISPLACED if the one scan is assigned a different position, or OK if the position matches.
6. Report every expected page with volume, position, label (Roman numerals in upper case, foldouts like 12A), status, and scans (the matching scan file names in ascending order joined with +, blank if none).""",
        'hi': """डिजिटाइज़ किए गए खंडों को ऑनलाइन डालने से पहले उनकी जाँच करें।
1. हर खंड के पृष्ठों का अपेक्षित क्रम यह है: पहले प्रारंभिक पृष्ठ i, ii, iii, ... (छोटे रोमन अंक, जितने "प्रारंभिक पृष्ठ" में लिखे हैं), फिर मुख्य पृष्ठ 1, 2, 3, ... ("मुख्य पृष्ठ" जितने)। फ़ोल्डआउट उस मुख्य पृष्ठ के ठीक बाद आता है जिसके बाद वह लगा है, और उसका लेबल उस पृष्ठ संख्या के साथ A होता है (पृष्ठ 12 के बाद का फ़ोल्डआउट 12A है)। "फ़ोल्डआउट किस पृष्ठ के बाद" में ये पृष्ठ अर्धविराम (;) से अलग लिखे हैं। स्थितियाँ (positions) 1 से पूरे अपेक्षित क्रम में गिनी जाती हैं, प्रारंभिक पृष्ठों सहित।
2. स्कैन फ़ाइल का नाम उसकी तय स्थिति बताता है: V1_0007.tif, V1_0007b.tif और V1_0007r.tif तीनों की स्थिति 7 है।
3. "खाली पन्ना" और "रंग पट्टी" वाले स्कैन छोड़ दें, और rescans.csv में "बदली गई फ़ाइल" के रूप में लिखे हर स्कैन को भी छोड़ दें (उसकी जगह "नई फ़ाइल" लेती है)।
4. लेबल मिलाते समय स्पेस हटाएँ, अक्षरों के छोटे-बड़े रूप को नज़रअंदाज़ करें, और देवनागरी अंकों को अंग्रेज़ी अंकों जैसा मानें (१२ यानी 12)।
5. हर अपेक्षित पृष्ठ के लिए: अगर किसी स्कैन पर उसका लेबल न हो तो MISSING; एक से ज़्यादा स्कैन पर हो तो DUPLICATE; वरना अगर उस एक स्कैन की स्थिति अलग है तो MISPLACED, और स्थिति मिलती है तो OK।
6. हर अपेक्षित पृष्ठ की रिपोर्ट दें: volume, position, label (रोमन अंक बड़े अक्षरों में, फ़ोल्डआउट 12A की तरह), status, और scans (मिलने वाली स्कैन फ़ाइलों के नाम बढ़ते क्रम में + से जुड़े, कोई न हो तो खाली)।""",
    }
    return task(
        id=tid, title='Digitization page audit', domain='archives',
        goals={'en': 'Audit every expected page of the digitized volumes against the scan files.',
               'hi': 'डिजिटाइज़ किए गए खंडों के हर अपेक्षित पृष्ठ को स्कैन फ़ाइलों से मिलाकर जाँचें।',
               'hinglish': 'Digitized volumes ke har expected page ko scan files se match karke audit karo.'},
        notice=notice, tables=tables, output=['volume', 'position', 'label', 'status', 'scans'], key_columns=2,
        answer=solve(), solve=solve, ablations=['rescans', 'foldout', 'digits', 'case'])


TASKS = [catalogue_merge, digitization_audit]
