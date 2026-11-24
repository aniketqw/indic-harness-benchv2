"""Localization: Hindi UI string QA, and Devanagari/Roman product search normalization."""

from collections import Counter
import random
import re
import unicodedata

from .core import Code, Id, Int, Table, Text, task

ZWJ, ZWNJ = '‍', '‌'
DDA = 'ड़'  # precomposed ड़; NFC turns it into ड + nukta

BASE = [
    ('save', 'button', 'Save', 'सहेजें'),
    ('cancel', 'button', 'Cancel', 'रद्द करें'),
    ('pay_now', 'button', 'Pay now', 'अभी भुगतान करें'),
    ('place_order', 'button', 'Place order', 'ऑर्डर करें'),
    ('track', 'button', 'Track delivery', 'डिलीवरी ट्रैक करें'),
    ('tab_account', 'tab', 'Account', 'खाता'),
    ('tab_settings', 'tab', 'Settings', 'सेटिंग्स'),
    ('tab_orders', 'tab', 'Orders', 'ऑर्डर'),
    ('address', 'label', 'Delivery address', 'डिलीवरी का पता'),
    ('method', 'label', 'Payment method', 'भुगतान का तरीका'),
    ('welcome', 'message', 'Hello {name}, welcome back!', 'नमस्ते {name}, आपका फिर से स्वागत है!'),
    ('shipped', 'message', 'Your order {order_id} has shipped.', 'आपका ऑर्डर {order_id} भेज दिया गया है।'),
    ('paid', 'message', 'Payment of ₹{amount} received.', '₹{amount} का भुगतान मिल गया।'),
    ('cart_one', 'plural_one', '{{count}} item in your cart', 'आपके कार्ट में {{count}} आइटम है'),
    ('cart_other', 'plural_other', '{{count}} items in your cart', 'आपके कार्ट में {{count}} आइटम हैं'),
    ('eta', 'message', 'Delivery expected by %s', 'डिलीवरी %s तक अपेक्षित है'),
    ('gift', 'message', '%1$s sent you %2$s', '%1$s ने आपको %2$s भेजा'),
    ('balance', 'message', 'Your account balance is ₹{balance}', 'आपके खाते में ₹{balance} शेष हैं'),
    ('history', 'label', 'Order history', 'ऑर्डर इतिहास'),
    ('reset', 'message', 'Reset your password', 'अपना पासवर्ड रीसेट करें'),
    ('coupon', 'button', 'Apply coupon', 'कूपन लगाएँ'),
    ('unread', 'message', 'You have %d new messages', 'आपके %d नए संदेश हैं'),
    ('account_settings', 'label', 'Account settings', 'खाता सेटिंग्स'),
    ('transit', 'message', 'Delivery to {city} takes {days} days', '{city} तक डिलीवरी में {days} दिन लगते हैं'),
    ('retry', 'button', 'Retry payment', 'भुगतान फिर से करें'),
    ('otp', 'message', 'Hi {name}, your OTP is {otp}', 'नमस्ते {name}, आपका ओटीपी {otp} है'),
    ('tab_help', 'tab', 'Help', 'सहायता'),
    ('logout', 'button', 'Log out', 'लॉग आउट'),
    ('order_cancelled', 'message', 'Order {order_id} cancelled', 'ऑर्डर {order_id} रद्द किया गया'),
    ('add_cart', 'button', 'Add to cart', 'कार्ट में जोड़ें'),
]
GLOSSARY = [('Account', 'खाता', 'अकाउंट'), ('Order', 'ऑर्डर', 'आदेश'), ('Settings', 'सेटिंग्स', 'समायोजन'),
            ('Payment', 'भुगतान', 'पेमेंट'), ('Delivery', 'डिलीवरी', 'वितरण')]
LIMITS = {'button': 18, 'tab': 8}
PLACEHOLDER = re.compile(r'\{\{\w+\}\}|\{\w+\}|%\d+\$[sd]|%[sd]')

