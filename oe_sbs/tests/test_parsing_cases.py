#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression harness for the offer-metadata parsers.

WHY THIS EXISTS
---------------
Every one of these cases comes from a real supplier file that was parsed
WRONGLY at some point. The parsers share regexes and guards, so a fix aimed at
one file has repeatedly broken another: widening the lead-time scan to accept
days made it swallow 'valid for 30 days'; letting 'clean' mean T2 made
'Fresh & Clean' stamp offers T2; requiring a label to start the cell made
'20% T/T in advance' return '(deposit)'.

Run this after ANY change to import_wizard.py:

    python3 oe_sbs/tests/test_parsing_cases.py

It needs no Odoo and no database - it loads the pure functions out of
import_wizard.py by source and exercises them directly. A failure here means a
file that used to import correctly no longer does.
"""
import os
import re
import sys
import calendar
import math
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
WIZARD = os.path.join(HERE, '..', 'wizard', 'import_wizard.py')


def load_namespace():
    """Pull the standalone helpers out of import_wizard.py without importing Odoo."""
    src = open(WIZARD, encoding='utf-8').read()
    ns = {'re': re, 'math': math, 'calendar': calendar, 'date': __import__('datetime').date}

    def grab(pattern, wrap_class=None):
        m = re.search(pattern, src, re.S | re.M)
        if not m:
            raise SystemExit('harness out of date: could not find %r' % pattern)
        code = m.group(0)
        if wrap_class:
            # each grabbed method gets its OWN holder class, otherwise the
            # second one silently replaces the first
            code = 'class %s:\n' % wrap_class + code
        exec(compile(textwrap.dedent(code) if not wrap_class else code,
                     '<wizard>', 'exec'), ns)

    grab(r'    def _mov_to_number\(self.*?(?=\n    @staticmethod\n    def _round_up_to)',
         wrap_class='_MovHolder')
    grab(r'_MONTH_NAMES = \{.*?(?=\ndef standardize_lead_time)')
    grab(r'^FB_NONE\s+=.*?^SCOPE_BOTH.*?$')
    grab(r'DYNAMIC_FIELDS = \{.*?\n\}\n')
    for fn in ('_looks_like_place_name',
               '_normalize', '_looks_like_label', '_inline_value',
               '_norm_country', 'standardize_lead_time', 'standardize_mov',
               '_is_take_all', '_is_monetary', '_looks_like_metadata_statement',
               '_case_per_pallet', '_case_per_layer', 'compute_moq_in_cases'):
        grab(r'def %s\b.*?(?=\ndef |\n@|\nclass |\n_[A-Z])' % fn)
    grab(r'_TAKE_ALL_RE = re\.compile\(.*?(?=\ndef _is_take_all)')
    grab(r'_SHELF_LIFE_HINTS = re\.compile\(.*?(?=\ndef _incoterm_context_ok)')
    grab(r'def _incoterm_context_ok.*?(?=\ndef |\n@)')
    grab(r'_META_KEYWORDS = .*?(?=\ndef _looks_like_metadata_statement)')
    grab(r'    # Wording that means .*?(?=\n    def _take_all_mov)', wrap_class='_W')
    return ns


NS = load_namespace()
W = NS['_W']


class _MOV(NS['_MovHolder']):
    """_mov_to_number needs only _round_up_to, and only when a margin is asked
    for - the harness checks the raw amount, so the stub never runs."""
    @staticmethod
    def _round_up_to(value, step):
        return int(math.ceil(float(value) / step) * step)

    def _get_default_profit_margin(self):
        return 0.0


_MOV = _MOV()
# Read straight from DYNAMIC_FIELDS instead of restating the patterns here:
# a hardcoded copy drifts, and a harness that tests yesterday's regex is
# worse than no harness ('EU + CLEAN' passed in the wizard and failed here).
T1_RE = re.compile(NS['DYNAMIC_FIELDS']['t1']['anchor_pattern'], re.IGNORECASE)
T2_RE = re.compile(NS['DYNAMIC_FIELDS']['t2']['anchor_pattern'], re.IGNORECASE)
E1_RE = re.compile(NS['DYNAMIC_FIELDS']['euro1']['anchor_pattern'], re.IGNORECASE)
LEAD_ANCHOR = re.compile(r'\d+\s*(week|month|day)s?', re.IGNORECASE)

RESULTS = []


def check(group, label, got, expected):
    RESULTS.append((group, label, got, expected, got == expected))


# --------------------------------------------------------------------------
# Lead time.  Files: GBS, ALB, MinMaxDeals, Sia Group, Supernova
# --------------------------------------------------------------------------
def lead_time(cell):
    """The full detection path: context guard first, then standardisation."""
    if not LEAD_ANCHOR.search(cell) or not NS['_lead_time_context_ok'](cell):
        return None
    return NS['standardize_lead_time'](cell)


LEAD_CASES = [
    # (cell, expected)  -- None means "must NOT be read as a lead time"
    ('Lead time: 4-6 weeks',                                    '6 Weeks'),
    ('Lead time: 3-5 weeks',                                    '5 Weeks'),
    ('4-6 Weeks (from receipt of deposit)',                     '6 Weeks'),
    ('l ead time will be 5 to 10 days after the order is confirmed.', '2 Weeks'),
    ('Delivery - 10 DAYS',                                      '2 Weeks'),
    ('Lead Time: 7 Days',                                       '1 Week'),
    ('Delivery in 21 days',                                     '3 Weeks'),
    # shelf life, not delivery  (Sia Group 'Ready Stock')
    ('Fresh & Clean, batch code within 18 months from manufacturing', None),
    # offer validity, not delivery  (Supernova)
    ('This price list is valid for 30 days from issue date.',    None),
    ('Offer Validity 14 days',                                   None),
    # payment terms, not delivery
    ('Payment: net 30 days',                                     None),
]

# --------------------------------------------------------------------------
# Customs status.  Files: Fenty, Beautynet, Sia Group, Beauty Care Global
# --------------------------------------------------------------------------
T_CASES = [
    # (cell, t1, t2, euro1)
    ('T1/T2   EXW NL',                          None, None,        None),
    ('T1/T2',                                   None, None,        None),
    ('T1 or T2',                                None, None,        None),
    ('T1/T2: T2',                               None, 'yes',       None),
    ('T1',                                      'yes', None,       None),
    ('Customs status: T1',                      'yes', None,       None),
    ('ALL GOODS ARE EU CLEAN',                  None, 'yes',       None),
    ('All Goods are Fresh & Clean-Eu.',         None, 'yes',       None),
    ('Goods are not EU cleared',                None, 'no',        None),
    ('T2 - available on request',               None, 'available', None),
    ('EU clearance available on request',       None, 'available', None),
    ('T2: No',                                  None, 'no',        None),
    ('EUR.1 - YES',                             None, None,        'yes'),
    ('EUR1: No',                                None, None,        'no'),
    # product wording must never be read as a customs status  (Sia Group)
    ('Fresh & Clean, batch code within 18 months', None, None,     None),
]

# --------------------------------------------------------------------------
# MOV / MOQ.  Files: Supernova, Rhode, MinMaxDeals, Divine, GBS
# --------------------------------------------------------------------------
# The raw amount a found MOV parses to, BEFORE any margin. Every one of these
# was mis-parsed at some point: '20KUSD' lost its k and became 20.
MOV_NUMBER_CASES = [
    ('20KUSD & ASSORTED ORDER',                       20000.0),
    ('20K USD',                                       20000.0),
    ('EUR 20K & ASSORTED ORDER & DECODE',             20000.0),
    ('20K\u20ac',                                       20000.0),
    ('Mov 20\u20achk'.replace('h', ''),                  20000.0),
    ('\u20ac5,000.00',                                  5000.0),
    ('33.000\u20ac',                                    33000.0),
    ('\u00a33,000',                                     3000.0),
    ('7.000\u20ac/12.000\u20ac',                          7000.0),
]

MONETARY_CASES = [
    ('20KUSD & ASSORTED ORDER', True),
    ('20K USD',                 True),
    ('MOQ 33.000EUR',           True),
    ('5000 units',              False),
    ('10 pallet',               False),
]

TAKE_ALL_CASES = [
    ('MOQ: Take all', True), ('take-all', True), ('Whole lot', True),
    ('MOQ: 20K', False), ('10 pallet', False), ('MOQ 33.000EUR', False),
]

MOQ_CASES = [
    # (number, unit, rows, expected cases)
    (5000, 'unit',   [{'case_size': 6}, {'case_size': 24}], 834),
    (5000, 'unit',   [{'case_size': 12}],                   417),
    (5000, 'unit',   [{'case_size': 0}],                    None),   # -> error
    (10,   'pallet', [{'pallet': 32}, {'pallet': 24}],      320),
    (20,   'case',   [],                                     20),
]

# --------------------------------------------------------------------------
# Metadata sidebar detection.  Files: Rhode, MinMaxDeals, GBS
# --------------------------------------------------------------------------
SIDEBAR_CASES = [
    ('MOQ: Take all', True), ('EXW: Poland', True), ('EXW: Italy', True),
    ('Lead time', False),    # a REAL column header in the GBS file
    ('Price', False), ('Case Size', False), ('Avl. Units', False),
    ('Brand', False), ('Value', False),
]

# --------------------------------------------------------------------------
# Label vs. value.  Files: Supernova, MinMaxDeals, Divine
# --------------------------------------------------------------------------
INLINE_CASES = [
    ('Deposit 20%', 'deposit', '20%'),
    ('MOQ: 5000 units', 'moq', '5000 units'),
    ('Our Moq is 3500', 'moq', '3500'),
    ('MOV: 20KUSD & ASSORTED ORDER', 'mov', '20KUSD & ASSORTED ORDER'),
    ('Payment: Full payment before shipment', 'payment',
     'Full payment before shipment'),
    # keyword mid-sentence -> the whole (short) cell is the value
    ('20% T/T in advance (deposit)', 'advance', '20% T/T in advance (deposit)'),
    # keyword inside a paragraph -> not a value at all
    ('This price list is valid for 30 days from issue date. Inventory subject '
     'to prior sale and availability confirmation.', 'valid', ''),
]


# The incoterm's city slot is filled from LEFTOVER text, not a lookup, so it
# must reject anything that means the parser ran past the place into the next
# statement. Every rejection here comes from a real file.
PLACE_NAME_CASES = [
    ('MOA:',        False),   # Dr lamy: label of the next statement
    ('Total:',      False),
    ('5,000',       False),   # an amount
    ('41-700',      False),   # a postal code
    ('20%',         False),
    ('USD',         False),   # Alfa: currency naming the price column
    ('PCS',         False),
    ('net',         False),
    ('Dortmund',    True),    # Argon
    ('Zvolen',      True),
    ('Rotterdam',   True),
    ('Herkenbosch', True),
    ('Jakarta',     True),
    ('Hamburg',     True),
]


def run():
    for cell, expected in LEAD_CASES:
        check('lead time', cell, lead_time(cell), expected)

    for cell, e1, e2, e3 in T_CASES:
        check('T1', cell, W._resolve_yes_no(cell, T1_RE), e1)
        check('T2', cell, W._resolve_yes_no(cell, T2_RE, allow_available=True), e2)
        check('EUR.1', cell, W._resolve_yes_no(cell, E1_RE), e3)

    for cell, expected in MOV_NUMBER_CASES:
        check('MOV amount', cell, _MOV._mov_to_number(cell), expected)

    for cell, expected in MONETARY_CASES:
        check('is monetary', cell, NS['_is_monetary'](cell), expected)
    for cell, expected in TAKE_ALL_CASES:
        check('take all', cell, NS['_is_take_all'](cell), expected)
    for num, unit, rows, expected in MOQ_CASES:
        check('MOQ -> cases', '%s %s' % (num, unit),
              NS['compute_moq_in_cases'](num, unit, rows), expected)

    for cell, expected in PLACE_NAME_CASES:
        check('city slot', cell, NS['_looks_like_place_name'](cell), expected)

    for cell, expected in SIDEBAR_CASES:
        check('sidebar header', cell,
              NS['_looks_like_metadata_statement'](cell), expected)

    for cell, kw, expected in INLINE_CASES:
        check('inline value', '%s  [%s]' % (cell[:38], kw),
              NS['_inline_value'](cell, kw), expected)

    failures = [r for r in RESULTS if not r[4]]
    width = max(len(r[1]) for r in RESULTS)
    current = None
    order = []
    for r in RESULTS:
        if r[0] not in order:
            order.append(r[0])
    for group, label, got, expected, ok in sorted(
            RESULTS, key=lambda r: order.index(r[0])):
        if group != current:
            print('\n== %s ==' % group)
            current = group
        flag = 'ok  ' if ok else 'FAIL'
        line = '%s %-*s -> %r' % (flag, width, label, got)
        if not ok:
            line += '   EXPECTED %r' % (expected,)
        print(line)

    print('\n%s/%s passed' % (len(RESULTS) - len(failures), len(RESULTS)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(run())