# Hand-written faults for the second namespace. Each maps a base key to a broken translation.
FAULTS = {
    'save': 'Save',
    'cancel': '  ',
    'pay_now': 'अभी पेमेंट करें',
    'place_order': 'आदेश दें',
    'track': 'डिलीवरी ट्' + ZWJ + 'रैक करें',
    'tab_account': 'अकाउंट',
    'tab_settings': 'सेटिंग्' + ZWJ + 'स',
    'tab_orders': 'ऑर्डर सूची',
    'address': 'डिलीवरी (वितरण) का पता',
    'welcome': 'नमस्ते {नाम}, आपका फिर से स्वागत है!',
    'shipped': 'आपका ऑर्डर भेज दिया गया है।',
    'paid': '₹{amount} का पेमेंट मिल गया।',
    'cart_one': 'आपके कार्ट में {count} आइटम है',
    'cart_other': 'आपके कार्ट में {{count}} आइटम हैं',
    'eta': 'डिलीवरी %d तक अपेक्षित है',
    'gift': '%2$s आपको %1$s ने भेजा',
    'balance': 'आपके अकाउंट में ₹{balance} शेष हैं',
    'history': 'ऑर्डर इतिहास',
    'reset': 'Reset your password',
    'coupon': 'कृपया यहाँ कूपन कोड लगाएँ',
    'unread': 'आपके %s नए संदेश हैं',
    'account_settings': 'खाता समायोजन',
    'transit': '{city} तक डिलीवरी में {days} {days} दिन लगते हैं',
    'retry': 'पेमेंट फिर से करें',
    'otp': 'नमस्ते {name}, आपका ओटीपी {OTP} है',
    'tab_help': 'मदद केंद्र',
    'logout': 'Log out ',
    'order_cancelled': '{order_id} आदेश रद्द किया गया',
    'add_cart': 'सब कार्ट में जो' + DDA + 'ें',
}


def ui_strings():
    tid = '07-ui-strings'
    rng = random.Random(tid)
    strings = []
    revisions = []
    for space in ('web', 'app'):
        for key, kind, source, good in BASE:
            name = f'{space}.{key}'
            text = good if space == 'web' else FAULTS.get(key, good)
            strings.append([name, kind, source, text, rng.randint(1, 3)])
    # Revision feed: newer fixes, newer regressions, and stale rows that must be ignored.
    by_name = {s[0]: s for s in strings}
    good_of = {key: good for key, _, _, good in BASE}
    for key in ['pay_now', 'tab_account', 'welcome', 'eta', 'reset', 'transit', 'otp']:
        row = by_name[f'app.{key}']
        revisions.append([row[0], row[4] + rng.randint(1, 2), good_of[key]])
    for key in ['shipped', 'coupon', 'logout']:
        # Stale fixes: equal to or older than the strings file, so they must be ignored.
        row = by_name[f'app.{key}']
        revisions.append([row[0], max(1, row[4] - rng.randint(0, 1)), good_of[key]])
    for key, broken in [('method', 'पेमेंट का तरीका'), ('history', 'Order history'), ('logout', 'लॉग  आउट करें अभी तुरंत यहाँ से'),
                        ('tab_help', 'सहायता' + ZWNJ + 'केंद्र')]:
        row = by_name[f'web.{key}']
        revisions.append([row[0], row[4] + 1, broken])
    second = by_name['app.pay_now']
    revisions.append([second[0], second[4] + 5, 'अभी पेमेंट करें'])
    rng.shuffle(revisions)
    glossary = [[en, hi, bad] for en, hi, bad in GLOSSARY]

    def status(kind, source, text, off):
        if not text.strip() or text.strip() == source.strip():
            return 'UNTRANSLATED'
        a, b = PLACEHOLDER.findall(source), PLACEHOLDER.findall(text)
        if (a != b) if 'order' in off else (Counter(a) != Counter(b)):
            return 'PLACEHOLDER'
        checks = []
        for term, required, forbidden in GLOSSARY:
            present = term in source if 'case' in off else term.casefold() in source.casefold()
            if present:
                bad = required not in text or (forbidden in text and 'forbidden' not in off)
                checks.append(bad)
        long = False
        if kind in LIMITS:
            measured = text if 'nfc' in off else unicodedata.normalize('NFC', text)
            if 'zwj' in off:
                measured = measured.replace(ZWJ, '').replace(ZWNJ, '')
            long = len(measured) > LIMITS[kind]
        if 'priority' in off and long:
            return 'TOO_LONG'
        if any(checks):
            return 'GLOSSARY'
        return 'TOO_LONG' if long else 'OK'

    def solve(off=frozenset()):
        answer = []
        latest = {}
        for key, revision, text in revisions:
            if 'revisions' in off:
                continue
            if 'revision_any' in off or revision > by_name[key][4]:
                if key not in latest or revision > latest[key][0] or 'revision_any' in off:
                    latest[key] = (revision, text)
        for name, kind, source, text, revision in strings:
            if name in latest:
                revision, text = latest[name]
            answer.append([name, str(revision), status(kind, source, text, off)])
        return answer

    kind = Code({'button': (['button'], ['बटन']), 'tab': (['tab'], ['टैब']), 'label': (['label'], ['लेबल']),
                 'message': (['message'], ['संदेश']), 'plural_one': (['plural_one'], ['एकवचन']),
                 'plural_other': (['plural_other'], ['बहुवचन'])})
    tables = [
        Table('strings', [('key', 'कुंजी', Id(noisy=False)), ('kind', 'प्रकार', kind), ('source_en', 'अंग्रेज़ी स्रोत', Text()),
                          ('hindi', 'हिंदी अनुवाद', Text()), ('revision', 'संशोधन', Int(devanagari=False))], strings, tid),
        Table('revisions', [('key', 'कुंजी', Id(noisy=False)), ('revision', 'संशोधन', Int(devanagari=False)),
                            ('hindi', 'हिंदी अनुवाद', Text())], revisions, tid),
        Table('glossary', [('term_en', 'अंग्रेज़ी शब्द', Text()), ('required_hi', 'अनिवार्य हिंदी', Text()),
                           ('forbidden_hi', 'वर्जित हिंदी', Text())], glossary, tid),
    ]
    notice = {
        'en': f"""QA the Hindi translations before the app release.
1. Use the translation with the highest revision number for each key: revisions.csv overrides strings.csv only when its revision is higher than the one in strings.csv. If revisions.csv has several rows for a key, the highest revision wins. Report the revision you used.
2. Give each key exactly one status, checking in this order and stopping at the first that applies:
   UNTRANSLATED - the translation is empty or only spaces, or (ignoring leading and trailing spaces) exactly equals the English source.
   PLACEHOLDER - the placeholders differ. Placeholders are {{name}}-style tokens, {{{{count}}}}-style tokens, %s, %d and numbered tokens such as %1$s. Compare them as a multiset: order does not matter, but every token must appear the same number of times with exactly the same text.
   GLOSSARY - the English source contains a glossary term (case-insensitive; "Orders" contains "Order") and the translation either lacks the required Hindi term or contains the forbidden Hindi term.
   TOO_LONG - a button longer than {LIMITS['button']} characters or a tab longer than {LIMITS['tab']} characters. Count Unicode code points after NFC normalization, including invisible joiners (U+200C, U+200D) and spaces. Labels, messages and plurals have no limit.
   OK - none of the above.""",
        'hi': f"""ऐप रिलीज़ से पहले हिंदी अनुवादों की जाँच करें।
1. हर कुंजी के लिए सबसे बड़े संशोधन (revision) नंबर वाला अनुवाद लें: revisions.csv तभी strings.csv की जगह लेगा जब उसका संशोधन नंबर strings.csv वाले नंबर से बड़ा हो। अगर revisions.csv में एक कुंजी की कई पंक्तियाँ हों, तो सबसे बड़ा संशोधन मान्य है। इस्तेमाल किया गया संशोधन नंबर लिखें।
2. हर कुंजी को ठीक एक status दें। इसी क्रम में जाँचें और जो पहली शर्त लागू हो, वहीं रुकें:
   UNTRANSLATED - अनुवाद खाली है या सिर्फ़ स्पेस है, या (शुरू और आख़िर के स्पेस छोड़कर) बिल्कुल अंग्रेज़ी स्रोत जैसा है।
   PLACEHOLDER - प्लेसहोल्डर अलग हैं। प्लेसहोल्डर ये हैं: {{name}} जैसे टोकन, {{{{count}}}} जैसे टोकन, %s, %d और %1$s जैसे क्रमांकित टोकन। इन्हें मल्टीसेट की तरह मिलाएँ: क्रम मायने नहीं रखता, पर हर टोकन उतनी ही बार और बिल्कुल उसी लिखावट में आना चाहिए।
   GLOSSARY - अंग्रेज़ी स्रोत में शब्दावली का कोई शब्द है (छोटे-बड़े अक्षर का फ़र्क नहीं; "Orders" में "Order" शामिल है) और अनुवाद में अनिवार्य हिंदी शब्द नहीं है या वर्जित हिंदी शब्द मौजूद है।
   TOO_LONG - {LIMITS['button']} अक्षरों से लंबा बटन या {LIMITS['tab']} अक्षरों से लंबा टैब। NFC नॉर्मलाइज़ेशन के बाद यूनिकोड कोड पॉइंट गिनें, जिनमें अदृश्य जोड़क (U+200C, U+200D) और स्पेस भी शामिल हैं। लेबल, संदेश और बहुवचन रूपों की कोई सीमा नहीं है।
   OK - ऊपर में से कुछ भी नहीं।""",
    }
    return task(
        id=tid, title='Hindi UI string QA', domain='localization',
        goals={'en': 'Check every Hindi UI string for release and report its status.',
               'hi': 'रिलीज़ के लिए हर हिंदी यूआई स्ट्रिंग की जाँच करें और उसका status बताएँ।',
               'hinglish': 'Release ke liye har Hindi UI string check karo aur uska status batao.'},
        notice=notice, tables=tables, output=['key', 'revision', 'status'], numeric=['revision'],
        answer=solve(), solve=solve,
        ablations=['revisions', 'revision_any', 'order', 'case', 'forbidden', 'nfc', 'zwj', 'priority'])


CATALOG = [
    ('चना दाल', 'chana dal; channa daal'), ('मूँग दाल', 'moong dal; mung dal'),
    ('अरहर दाल', 'arhar dal; toor dal; tur dal'), ('मसूर दाल', 'masoor dal; masur dal'),
    ('उड़द दाल', 'urad dal'), ('ज़ीरा', 'jeera; zeera; cumin'), ('हल्दी', 'haldi; turmeric'),
    ('धनिया', 'dhaniya; coriander'), ('गुड़', 'gud; jaggery; gur'), ('शक्कर', 'shakkar; sugar'),
    ('चीनी', 'cheeni; sugar'), ('आटा', 'atta; wheat flour'), ('मैदा', 'maida; refined flour'),
    ('बेसन', 'besan; gram flour'), ('सूजी', 'sooji; suji; rava'), ('पोहा', 'poha; flattened rice'),
    ('साबूदाना', 'sabudana; sago'), ('इलायची', 'elaichi; cardamom'), ('लौंग', 'laung; clove'),
    ('दालचीनी', 'dalchini; cinnamon'), ('काली मिर्च', 'kali mirch; black pepper'),
    ('लाल मिर्च', 'lal mirch; red chilli'), ('सरसों का तेल', 'sarson ka tel; mustard oil'),
    ('मूँगफली', 'moongphali; peanuts; groundnut'), ('बादाम', 'badam; almonds'), ('किशमिश', 'kishmish; raisins'),
    ('अजवाइन', 'ajwain; carom seeds'), ('हींग', 'hing; asafoetida'), ('सौंफ़', 'saunf; fennel'),
    ('मेथी', 'methi; fenugreek'), ('राजमा', 'rajma; kidney beans'), ('छोले', 'chhole; chole; chickpeas'),
    ('खड़ा मसाला', 'khada masala; whole spices'), ('गरम मसाला', 'garam masala'), ('नमक', 'namak; salt'),
    ('घी', 'ghee'), ('पनीर', 'paneer; cottage cheese'), ('दही', 'dahi; curd; yogurt'), ('चावल', 'chawal; rice'),
    ('बासमती चावल', 'basmati chawal; basmati rice'), ('बासमती चावल 1121', 'basmati 1121; 1121 basmati'),
]


def normalize(text, off=frozenset()):
    text = unicodedata.normalize('NFC', text)
    if 'zwj' not in off:
        text = text.replace(ZWJ, '').replace(ZWNJ, '')
    if 'nukta' not in off:
        text = text.replace('़', '')
    if 'chandrabindu' not in off:
        text = text.replace('ँ', 'ं')
    if 'digits' not in off:
        text = text.translate(str.maketrans('०१२३४५६७८९', '0123456789'))
    if 'case' not in off:
        text = text.casefold()
    if 'diacritics' not in off:
        text = unicodedata.normalize('NFC', ''.join(
            ch for ch in unicodedata.normalize('NFD', text) if not 0x300 <= ord(ch) <= 0x36f))
    if 'hyphen' not in off:
        text = text.replace('-', ' ')
    if 'space' not in off:
        text = ' '.join(text.split())
    return text


def search_normalization():
    tid = '08-search-normalization'
    rng = random.Random(tid)
    catalog = [[f'P{i + 1:02d}', name, aliases, 'ACTIVE'] for i, (name, aliases) in enumerate(CATALOG)]
    catalog[33][3] = 'DISCONTINUED'
    amendments = [['P09', 'REMOVE_ALIAS', 'gur'], ['P14', 'ADD_ALIAS', 'chickpea flour'],
                  ['P36', 'DISCONTINUE', None], ['P34', 'REACTIVATE', None], ['P02', 'ADD_ALIAS', 'green gram'],
                  ['P15', 'REMOVE_ALIAS', 'rava'], ['P15', 'ADD_ALIAS', 'rava'], ['P22', 'DISCONTINUE', None]]
    amendments = [[seq, *row] for seq, row in enumerate(amendments, 1)]
    file_amends = amendments[:]
    rng.shuffle(file_amends)
    queries = [
        'हल्‍दी', 'हल्‌दी', 'हल्दी', 'जीरा', 'ज़ीरा', 'ज़ीरा', 'मूंग दाल', 'मूँग  दाल', 'मूंगदाल',
        'उडद दाल', 'उड़द दाल', 'गुड', 'गुड़', 'gur', 'Gud', 'JAGGERY', 'Jeera', 'zeera ', 'chana-dal',
        'Chana Dal', 'chana', 'channa daal', 'mūng dal', 'haldī', 'jīra', 'sugar', 'Sugar', 'cheeni', 'शक्कर',
        'चीनी', 'बासमती चावल ११२१', 'बासमती चावल 1121', 'basmati-1121', '1121 Basmati', 'basmati', 'बासमती चावल',
        'chickpea flour', 'besan', 'gram  flour', 'rava', 'Rava', 'sooji', 'सूजी', 'garam masala', 'गरम मसाला',
        'ghee', 'घी', 'Lal Mirch', 'लाल मिर्च', 'red chilli', 'red chili', 'मूँगफली', 'मूंगफली', 'moongphali',
        'groundnut', 'green gram', 'सौंफ', 'सौंफ़', 'saunf', 'सौंफ़‍', 'खडा मसाला', 'खड़ा मसाला', 'khada-masala',
        'kali  mirch', 'काली मिर्च', 'black-pepper', 'Black Pepper', 'हींग', 'हिंग', 'hing', 'asafoetida',
        'सरसों का तेल', 'सरसो का तेल', 'sarson-ka-tel', 'mustard oil', 'Mustard Oil', 'दही', 'dahi', 'Curd',
        'yoghurt', 'राजमा', 'rajma', 'Rājmā', 'छोले', 'chhole', 'chole', 'Chickpeas', 'पोहा', 'Poha', 'poha ',
        'साबूदाना', 'sabudana', 'sāgo', 'cardamom', 'इलायची', 'इलाइची', 'clove', 'लौंग', 'लोंग', 'दालचीनी',
        'दाल चीनी', 'cinnamon', 'Methi', 'मेथी', 'paneer', 'पनीर', 'cottage-cheese', 'chawal', 'चावल', 'Rice',
        'basmati rice', 'आटा', 'atta', 'Wheat Flour', 'मैदा', 'maida', 'बेसन', 'नमक', 'salt', 'अरहर दाल', 'toor-dal',
        'Tur Dal', 'मसूर दाल', 'masoor dal', 'मसूर  दाल', 'urad dal', 'Urad-Dal', 'अजवाइन', 'ajwain', 'carom seeds',
        'बादाम', 'Badam', 'almond', 'किशमिश', 'kishmish', 'धनिया', 'dhaniya', 'Coriander',
    ]
    query_rows = [[f'Q{i + 1:03d}', q] for i, q in enumerate(queries)]

    def solve(off=frozenset()):
        entries = {c[0]: {'name': c[1], 'aliases': [a.strip() for a in c[2].split(';')], 'status': c[3]}
                   for c in catalog}
        if 'amend' not in off:
            for _, key, act, alias in sorted(file_amends):
                if act == 'ADD_ALIAS':
                    entries[key]['aliases'].append(alias)
                elif act == 'REMOVE_ALIAS':
                    entries[key]['aliases'] = [a for a in entries[key]['aliases'] if a != alias]
                elif act == 'DISCONTINUE':
                    entries[key]['status'] = 'DISCONTINUED'
                else:
                    entries[key]['status'] = 'ACTIVE'
        index = {}
        for key, item in entries.items():
            if item['status'] != 'ACTIVE' and 'status' not in off:
                continue
            for form in [item['name'], *item['aliases']]:
                index.setdefault(normalize(form, off), set()).add(key)
        answer = []
        for qid, text in query_rows:
            found = sorted(index.get(normalize(text, off), set()))
            if 'multi' in off:
                found = found[:1]
            answer.append([qid, '+'.join(found) or 'NONE'])
        return answer

    status = Code({'ACTIVE': (['ACTIVE', 'active'], ['सक्रिय']), 'DISCONTINUED': (['DISCONTINUED'], ['बंद'])})
    action = Code({'ADD_ALIAS': (['ADD_ALIAS'], ['उपनाम जोड़ें']), 'REMOVE_ALIAS': (['REMOVE_ALIAS'], ['उपनाम हटाएँ']),
                   'DISCONTINUE': (['DISCONTINUE'], ['बंद करें']), 'REACTIVATE': (['REACTIVATE'], ['फिर से चालू करें'])})
    tables = [
        Table('catalog', [('product', 'उत्पाद', Id(noisy=False)), ('display_name', 'प्रदर्शित नाम', Text()),
                          ('aliases', 'उपनाम', Text()), ('status', 'स्थिति', status)], catalog, tid),
        Table('amendments', [('seq', 'क्रम', Int()), ('product', 'उत्पाद', Id()), ('action', 'कार्रवाई', action),
                             ('alias', 'उपनाम', Text())], file_amends, tid),
        Table('queries', [('query', 'खोज', Id(noisy=False)), ('text', 'खोज शब्द', Text())], query_rows, tid),
    ]
    notice = {
        'en': """Resolve customer search queries to grocery products.
1. Apply amendments.csv in ascending seq order (the file is not sorted): ADD_ALIAS adds an alias, REMOVE_ALIAS removes that exact alias, DISCONTINUE sets the product to DISCONTINUED, and REACTIVATE sets it back to ACTIVE.
2. Only ACTIVE products can match. aliases holds several aliases separated by semicolons.
3. Normalize every query, display name and alias the same way: apply Unicode NFC; delete zero-width joiners and non-joiners (U+200D, U+200C); delete the nukta sign U+093C, including the nukta inside letters such as ज़ and ड़ (they become ज and ड); replace chandrabindu (ँ) with anusvara (ं); convert Devanagari digits to ASCII digits; convert letters to lower case; remove accent marks from Latin letters (ā becomes a); replace hyphens with spaces; collapse runs of spaces into one space and trim the ends. Make no other changes: no spelling correction, no partial or prefix matches, and no transliteration between scripts.
4. A query matches a product when its normalized text equals the normalized display name or one of its normalized aliases.
5. Report every query: matches lists all matching product IDs in ascending order joined with +, or NONE.""",
        'hi': """ग्राहकों की खोज को किराना उत्पादों से मिलाएँ।
1. amendments.csv को क्रम (seq) के बढ़ते क्रम में लागू करें (फ़ाइल क्रमबद्ध नहीं है): "उपनाम जोड़ें" एक उपनाम जोड़ता है, "उपनाम हटाएँ" बिल्कुल वही उपनाम हटाता है, "बंद करें" उत्पाद की स्थिति बंद करता है, और "फिर से चालू करें" उसे फिर सक्रिय करता है।
2. सिर्फ़ सक्रिय उत्पाद मिलान में आ सकते हैं। उपनाम कॉलम में कई उपनाम अर्धविराम (;) से अलग किए गए हैं।
3. हर खोज, प्रदर्शित नाम और उपनाम को एक ही तरह नॉर्मलाइज़ करें: यूनिकोड NFC लागू करें; शून्य-चौड़ाई वाले जोड़क और अजोड़क (U+200D, U+200C) हटाएँ; नुक़्ता चिह्न U+093C हटाएँ, ज़ और ड़ जैसे अक्षरों के अंदर का नुक़्ता भी (वे ज और ड बन जाते हैं); चंद्रबिंदु (ँ) की जगह अनुस्वार (ं) लिखें; देवनागरी अंकों को अंग्रेज़ी अंकों में बदलें; अक्षरों को छोटे (lower case) करें; लैटिन अक्षरों से उच्चारण चिह्न हटाएँ (ā को a); हाइफ़न की जगह स्पेस लिखें; लगातार कई स्पेस को एक स्पेस करें और दोनों सिरों से स्पेस हटाएँ। इसके अलावा कोई बदलाव न करें: न वर्तनी सुधार, न आंशिक या शुरुआती हिस्से से मिलान, और न एक लिपि से दूसरी लिपि में लिप्यंतरण।
4. खोज किसी उत्पाद से तब मिलती है जब उसका नॉर्मलाइज़ किया गया पाठ उस उत्पाद के नॉर्मलाइज़ किए गए प्रदर्शित नाम या किसी नॉर्मलाइज़ किए गए उपनाम के बराबर हो।
5. हर खोज की रिपोर्ट दें: matches में मिलने वाले सभी उत्पाद आईडी बढ़ते क्रम में + से जोड़कर लिखें, या NONE।""",
    }
    return task(
        id=tid, title='Grocery search normalization', domain='localization',
        goals={'en': 'Resolve every customer search query to the matching grocery products.',
               'hi': 'ग्राहकों की हर खोज को मिलते-जुलते किराना उत्पादों से जोड़ें।',
               'hinglish': 'Har customer search query ko matching grocery products se resolve karo.'},
        notice=notice, tables=tables, output=['query', 'matches'], answer=solve(), solve=solve,
        ablations=['amend', 'status', 'zwj', 'nukta', 'chandrabindu', 'digits', 'case', 'diacritics', 'hyphen',
                   'space', 'multi'])


TASKS = [ui_strings, search_normalization]
