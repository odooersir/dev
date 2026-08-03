from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
from io import BytesIO
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import calendar
import math
import re
from openpyxl import load_workbook, Workbook
from unidecode import unidecode
import io
import zipfile

import json
import logging

_logger = logging.getLogger(__name__)


def _looks_like_xls(file_content):
    """Old .xls (BIFF) files start with the OLE2 magic header D0 CF 11 E0."""
    return bool(file_content) and file_content[:4] == b'\xd0\xcf\x11\xe0'


def _xls_to_xlsx_bytes(xls_bytes):
    """
    Convert legacy .xls (Excel 97-2003) bytes to .xlsx bytes in memory,
    so the rest of the pipeline (openpyxl, splitting, mapping) is unchanged.
    Preserves all sheets and converts xlrd date cells to datetime.
    """
    try:
        import xlrd
    except ImportError:
        raise UserError(_(
            "Reading legacy .xls files requires the 'xlrd' Python package, "
            "which is not installed on the server. Ask your administrator to run "
            "'pip install xlrd', or re-save the file as .xlsx."))
    book = xlrd.open_workbook(file_contents=xls_bytes)
    wb = Workbook()
    wb.remove(wb.active)                       # drop the default empty sheet
    for sheet_name in book.sheet_names():
        xs = book.sheet_by_name(sheet_name)
        ws = wb.create_sheet(title=str(sheet_name)[:31])   # Excel name max 31 chars
        for r in range(xs.nrows):
            for c in range(xs.ncols):
                cell = xs.cell(r, c)
                value = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        value = xlrd.xldate_as_datetime(value, book.datemode)
                    except Exception:
                        pass
                ws.cell(row=r + 1, column=c + 1, value=value)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ─────────────────────────────────────────────────────────────
# Fallback types
# ─────────────────────────────────────────────────────────────
FB_NONE      = 'none'         # leave empty
FB_TEXT      = 'fixed_text'   # fixed text
FB_WEEKS     = 'fixed_weeks'  # number of weeks
FB_COMPUTED  = 'computed'     # computed (MOV)
FB_TRANSLATE = 'translate'    # translate (CoO)
FB_ACTION    = 'action'       # action with side-effect (Incoterms)

# Field scope
SCOPE_OFFER   = 'offer'       # single value for the whole list
SCOPE_PRODUCT = 'product'     # per-row value
SCOPE_BOTH    = 'both'        # per-row first, else offer-level


# ─────────────────────────────────────────────────────────────
# Central map of dynamic fields
# ─────────────────────────────────────────────────────────────
DYNAMIC_FIELDS = {

    'mov': {
        'odoo_field': 'mov',
        'scope':      SCOPE_OFFER,
        'keywords':   ['mov', 'minimum order value', 'min order value',
                       'min order val', 'minimum order', 'moa',
                       # 'order value' is the common core - it also catches
                       # labels like 'Min / Max Order Value' where the words are
                       # split by a slash. Keep it AFTER the longer keys so the
                       # more specific ones win when both match.
                       'order value', 'order amount', 'order val',
                       # 'min' alone is common shorthand ('MIN 15 K').
                       # _looks_like_label requires it to START the cell, and
                       # any longer keyword beats it, so 'Min order qty 500
                       # cases' still resolves to MOQ rather than MOV.
                       'min', 'min.'],
        # symbol+number, number+k, OR a bare number (e.g. "MOV 75000"): the
        # value sits next to an explicit MOV label, so a plain integer is valid.
        # Allow spaces INSIDE the number ('8 000') and word currencies (EUR/USD).
        'pattern':    r'((?:€|\$|£|aed|eur|usd|gbp)?\s*[\d][\d.,\s]*\d\s*k?|[\d]+\s*k?)',
        # anchor-free: catch a MONETARY minimum buried in a sentence, e.g.
        # "Our Moq is €.3500.-", "MOV: $10,000", or "MOQ: 8 000 EUR". A currency
        # (symbol OR word) near the number means it's a value (MOV).
        'anchor_pattern': r'\b(?:mov|moq|moa|minimum\s+order)\b[^0-9€$£]*?'
                          r'((?:€|\$|£|aed)\s*\.?\s*[\d][\d.,\s]*\d\s*k?'
                          r'|[\d][\d.,\s]*\d\s*(?:€|\$|£|aed|eur|usd|gbp)'
                          r'|[\d][\d.,\s]*\d\s*k)',
        'anchor_free': True,
        'anchor_mov':  True,
        'fixed_field': 'mov_fixed',
        'fallback':   FB_COMPUTED,
        'fallback_value': '5k',
    },

    'moq': {
        'odoo_field': 'moq',
        'scope':      SCOPE_OFFER,
        'keywords':   ['moq', 'minimum order quantity', 'min order qty',
                       'min order quantity', 'minimum qty', 'min qty'],
        # 'Take all' is a perfectly valid MOQ answer, not a number.
        # Rejecting it made the label fall through to whatever cell sat
        # BELOW it - the payment terms line - and the import then died
        # trying to turn 'Terms of payment: 20% deposit...' into cartons.
        'pattern':    r'\d+\s*(pallet|case|carton|unit|pcs|box|ctn)?'
                      r'|take\s*-?\s*all|all\s+stock|whole\s+(?:lot|stock)',
        # anchor-free: catch 'MOQ 10 pallets' buried inside a long sentence,
        # but require the MOQ keyword + a number + a unit so it can't grab
        # random numbers (e.g. incoterm text). Keeps the captured quantity only.
        'anchor_pattern': r'\bmoq\b\s*[:\-]?\s*\d+\s*'
                          r'(?:plt|pallets?|cases?|cartons?|ctn|units?|pcs|box(?:es)?)',
        'fixed_field': 'moq_fixed',
        'fallback':   FB_NONE,
        'fallback_value': None,
        'anchor_free': True,
        'anchor_moq':  True,
    },

    'payment_term': {
        'odoo_field': 'payment_term',
        'scope':      SCOPE_OFFER,
        # 'deposit' / 'prepayment' name the payment term just as clearly as
        # 'payment' does. Without them a cell reading only 'Deposit 20%' matched
        # no field at all and fell through to the offer note.
        'keywords':   ['payment', 'payment terms', 'payment term',
                       'payment advance', 'terms of payment', 'pmt', 'advance',
                       'deposit', 'down payment', 'prepayment', 'pre-payment'],
        'pattern':    r'(net\s*\d+|\d+\s*days?|deposit|advance|t/?t|l/?c|\d+\s*%|before|loading|confirmation)',
        'fixed_field': 'payment_terms_fixed',
        'fallback':   FB_TEXT,
        'fallback_value': '30% Deposit, Balance before shipping',
    },

    'offer_validity': {
        'odoo_field': 'end_date',
        'scope':      SCOPE_OFFER,
        'keywords':   ['offer validity', 'validity', 'valid until',
                       'offer valid', 'expiry', 'expiration', 'valid'],
        'pattern':    r'(\d+\s*(day|week|month)s?|valid|until)',
        'fixed_field': 'offer_validity_fixed',
        'fallback':   FB_WEEKS,
        'fallback_value': 4,
    },

    'coo': {
        'odoo_field': 'coo',
        'scope':      SCOPE_BOTH,
        'keywords':   ['coo', 'country of origin', 'origin', 'made in', 'c.o.o'],
        'pattern':    None,
        'fixed_field': 'coo_fixed',
        'fallback':   FB_TRANSLATE,
        'fallback_value': None,
        'keep_col':   True,
    },

    'incoterms': {
        'odoo_field': 'incoterms',
        'scope':      SCOPE_OFFER,
        'keywords':   ['incoterms', 'incoterm', 'delivery terms',
                       'trade terms', 'shipping terms',
                       # bare incoterm codes used as a row label (value sits in
                       # the adjacent cell, e.g. B7='EXW' / C7='Spain')
                       'exw', 'fca', 'fob', 'cif', 'cfr', 'cpt', 'cip',
                       'dap', 'dpu', 'ddp', 'fas', 'ex works'],
        'pattern':    r'\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP|'
                      r'ex[\s\-]?works|free on board|cost insurance freight)\b',
        'fixed_field': 'incoterm_id',
        'fallback':   FB_ACTION,
        'fallback_value': 'email_supplier',
        'anchor_free': True,
        'anchor_incoterm': True,
        'label_is_incoterm': True,   # when the LABEL is the code, adjacent cell is the place
    },

    'lead_time': {
        'odoo_field': 'lead_time',
        'scope':      SCOPE_BOTH,
        'keywords':   ['lead time', 'leadtime', 'delivery time',
                       'production time', 'eta',
                       # suppliers often phrase lead time as loading/shipping/
                       # dispatch time, e.g. 'Loading time - 7-10 days after...'
                       'loading time', 'shipping time', 'dispatch time',
                       'delivery lead time', 'delivery term time',
                       # a bare 'Delivery:' label is very common and its value
                       # is often a MONTH ('Delivery: October') rather than a
                       # duration - see standardize_lead_time
                       'delivery'],
        # a duration OR a month name; the month form is measured to the end of
        # that month, so 'October' is as much a lead time as '6 weeks' is
        # a duration, a bare range ('ETA 4/5' = 4-5 weeks), or a month name;
        # standardize_lead_time decides which and guards each form
        'pattern':    r'\d+\s*(day|week|month)s?|\d{1,2}\s*[/\-\u2013]\s*\d{1,2}'
                      r'|\b(jan|feb|mar|apr|may|jun|jul|'
                      r'aug|sep|oct|nov|dec)[a-z]*\b',
        # anchor-free only matches weeks/months to avoid '2days' hidden in URLs
        # Days count too: 'lead time will be 5 to 10 days after the order is
        # confirmed' never reached standardize_lead_time (which handles days
        # fine) because this scan only looked for weeks and months, so the offer
        # fell back to the default. _lead_time_context_ok keeps the day form
        # from swallowing payment terms ('net 30 days') and offer validity
        # ('valid for 30 days from issue date').
        'anchor_pattern': r'\d+\s*(week|month|day)s?',
        'fixed_field': 'lead_time_fixed',
        'fallback':   FB_TEXT,
        'fallback_value': '4 Weeks',
        'anchor_free': True,
        'anchor_full_cell': True,
        # Stage B must skip shelf-life cells (see _lead_time_context_ok)
        'anchor_lead_time': True,
        'keep_col':   True,
    },

    # Customs status, three independent facts. They are OFFER-level: in every
    # supplier file seen so far the status is a sentence beside or under the
    # table, never a per-product column. Each keeps the WHOLE cell so the
    # resolver can read the wording ('Yes', 'on request', 'EU Clean') itself
    # rather than the scanner guessing from a token.
    't1': {
        'odoo_field': 't1',
        'scope':      SCOPE_OFFER,
        'keywords':   ['t1', 't1/t2', 't1-t2', 'customs status'],
        'pattern':    r'\bT1\b',
        'anchor_pattern': r'\bT1\b',
        'anchor_full_cell': True,
        'fixed_field': 't1_fixed',
        'fallback':   FB_NONE,
        'fallback_value': None,
        'anchor_free': True,
    },

    't2': {
        'odoo_field': 't2',
        'scope':      SCOPE_OFFER,
        'keywords':   ['t2', 't1/t2', 't1-t2', 'customs status', 'eu clean',
                       'clean eu', 'eu cleared'],
        'pattern':    r'\bT2\b|clean(?:ed)?',
        'anchor_pattern': r'\bT2\b|eu[\s\-+/]*(?:clean(?:ed)?|clear(?:ed|ance)?)|clean(?:ed)?[\s\-+/]*eu',
        'anchor_full_cell': True,
        'fixed_field': 't2_fixed',
        'fallback':   FB_NONE,
        'fallback_value': None,
        'anchor_free': True,
    },

    'euro1': {
        'odoo_field': 'euro1',
        'scope':      SCOPE_OFFER,
        'keywords':   ['eur1', 'eur.1', 'eur 1', 'euro1', 'euro 1',
                       'movement certificate', 'preference certificate'],
        'pattern':    r'eur\.?\s*1|euro\s*1',
        'anchor_pattern': r'\beur\.?\s*1\b|\beuro\s*1\b',
        'anchor_full_cell': True,
        'fixed_field': 'euro1_fixed',
        'fallback':   FB_NONE,
        'fallback_value': None,
        'anchor_free': True,
    },

    'currency': {
        'odoo_field': 'currency_id',
        'scope':      SCOPE_OFFER,
        # explicit currency labels are preferred over a bare symbol elsewhere
        'keywords':   ['currency', 'prices in', 'price in', 'all prices', 'price'],
        'pattern':    r'(€|\$|£|aed|eur|usd|gbp|euro|dollar|pound|dirham)',
        'fixed_field': None,
        'fallback':   FB_NONE,
        'fallback_value': None,
    },
}


# ─────────────────────────────────────────────────────────────
# Column conversion helpers
# ─────────────────────────────────────────────────────────────
def col_letter_to_index(col_str):
    """A->0, B->1, C->2, AA->26 (0-based). Ignores any digits."""
    col_str = ''.join(ch for ch in str(col_str).strip().upper() if ch.isalpha())
    if not col_str:
        return None
    result = 0
    for ch in col_str:
        result = result * 26 + (ord(ch) - ord('A') + 1)
    return result - 1


def index_to_col_letter(idx):
    """Inverse of col_letter_to_index: 0->A, 25->Z, 26->AA"""
    result = ''
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def parse_cell_reference(cell_ref):
    """Convert an address (e.g. A3) to (col_index, row_number); col_index is 0-based."""
    if not cell_ref:
        return None, None
    match = re.match(r"([A-Z]+)(\d+)", str(cell_ref).strip().upper())
    if not match:
        return None, None
    col_str, row_str = match.groups()
    col_idx = 0
    for char in col_str:
        col_idx = col_idx * 26 + (ord(char) - ord('A') + 1)
    return col_idx - 1, int(row_str)


# ─────────────────────────────────────────────────────────────
# Metadata-region extraction
# ─────────────────────────────────────────────────────────────
def extract_metadata_cells(sheet_data, template, ai_scan_mode='outside'):
    """
    Return non-empty cells located outside the data table.
    Output: [{'row': r(1-based), 'col': c(0-based), 'addr': 'B2', 'value': str}, ...]
    """
    if not sheet_data:
        return []

    header_row = int(getattr(template, 'header_row', 1) or 1)
    header_row_idx = header_row - 1

    mapped_cols = set()
    for fname in template._fields:
        if fname.endswith('_col'):
            v = getattr(template, fname, None)
            if v:
                ci = col_letter_to_index(v)
                if ci is not None:
                    mapped_cols.add(ci)

    min_col = min(mapped_cols) if mapped_cols else 0
    max_col = max(mapped_cols) if mapped_cols else 0

    # Which COLUMNS belong to the table? Using only the min..max span of the
    # MAPPED columns was wrong: a column inside the table that we simply don't
    # map (a second product-name column, a stock column, a line-number column)
    # fell outside that span and every one of its data cells was handed to the
    # metadata scan. On a 1500-row price list that meant thousands of product
    # names were scanned for MOV/incoterms/lead time - and a product called
    # 'MLECZKO DO CZYSZCZENIA CIF 1001G' was read as a CIF incoterm.
    # A column that has a HEADER in the header row belongs to the table, even
    # when it is not mapped.
    # Where does the data table actually END?
    # Without this, any note written BELOW the table but inside the table's
    # column span (very common: 'EUR 1 - YES', 'Loading time - 7-10 days'
    # under the last product row) was classified as table data and never
    # reached the metadata scan.
    # The last data row is the last row holding a value in an "identifier"
    # column - one that only ever contains per-product data. Free-text columns
    # (product name / note) are deliberately excluded, because footer notes are
    # usually written in the product-name column.
    anchor_cols = []
    for fname in ('ean_col', 'price_col', 'case_price_col',
                  'case_size_col', 'unit_per_pallet_col', 'pallet_col',
                  'available_qty_col', 'hs_code_col'):
        v = getattr(template, fname, None)
        if v:
            ci = col_letter_to_index(v)
            if ci is not None:
                anchor_cols.append(ci)

    def _is_data_value(v):
        """
        Does this anchor cell hold product DATA, or footer prose?

        Anchor columns are the identifier/number columns (barcode, price,
        quantity...), so a real data cell is numeric or nearly so. Suppliers
        very often write the closing terms in the FIRST column, right under the
        last product - 'CONDITION : * All Goods are Fresh & Clean-Eu ...' in the
        EAN column, 'Offer Terms:' under the barcodes. Counting those as data
        pushed the end of the table past them, so the footer never qualified as
        a footer and the whole conditions block stayed invisible.
        """
        if isinstance(v, (int, float)):
            return True
        txt = str(v).strip()
        if not txt or '\n' in txt:
            return False
        alnum = re.sub(r'[^0-9A-Za-z]', '', txt)
        if not alnum:
            return False
        digits = sum(ch.isdigit() for ch in alnum)
        return digits / len(alnum) >= 0.4

    data_end_idx = None
    if anchor_cols:
        for r_idx, row in enumerate(sheet_data):
            if r_idx < header_row_idx:
                continue
            for ci in anchor_cols:
                if ci < len(row) and row[ci] is not None \
                        and str(row[ci]).strip() != '' and _is_data_value(row[ci]):
                    data_end_idx = r_idx
                    break
    # No anchor column mapped -> keep the old behaviour (table runs to the end).

    # Which COLUMNS belong to the table? Using only the min..max span of the
    # MAPPED columns was wrong: a column inside the table that we simply don't
    # map (a second product-name column, a stock column, a line-number column)
    # fell outside that span and every one of its data cells was handed to the
    # metadata scan. On a 1500-row price list that meant thousands of product
    # names were scanned for MOV/incoterms/lead time - and a product called
    # 'MLECZKO DO CZYSZCZENIA CIF 1001G' was read as a CIF incoterm.
    # A column that has a HEADER in the header row belongs to the table...
    # ...but ONLY if it is actually FILLED like a table column. Suppliers very
    # often park the offer conditions in a free column beside the table, with
    # the first line landing exactly on the header row:
    #     H2 'EXW: Italy'  H3 'MOQ: 5000 units'  H4 'Lead time: 4-6 weeks'
    # Treating H as a table column hid that whole sidebar from the metadata
    # scan, so the offer silently fell back to the default MOV/lead time and
    # lost its incoterm. A real table column is filled on nearly every data
    # row; a sidebar holds a handful of cells, so the fill ratio separates them.
    last_idx = data_end_idx if data_end_idx is not None else len(sheet_data) - 1
    n_data_rows = max(0, last_idx - header_row_idx)
    SIDEBAR_MAX_CELLS = 12          # a conditions sidebar is a few lines
    SIDEBAR_MAX_RATIO = 0.10        # ...and covers almost none of the table

    # NOTE: table_cols starts EMPTY, not from mapped_cols. Seeding it with the
    # mapped columns made every mapped column table data unconditionally, which
    # overrode the sidebar test below - a supplier who reuses a mapped column
    # for the conditions block had that block silently swallowed.
    table_cols = set()
    if 0 <= header_row_idx < len(sheet_data):
        for c_idx, val in enumerate(sheet_data[header_row_idx]):
            if val is None or str(val).strip() == '':
                continue
            # A mapped column is normally table data - but suppliers do reuse a
            # near-empty mapped column for the conditions block ('TERMS:' header
            # with EXW / lead time / MOQ underneath). Treating it as table data
            # hid the whole block, so a mapped column that is BOTH nearly empty
            # AND opens with a labelled statement is still read as metadata.
            if c_idx in mapped_cols:
                filled_m = 0
                for r_idx in range(header_row_idx + 1, last_idx + 1):
                    row = sheet_data[r_idx]
                    if c_idx < len(row) and row[c_idx] is not None \
                            and str(row[c_idx]).strip() != '':
                        filled_m += 1
                ratio_m = (filled_m / n_data_rows) if n_data_rows else 1.0
                if not (filled_m <= SIDEBAR_MAX_CELLS
                        and ratio_m < SIDEBAR_MAX_RATIO
                        and _column_opens_with_statement(sheet_data, c_idx,
                                                         header_row_idx, last_idx)):
                    table_cols.add(c_idx)
                    continue
                _logger.info("[SBS Meta] mapped column %s is nearly empty and "
                             "holds labelled statements - scanned as metadata "
                             "too (%s/%s cells).", index_to_col_letter(c_idx),
                             filled_m, n_data_rows)
                continue
            filled = 0
            for r_idx in range(header_row_idx + 1, last_idx + 1):
                row = sheet_data[r_idx]
                if c_idx < len(row) and row[c_idx] is not None \
                        and str(row[c_idx]).strip() != '':
                    filled += 1
            ratio = (filled / n_data_rows) if n_data_rows else 1.0
            is_statement = _looks_like_metadata_statement(val)
            sparse = filled <= SIDEBAR_MAX_CELLS and ratio < SIDEBAR_MAX_RATIO
            if is_statement or sparse:
                _logger.info("[SBS Meta] column %s (%r) looks like a conditions "
                             "sidebar (%s/%s cells, statement=%s) - scanned as "
                             "metadata.", index_to_col_letter(c_idx),
                             str(val).strip()[:30], filled, n_data_rows,
                             is_statement)
            else:
                table_cols.add(c_idx)

    # A mapped column with no header text never entered the loop above, so it
    # was never classified. It is still table data.
    for c_idx in mapped_cols:
        if c_idx in table_cols:
            continue
        header_row_vals = sheet_data[header_row_idx] \
            if 0 <= header_row_idx < len(sheet_data) else []
        head = header_row_vals[c_idx] if c_idx < len(header_row_vals) else None
        if head is None or str(head).strip() == '':
            table_cols.add(c_idx)

    cells = []
    for r_idx, row in enumerate(sheet_data):
        for c_idx, val in enumerate(row):
            if val is None or str(val).strip() == '':
                continue
            if ai_scan_mode == 'full':
                in_metadata = True
            else:
                in_table_cols = (c_idx in table_cols) if table_cols \
                    else (min_col <= c_idx <= max_col)
                in_data_rows  = (r_idx >= header_row_idx)
                if in_data_rows and data_end_idx is not None and r_idx > data_end_idx:
                    in_data_rows = False        # below the table -> footer note
                in_metadata   = not (in_table_cols and in_data_rows)
            if in_metadata:
                addr = f"{index_to_col_letter(c_idx)}{r_idx + 1}"
                # A single cell often holds the WHOLE conditions block as a
                # bulleted, newline-separated list:
                #   'CONDITION :
                #      *  All Goods are Fresh & Clean-Eu.
                #      *  Delivery - 10 DAYS
                #      *  EXW - Warsaw Poland'
                # Treated as one blob it defeats every reader: the incoterm is
                # 'buried in a long cell' and gets rejected, the lead time is
                # read out of the wrong line, and the note swallows all four
                # bullets. Each visual line is really its own statement, so emit
                # them separately. Single-line cells are unaffected.
                lines = []
                for ln in str(val).splitlines():
                    ln = ln.strip(' \t\u2022*-\u2013\u00b7')
                    if not ln:
                        continue
                    # A run of 3+ spaces is the supplier laying out columns
                    # inside one cell, so each piece is its own statement -
                    # but only split where a NEW label actually starts,
                    # otherwise plain padded prose gets chopped up.
                    pieces = re.split(r'\s{3,}', ln)
                    if len(pieces) > 1 and any(
                            _looks_like_metadata_statement(pc) or pc.rstrip().endswith(':')
                            for pc in pieces[1:]):
                        merged, buf = [], pieces[0]
                        for pc in pieces[1:]:
                            if _looks_like_metadata_statement(pc) or pc.rstrip().endswith(':'):
                                merged.append(buf.strip())
                                buf = pc
                            else:
                                buf += ' ' + pc
                        merged.append(buf.strip())
                        lines.extend([mg for mg in merged if mg])
                    else:
                        lines.append(ln)
                if len(lines) <= 1:
                    cells.append({'row': r_idx + 1, 'col': c_idx,
                                  'addr': addr, 'value': str(val).strip()})
                else:
                    for n, line in enumerate(lines):
                        cells.append({'row': r_idx + 1, 'col': c_idx,
                                      'addr': "%s#%d" % (addr, n) if n else addr,
                                      'value': line})
    return cells


# ─────────────────────────────────────────────────────────────
# pre-AI helpers (pure functions)
# ─────────────────────────────────────────────────────────────
def _normalize(s):
    s = str(s).lower().strip()
    s = re.sub(r'[._\-/]+', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def _looks_like_label(cell_text, keyword):
    norm = _normalize(cell_text)
    kw = _normalize(keyword)
    return re.search(r'(^|\s)' + re.escape(kw) + r'(\s|:|$)', norm) is not None


def _inline_value(cell_text, keyword):
    """
    Pull the value that sits right after the keyword in the same cell.
    The colon (if any) must belong to the KEYWORD, not to some other word later
    in the sentence: 'Our Moq is €.3500. Leadtime: one week' must NOT return
    'one week' for keyword 'moq' just because 'Leadtime:' has a colon.
    """
    raw = str(cell_text)
    # A keyword sitting in the MIDDLE of a sentence is not a label introducing a
    # value - it is part of the value. '20% T/T in advance (deposit)' matches the
    # keyword 'advance' at character 9, and taking the tail returned '(deposit)'
    # as the payment term while throwing the actual terms away. A real label
    # starts the cell (optionally after a bullet or quantifier such as 'Min').
    # Skip any leading non-letter noise: bullets, dashes and the emoji that
    # suppliers now decorate their terms with ('\U0001f4e6 Minimum Order Value:
    # \u00a33,000', '\u23f1 Lead Time: 7 Days'). Without this the label no longer
    # starts the cell and the value was never extracted.
    lead = re.match(r'^[^0-9A-Za-z]*(?:min\.?|minimum|our|total)?\s*'
                    + re.escape(keyword) + r'\b', raw, re.IGNORECASE)
    if not lead:
        # The keyword is part of the sentence, so the WHOLE cell is the value -
        # '20% T/T in advance (deposit)' IS the payment term. Only accept short
        # cells here: in a long paragraph a stray keyword would drag the entire
        # prose in as a value.
        compact = re.sub(r'\s+', ' ', raw).strip()
        if len(compact) <= 60 and len(compact.split()) <= 10:
            return compact
        return ''
    # locate the keyword
    km = re.search(r'(^|\b)' + re.escape(keyword) + r'\b', raw, re.IGNORECASE)
    if km:
        after_kw = raw[km.end():]
        # a colon/'is'/dash immediately tied to the keyword introduces the value;
        # stop at the first sentence break so we don't swallow the rest of the line
        m = re.match(r'\s*(?:is\s+)?[:\-]?\s*(.+?)(?:\.\s|\.$|$|,\s|;\s)', after_kw,
                     re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip()
    # fallback: remove the keyword and return whatever is left (single-token cells)
    pat = re.compile(r'(^|\b)' + re.escape(keyword) + r'(\b|$)', re.IGNORECASE)
    residual = pat.sub(' ', raw).strip()
    return residual if residual and residual != raw.strip() else ''


def _parse_cell_ref(ref):
    """
    Split a template cell reference into (column_letter, row_number).

      'A'  -> ('A', None)   a per-row COLUMN
      'B2' -> ('B', 2)      one ABSOLUTE cell, same value for every row

    Returns (None, None) when the reference is unusable.
    """
    if not ref:
        return None, None
    m = re.fullmatch(r'([A-Za-z]{1,3})(\d+)?', str(ref).strip())
    if not m:
        return None, None
    return m.group(1).upper(), (int(m.group(2)) if m.group(2) else None)


# 'Take all' / 'all stock' offers: the supplier sells the WHOLE basket in one
# lot, so there is no per-carton minimum to convert - the minimum order is the
# basket itself. Detected here so MOQ handling can hand over to MOV.
_TAKE_ALL_RE = re.compile(
    r'take[\s\-]*all|all[\s\-]*stock|whole[\s\-]*(?:stock|lot)|'
    r'entire[\s\-]*(?:stock|lot)|full[\s\-]*lot|job[\s\-]*lot|as[\s\-]*is[\s\-]*where',
    re.IGNORECASE)


def _is_take_all(value):
    """True when an MOQ/MOV text means 'buy the entire offer' rather than a quantity."""
    return bool(value) and bool(_TAKE_ALL_RE.search(str(value)))


# Words that name an offer CONDITION rather than a product attribute. On their
# own they can be a perfectly good column header ('Lead time' really is a column
# in some files), so they only signal a metadata sidebar when the cell also
# carries a VALUE - 'MOQ: Take all', 'EXW: Poland'.
# 'moa' = Minimum Order Amount, a common synonym for MOV; 'trade terms' and
# 'terms' introduce the incoterm block.
_META_KEYWORDS = (r'moq|mov|moa|min\.?\s*order|lead\s*time|leadtime|delivery\s*time|'
                  r'incoterms?|exw|fca|fob|cif|cfr|cpt|cip|dap|dpu|ddp|'
                  r'payment|deposit|t1\s*/\s*t2|eur\.?\s*1|validity|valid\s+for|'
                  r'trade\s*terms?|terms?\s*&?\s*conditions?')
_META_STATEMENT_RE = re.compile(
    r'^\s*(?:%s)\b\s*[:\-\u2013]\s*\S' % _META_KEYWORDS, re.IGNORECASE)
_META_KEYWORD_RE = re.compile(r'\b(?:%s)\b' % _META_KEYWORDS, re.IGNORECASE)


def _looks_like_metadata_statement(text):
    """
    True when a header-row cell is really the first line of a CONDITIONS SIDEBAR
    rather than a column header.

    Suppliers park the offer conditions in a free column beside the table, and
    the first line lands exactly on the header row - 'MOQ: Take all' at J2,
    'EXW: Poland' at I2. Fill ratio alone doesn't catch these on short lists: a
    4-cell sidebar next to a 13-row table is 31% full, which looks like a
    sparse-but-real column.

    A header is a NAME ('Lead time', 'Price'); a sidebar line is a STATEMENT -
    a condition word followed by its value. Requiring the value is what keeps a
    genuine 'Lead time' column from being thrown away.
    """
    txt = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not txt:
        return False
    if _META_STATEMENT_RE.match(txt):          # 'MOQ: Take all', 'EXW - Poland'
        return True
    # no separator, but a condition word buried in a full sentence
    return bool(_META_KEYWORD_RE.search(txt)) and len(txt.split()) >= 3


def score_template_headers(t, sheet_data):
    """
    Return the number of col+header pairs that matched (the 'score'),
    or -1 if the template is invalid (any mismatch / out of range / no
    pairs). A higher score means a more specific template, so the caller
    can pick the best-matching one when several templates fit.
    """
    header_row = int(t.header_row) if getattr(t, 'header_row', None) else 1
    header_row_idx = header_row - 1

    if header_row_idx >= len(sheet_data):
        # print(f"[X] '{t.name}': header_row={header_row} but file has {len(sheet_data)} rows")
        return -1

    template_fields = t.fields_get()
    fields_to_check = []
    for field_name in template_fields:
        if field_name.endswith('_col'):
            col_val = getattr(t, field_name, None)
            if not col_val:
                continue
            header_field = field_name.replace('_col', '_header')
            expected_header = getattr(t, header_field, None)
            fields_to_check.append((col_val, expected_header, field_name))

    score = 0
    for col_ref, expected_header, field_name in fields_to_check:
        expected_str = str(expected_header).strip() if expected_header else ""
        if not expected_str:
            continue

        col_idx = col_letter_to_index(col_ref)
        if col_idx is None:
            # print(f"[X] '{t.name}': col_ref '{col_ref}' invalid")
            return -1

        header_row_data = sheet_data[header_row_idx]
        if col_idx >= len(header_row_data):
            # print(f"[X] '{t.name}': column '{col_ref}' out of range")
            return -1

        cell_value = header_row_data[col_idx]
        actual_str = str(cell_value).strip() if cell_value is not None else ""
        # print(f"[Check] {field_name}: row={header_row}, col={col_ref}(idx={col_idx}) "
              # f"actual='{actual_str}' expected='{expected_str}'")

        if actual_str.lower() != expected_str.lower():
            # print(f"❌ '{t.name}' MISMATCH: '{actual_str}' != '{expected_str}'")
            return -1

        score += 1

    if score == 0:
        # print(f"[!] '{t.name}': no col+header pair defined -> rejected")
        return -1

    # print(f"✅ '{t.name}' matched! (score={score})")
    return score


def _column_opens_with_statement(sheet_data, c_idx, header_row_idx, last_idx):
    """Does this column's first few filled cells look like offer conditions?"""
    seen = 0
    for r_idx in range(header_row_idx, last_idx + 1):
        row = sheet_data[r_idx]
        if c_idx >= len(row) or row[c_idx] is None:
            continue
        text = str(row[c_idx]).strip()
        if not text:
            continue
        if _looks_like_metadata_statement(text):
            return True
        seen += 1
        if seen >= 4:
            break
    return False


def _looks_like_place_name(word):
    """
    Could this token be a city / place name?

    Used to guard the incoterm's city slot, which is filled from leftover text
    rather than a lookup. The rejections are all things that mean the parser has
    run past the place and into the next statement or into pricing data:

      'MOA:'    a label - places are not written with a colon
      '5,000'   a number - an amount, a postal code, a quantity
      'USD'     a currency or unit
      'w'       too short to be a place

    Kept permissive on purpose: any ordinary word is accepted, because res.city
    is empty in a stock Odoo and a whitelist would reject most real cities.
    """
    text = str(word or '').strip()
    if len(text) < 3:
        return False
    # a colon (or any label punctuation) means this opens a new statement
    if re.search(r'[:=;]', text):
        return False
    # must be mostly letters - rejects '5,000', '41-700', '20%'
    letters = sum(ch.isalpha() for ch in text)
    if letters < 3 or letters / len(text) < 0.6:
        return False
    if re.fullmatch(r'(?:usd|eur|gbp|aed|chf|jpy|cny|hkd|try|pln|'
                    r'pcs|pieces?|units?|boxe?s|cases?|cartons?|ctns?|'
                    r'pallets?|kgs?|ltrs?|each|per|net|total|price|prices)',
                    text, re.IGNORECASE):
        return False
    return True


def _validate(value, pattern):
    if not value:
        return False
    if pattern is None:
        return True
    return re.search(pattern, str(value), re.IGNORECASE) is not None


# Cells that state SHELF LIFE / batch validity, not a delivery duration.
# Suppliers phrase them exactly like a lead time ("batch code within 18 months
# from manufacturing"), and the anchor-free scan read that as a 72-week lead
# time. Detection must reject such cells.
_SHELF_LIFE_HINTS = re.compile(
    r'batch\s*code|shelf\s*life|best\s*before|expiry|expiration|'
    r'manufactur|production\s*date|\bmfd\b|\bmfg\b|'
    r'goods?\W{0,3}condition|freshness|remaining\s*life|'
    # a duration in these contexts is an offer/payment term, not a delivery time
    r'valid\s*(?:for|until|till)|validity|issue\s*date|price\s*list\s+valid|'
    r'\bnet\s*\d+|payment|\bt/?t\b|invoice|credit\s*terms?',
    re.IGNORECASE)


def _lead_time_context_ok(raw):
    """A duration is a LEAD TIME only when the cell is about dispatch/delivery.
    Reject cells that are really about batch validity or product expiry."""
    return not _SHELF_LIFE_HINTS.search(str(raw or ''))


def _incoterm_context_ok(raw, code_start, code_end):
    """
    Guard against incoterm codes that are really part of a PRODUCT NAME.
    'CIF', 'FOB', 'DAP' are also brands/words ('MLECZKO DO CZYSZCZENIA CIF
    1001G' = Cif cleaning milk). A genuine incoterm cell is short, or leads
    with the code, or carries an explicit incoterm label - and it is never
    followed by a product measure like '750ML' / '1001G'.
    """
    raw = str(raw)
    has_label = re.search(r'incoterm|delivery\s*term|trade\s*term|'
                          r'shipping\s*term|ex\s*works', raw, re.IGNORECASE)
    code_is_early = code_start <= 12
    cell_is_short = len(raw.split()) <= 4
    if not (has_label or code_is_early or cell_is_short):
        return False
    # A long PROSE sentence that merely mentions the code is not an incoterm
    # cell, e.g. 'Quoted EXW & offered subject to final confirmation.' Such a
    # footer note has the code early (passes code_is_early) but is really a
    # sentence. Unless it is explicitly labelled, reject cells that read as
    # prose: many words, or sentence punctuation after the code.
    if not has_label and not cell_is_short:
        after_full = raw[code_end:]
        looks_like_sentence = (
            len(raw.split()) >= 6
            or re.search(r'[.;]', after_full)
            or re.search(r'\b(and|or|only|please|subject|offered|quoted|'
                         r'confirmation|terms?|approx|aprox|note)\b',
                         after_full, re.IGNORECASE)
        )
        if looks_like_sentence:
            return False
    after = raw[code_end:].strip()
    if re.match(r'\d', after) or re.search(
            r'^\W*\d+\s*(ml|g|kg|l|pcs|szt|x\d)', after, re.IGNORECASE):
        return False            # 'CIF 750ML ...' -> a product, not an incoterm
    # A product MEASURE anywhere in the cell ('750ML', '1001G', '1L') means it
    # is a product description, e.g. 'CIF CLEANING MILK 750ML LEMON'. A real
    # incoterm cell names a place, not a pack size - unless it is explicitly
    # labelled as an incoterm.
    if not has_label and re.search(r'\d+\s*(ml|g|kg|l|szt)\b', raw, re.IGNORECASE):
        return False
    return True


def _is_other_field_label(text, fields_config, skip_key):
    """
    True when a cell is itself the LABEL of a different offer field.

    Terms blocks are often stacked in one column ('EXW: Germany' with
    'LEAD TIME: 6 weeks' right underneath). Such a neighbour must never be
    consumed as the value of the field above it.
    """
    s = str(text or '')
    for key, cfg in (fields_config or {}).items():
        if key == skip_key:
            continue
        for kw in cfg.get('keywords', ()):
            if _looks_like_label(s, kw):
                return True
    return False


def _labels_another_field(text, this_field, fields_config):
    """
    True when `text` OPENS with the label of a different offer field.

    _looks_like_label alone is not enough here: it also matches a keyword
    sitting mid-sentence, and 'Full payment before shipment' - a perfectly
    good payment term - then looked like a lead-time label because of the
    word 'shipment'. Only a keyword at the START of the cell introduces a
    new statement.
    """
    head = re.sub(r'^[^0-9A-Za-z]+', '', str(text or ''))
    for fkey, cfg in fields_config.items():
        if fkey == this_field:
            continue
        for kw in cfg.get('keywords', []):
            if re.match(r'(?:min\.?|minimum|our|total)?\s*' + re.escape(kw)
                        + r'\b', head, re.IGNORECASE):
                return True
    return False


def pre_ai_extract(metadata_cells, fields_config):
    """
    metadata_cells: output of extract_metadata_cells
    fields_config:  subset of DYNAMIC_FIELDS (offer-level)
    Output: {field_key: {'value':..., 'addr':..., 'method':...}, ...}
    """
    result = {}
    # First fragment wins per position. A multi-line cell is emitted as several
    # metadata entries that all share one (row, col), so a dict comprehension
    # kept the LAST line: a label in B5 pointing at C5 then read C5's closing
    # line instead of its opening one, and 'EUR 20K & ASSORTED ORDER / MAX PER
    # SKU 55PCS' handed the MOV parser the 55.
    by_pos = {}
    for c in metadata_cells:
        by_pos.setdefault((c['row'], c['col']), c['value'])
    # Address of each position too. A label and its value usually live in TWO
    # cells ('MOV:' in B5, '20KUSD & ASSORTED ORDER' in C5), and recording only
    # the label's address left the value cell looking untouched - so the offer
    # note picked it up again and repeated the lead time, MOV and payment terms
    # that already had their own fields.
    addr_by_pos = {}
    for c in metadata_cells:
        addr_by_pos.setdefault((c['row'], c['col']), c['addr'])

    # Stage A: Label + Proximity
    for cell in metadata_cells:
        text, r, c = cell['value'], cell['row'], cell['col']

        best = None
        for fkey, cfg in fields_config.items():
            if fkey in result:
                continue
            for kw in cfg['keywords']:
                if _looks_like_label(text, kw) and (best is None or len(kw) > best[0]):
                    best = (len(kw), fkey, kw)
        if not best:
            continue

        _, fkey, kw = best
        cfg = fields_config[fkey]
        pattern = cfg.get('pattern')

        candidates = []
        inline = _inline_value(text, kw)
        if inline:
            candidates.append(('inline', cell['addr'], inline))
        if by_pos.get((r, c + 1)):
            candidates.append(('right', addr_by_pos.get((r, c + 1), cell['addr']),
                               by_pos[(r, c + 1)]))
        if by_pos.get((r + 1, c)):
            candidates.append(('below', addr_by_pos.get((r + 1, c), cell['addr']),
                               by_pos[(r + 1, c)]))

        # When the LABEL itself is an incoterm code (e.g. cell 'EXW' with the
        # place in the next cell 'Spain'), the adjacent value is a place, not an
        # incoterm - so prepend the code to make a validatable 'EXW Spain'.
        code_kw = kw.strip().upper().replace(' ', '')
        INCOTERM_CODES = {'EXW', 'FCA', 'FAS', 'FOB', 'CFR', 'CIF', 'CPT',
                          'CIP', 'DAP', 'DPU', 'DDP', 'EXWORKS'}
        if cfg.get('label_is_incoterm') and code_kw in INCOTERM_CODES:
            code = 'EXW' if code_kw == 'EXWORKS' else code_kw
            # The same product-name guard Stage B uses: a bare incoterm code
            # sitting deep inside a long product description is NOT a label.
            cm = re.search(r'(^|\b)' + re.escape(kw) + r'\b', text, re.IGNORECASE)
            if cm and not _incoterm_context_ok(text, cm.start(), cm.end()):
                continue
            # The place may be written INLINE ('EXW: Germany'), to the right
            # ('EXW' | 'Spain'), or below. Inline wins: it is stated in the very
            # cell that carries the code, so it needs no guessing.
            # A neighbour is only usable when it is not itself another field's
            # label - otherwise a terms block stacked in one column
            #   H5 'EXW: Germany'
            #   H6 'LEAD TIME: 6 weeks'
            # made the incoterm swallow the lead-time line.
            place = inline
            if not place:
                for cand in (by_pos.get((r, c + 1)), by_pos.get((r + 1, c))):
                    if cand and not _is_other_field_label(cand, fields_config, fkey):
                        place = cand
                        break
            place = str(place or '').strip()
            combined = ("%s %s" % (code, place)).strip()
            if _validate(combined, pattern):
                result[fkey] = {'value': combined, 'addr': cell['addr'],
                                'label_addr': cell['addr'],
                                'method': 'label_incoterm'}
                continue

        for method, addr, val in candidates:
            # A neighbour cell that is itself a LABELLED statement for a
            # DIFFERENT field is not this field's value - it is simply the
            # next line of the sidebar. Without this guard, a label whose
            # own value fails to validate silently adopts the line below it.
            if method in ('right', 'below') and \
                    _labels_another_field(val, fkey, fields_config):
                continue
            if _validate(val, pattern):
                # 'addr' is where the VALUE was read; 'label_addr' is the cell
                # that named the field. Both count as consumed.
                result[fkey] = {'value': val, 'addr': addr,
                                'label_addr': cell['addr'],
                                'method': f'label_{method}'}
                break

    # Stage B: Anchor-Free Scan (only flagged fields)
    for fkey, cfg in fields_config.items():
        if fkey in result or not cfg.get('anchor_free') or not cfg.get('pattern'):
            continue
        scan_pattern = cfg.get('anchor_pattern', cfg['pattern'])
        for cell in metadata_cells:
            raw = str(cell['value'])
            mt = re.search(scan_pattern, raw, re.IGNORECASE)
            if not mt:
                continue
            if cfg.get('anchor_incoterm'):
                # Same product-name / prose guard the Stage A label path uses,
                # kept in one place (_incoterm_context_ok) so both agree - a
                # code buried in a product name ('...CIF 750ML...') or in a
                # footer sentence ('Quoted EXW & offered subject to...') is not
                # an incoterm.
                if not _incoterm_context_ok(raw, mt.start(), mt.end()):
                    continue
                # from the incoterm code to end of line (keeps destination, drops leading text)
                matched = raw[mt.start():].split('\n')[0].strip()
            elif cfg.get('anchor_lead_time') and not _lead_time_context_ok(raw):
                # shelf-life / batch-validity cell, not a delivery duration
                continue
            elif cfg.get('anchor_moq'):
                # keep only the quantity + unit (drop the 'MOQ' keyword itself)
                qm = re.search(r'(\d+)\s*'
                               r'(plt|pallets?|cases?|cartons?|ctn|units?|pcs|box(?:es)?)',
                               mt.group(0), re.IGNORECASE)
                if not qm:
                    continue
                num = qm.group(1)
                u = qm.group(2).lower()
                if u.startswith(('plt', 'pallet')):
                    unit = 'pallet'
                elif u.startswith(('case', 'carton', 'ctn')):
                    unit = 'case'
                else:
                    unit = 'unit'
                matched = "%s %s" % (num, unit)
            elif cfg.get('anchor_mov'):
                # keep only the monetary value (group 1), e.g. '€.3500' -> '€.3500'
                matched = (mt.group(1) if mt.groups() else mt.group(0)).strip()
            elif cfg.get('anchor_full_cell'):
                matched = raw.strip()              # whole cell
            else:
                matched = (mt.group(1) if mt.groups() else mt.group(0)).strip()
            result[fkey] = {'value': matched, 'addr': cell['addr'],
                            'method': 'pattern_scan'}
            break

    return result


# ─────────────────────────────────────────────────────────────
# MOV / offer helpers (pure functions)
# ─────────────────────────────────────────────────────────────
def extract_moq_from_header(header):
    """
    Extract a MOQ/MOV hint from a price-column header.
      'MOQ 5 PLT'   -> ('5 pallet', False)   # quantity MOQ
      'MOV 10K'     -> ('10K', True)         # monetary -> treat as MOV
    Returns (value_str, is_mov) or (None, False) when the header carries
    no MOQ/MOV pattern (e.g. 'UNIT PRICE EUR').
    """
    if not header:
        return None, False
    s = str(header)
    # FTL / Full Truck Load in the price header means the MOQ is a full truck,
    # which we treat as 20 pallets -> 20 x Max[Case/Pallet]. Return a marker
    # that compute_moq_in_cases understands.
    if re.search(r'\bftl\b|\bfull\s+truck\s*load\b', s, re.IGNORECASE):
        return '20 pallet', False
    mv = re.search(r'\bmov\b\s*[:\-]?\s*((?:€|\$|£|aed)?\s*[\d.,]+\s*k?)', s, re.IGNORECASE)
    if mv:
        return mv.group(1).strip(), True
    mq = re.search(r'\bmoq\b\s*[:\-]?\s*(\d+)\s*'
                   r'(plt|pallets?|cases?|cartons?|ctn|units?|pcs|box(?:es)?)?',
                   s, re.IGNORECASE)
    unit_required = False
    if not mq:
        # Headers often state the minimum with 'MIN' instead of 'MOQ', e.g.
        # 'Price II-tier\nMIN 9 box'. 'MIN' is a common word, so here the
        # packaging unit is REQUIRED - that keeps 'min 5 EUR' or 'min. 3%'
        # from being read as an MOQ.
        mq = re.search(r'\bmin(?:imum)?\b\.?\s*[:\-]?\s*(\d+)\s*'
                       r'(plt|pallets?|cases?|cartons?|ctn|units?|pcs|box(?:es)?)',
                       s, re.IGNORECASE)
        unit_required = True
    if mq:
        num = mq.group(1)
        unit_raw = (mq.group(2) or ('' if unit_required else 'pallet')).lower()
        if unit_raw.startswith(('plt', 'pallet')):
            unit = 'pallet'
        # 'box' is a carton, not a single piece - see parse_moq_quantity().
        elif unit_raw.startswith(('case', 'carton', 'ctn', 'box')):
            unit = 'case'
        else:
            unit = 'unit'
        return f"{num} {unit}", False
    return None, False


def _sbs_unmerge_fill(workbook, header_row=1):
    """
    Suppliers sometimes MERGE a cell across several DATA rows so one value (e.g. a
    single price) visually covers many products. openpyxl only keeps the value in
    the merge's top-left cell, leaving the rest blank - which breaks import
    (missing prices/quantities). This fills the top-left value into every cell the
    merge covered, so each product row carries its own value.

    Only merges that sit in the TABLE/DATA area (at or below header_row) are
    filled. Merges ABOVE the header are metadata/titles (e.g. a 'MOQ: ...' banner
    spanning several columns); those are left untouched so they don't get copied
    across columns and confuse metadata extraction. Applies to all data columns
    (price, currency, MOQ, ...), so any merged column is handled - not just price.
    No-op on read-only workbooks (which forbid writes).
    """
    for ws in workbook.worksheets:
        # copy the ranges first: unmerging mutates the collection we're iterating
        try:
            ranges = list(ws.merged_cells.ranges)
        except Exception:
            continue
        for mr in ranges:
            try:
                min_col, min_row, max_col, max_row = (
                    mr.min_col, mr.min_row, mr.max_col, mr.max_row)
                # skip metadata merges that live entirely above the header row
                if max_row < header_row:
                    continue
                top_left = ws.cell(row=min_row, column=min_col).value
                ws.unmerge_cells(str(mr))
                if top_left is None:
                    continue
                for r in range(min_row, max_row + 1):
                    for c in range(min_col, max_col + 1):
                        if r == min_row and c == min_col:
                            continue
                        ws.cell(row=r, column=c).value = top_left
            except Exception:
                # never let one odd merge stop the whole import
                continue
    return workbook


def _parse_pack_count(val):
    """
    Parse a packaging count (Unit/Case, Case/Pallet, ...) from a cell.
    Handles plain numbers ('12', 12, 12.0) and packing strings where the count
    follows an 'x', e.g. '200ML X 12' -> 12, '12 x 200ml' -> 12, '6X1L' -> 6.
    Returns an int, or 0 when nothing usable is found.
    """
    if val is None:
        return 0
    # already numeric
    if isinstance(val, (int, float)):
        try:
            return int(val)
        except Exception:
            return 0
    s = str(val).strip()
    if not s:
        return 0
    # plain integer/float string
    try:
        return int(float(s))
    except ValueError:
        pass
    # 'AxB' packing (e.g. '200ML X 12', '12 X 200ML', '6X1L', '24 x 500ml').
    # The COUNT is the number that is NOT glued to a volume/weight unit
    # (ml, l, g, kg, cl, oz, cc). Collect every number and drop the ones that a
    # unit immediately follows.
    UNIT = r'(?:ml|l|g|kg|cl|oz|cc)'
    nums = []
    for nm in re.finditer(r'(\d+(?:\.\d+)?)\s*([a-z]*)', s, re.IGNORECASE):
        digits, suffix = nm.group(1), (nm.group(2) or '').lower()
        is_measure = bool(re.match(UNIT + r'$', suffix))
        nums.append((digits, is_measure))
    # prefer the first number with no measurement unit after it -> that's count
    for digits, is_measure in nums:
        if not is_measure:
            try:
                return int(float(digits))
            except ValueError:
                continue
    return 0


def parse_moq_quantity(moq_str):
    """'2 pallet' -> (2.0, 'pallet'). Output: (number, unit) or (None, None)"""
    if not moq_str:
        return None, None
    # allow filler words between the number and the unit, e.g. '16 Full Pallets'
    # or '10 complete cartons' - grab the number, then the FIRST packaging unit
    # word that follows anywhere in the string.
    s = str(moq_str)
    num_m = re.search(r'(\d[\d\s.,]*\d|\d)', s)
    if not num_m:
        return None, None
    # normalise the number: strip spaces (thousands like '8 000' -> '8000'),
    # keep a single decimal separator.
    raw_num = num_m.group(1).replace(' ', '')
    if '.' in raw_num and ',' in raw_num:
        # both present -> comma is thousands sep: '5,000.50' -> '5000.50'
        raw_num = raw_num.replace(',', '')
    elif ',' in raw_num:
        # comma only: '5,000' (3 trailing digits) is thousands -> '5000';
        # '5,5' (1-2 trailing digits) is a decimal -> '5.5'
        if re.search(r',\d{3}$', raw_num):
            raw_num = raw_num.replace(',', '')
        else:
            raw_num = raw_num.replace(',', '.')
    try:
        num = float(raw_num)
    except ValueError:
        return None, None
    unit_m = re.search(
        r'\b(pallets?|pl?lts?|plls?|layers?|cases?|cartons?|ctns?|ctn|'
        r'units?|pcs|boxe?s?)\b',
        s, re.IGNORECASE)
    u = (unit_m.group(1).lower() if unit_m else '')
    if u.startswith(('pallet', 'plt', 'pll', 'pll')): unit = 'pallet'
    elif u.startswith('layer'):                      unit = 'layer'
    # A 'box' is a CARTON, not a single piece: suppliers write 'MIN 9 box'
    # next to a 'pcs in box' column holding values like 12 or 24. Bucketing it
    # with pcs/units made the MOQ unconvertible (and, since MOQ conversion
    # failures now reject the file, would have rejected valid price lists).
    elif u.startswith(('case', 'carton', 'ctn', 'box')): unit = 'case'
    elif u.startswith(('unit', 'pcs')):              unit = 'unit'
    else:                                            unit = None
    return num, unit


def _derive_packaging(vals):
    """
    Fill in missing packaging ratios from the ones already present, using:
        Unit/Layer  = Unit/Case * Case/Layer      (unit_per_layer = case_size*layer)
        Unit/Pallet = Unit/Case * Case/Pallet      (unit_per_pallet = case_size*pallet)

    Works in BOTH directions (e.g. Case/Pallet = Unit/Pallet / Unit/Case) and
    only ever writes a field that is currently empty/zero - real file data is
    never overwritten. Mutates 'vals' in place. Runs a couple of passes so a
    value derived in one step can feed the next (e.g. case_size then pallet).
    """
    def g(k):
        return vals.get(k) or 0

    def set_if_empty(k, v):
        # only fill blanks, and only with a clean positive integer
        if (vals.get(k) or 0):
            return False
        if v and v > 0 and float(v).is_integer():
            vals[k] = int(v)
            return True
        return False

    for _ in range(3):                       # a few passes for chained fills
        changed = False
        cs = g('case_size')
        lay = g('layer')             # Case/Layer
        pal = g('pallet')            # Case/Pallet
        upl = g('unit_per_layer')    # Unit/Layer
        upp = g('unit_per_pallet')   # Unit/Pallet

        # forward: multiply
        if cs and lay:
            changed |= set_if_empty('unit_per_layer', cs * lay)
        if cs and pal:
            changed |= set_if_empty('unit_per_pallet', cs * pal)
        # reverse: divide (exact only)
        if upl and cs and upl % cs == 0:
            changed |= set_if_empty('layer', upl // cs)
        if upp and cs and upp % cs == 0:
            changed |= set_if_empty('pallet', upp // cs)
        if upl and lay and upl % lay == 0:
            changed |= set_if_empty('case_size', upl // lay)
        if upp and pal and upp % pal == 0:
            changed |= set_if_empty('case_size', upp // pal)
        # Case/Pallet from Case/Layer * Layer/Pallet chain via units
        if upp and upl and upl and upp % upl == 0:
            # Layers/Pallet = Unit/Pallet / Unit/Layer -> Case/Pallet = Case/Layer * that
            lpp = upp // upl
            if lay:
                changed |= set_if_empty('pallet', lay * lpp)
        if not changed:
            break
    return vals


def _case_per_pallet(rec):
    """
    Cases-per-pallet for one row. Prefer the explicit 'pallet' ratio; otherwise
    derive it from Unit/Pallet / Unit/Case (e.g. 1548 pcs-per-pallet / 6 pcs-per-
    case = 258 cases-per-pallet). Returns a number (0 if not derivable).
    """
    direct = rec.get('pallet') or 0
    if direct:
        return direct
    upp = rec.get('unit_per_pallet') or 0
    cs = rec.get('case_size') or 0
    if upp and cs:
        return upp / cs
    return 0


def _case_per_layer(rec):
    """Cases-per-layer: explicit 'layer' ratio, else Unit/Layer / Unit/Case."""
    direct = rec.get('layer') or 0
    if direct:
        return direct
    upl = rec.get('unit_per_layer') or 0
    cs = rec.get('case_size') or 0
    if upl and cs:
        return upl / cs
    return 0


def compute_moq_in_cases(moq_number, moq_unit, temp_records):
    """
    Convert an MOQ expressed in pallets/layers into a CASE count, using the
    LARGEST packing ratio found across the whole offer (per the agreed rule):

        MOQ(pallet) -> moq_number * MAX(Case/Pallet over all rows)
        MOQ(layer)  -> moq_number * MAX(Case/Layer  over all rows)
        MOQ(case)   -> moq_number            (already in cases)
        MOQ(unit)   -> None                  (not a case-based quantity)

    Case/Pallet is taken from the explicit 'pallet' ratio, or derived from
    Unit/Pallet / Unit/Case when only those are mapped (same for layer).

    Example: MOQ = 10 pallets, rows have Case/Pallet 24/20/30/12/32
             -> 10 * 32 = 320 cases.
    Returns an integer case count, or None if it can't be computed.
    """
    if not moq_number:
        return None
    if moq_unit == 'case':
        return int(round(moq_number))
    if moq_unit == 'pallet':
        ratios = [_case_per_pallet(r) for r in (temp_records or [])]
        top = max(ratios) if ratios else 0
        return int(round(moq_number * top)) if top > 0 else None
    if moq_unit == 'layer':
        ratios = [_case_per_layer(r) for r in (temp_records or [])]
        top = max(ratios) if ratios else 0
        return int(round(moq_number * top)) if top > 0 else None
    if moq_unit in ('unit', 'piece'):
        # 'MOQ: 5000 units' with a case-size column in the file is perfectly
        # convertible - it just needs dividing instead of multiplying, which is
        # why it used to fall through and stay in pieces.
        # The SMALLEST case in the offer is used, mirroring the pallet rule
        # above: both pick the packing that yields the MOST cases, so the
        # converted MOQ still reaches the piece count the supplier asked for
        # whichever products the basket ends up containing.
        sizes = [r.get('case_size') or 0 for r in (temp_records or [])]
        sizes = [c for c in sizes if c and c > 0]
        if not sizes:
            return None
        return int(math.ceil(moq_number / float(min(sizes))))
    return None   # unknown unit -> leave MOQ as-is upstream


def compute_mov_units(moq_number, moq_unit, case_size, pallet, unit_per_pallet):
    """Return total number of units, or None if not computable."""
    if moq_unit == 'unit':
        return moq_number
    if moq_unit == 'case':
        return moq_number * case_size if case_size > 0 else None
    # pallet or unknown (assume pallet)
    if unit_per_pallet > 0:
        upp = unit_per_pallet
    elif case_size > 0 and pallet > 0:
        upp = case_size * pallet
    else:
        return None
    return moq_number * upp


def _has_currency(s):
    return re.search(r'(€|\$|£|aed)', str(s), re.IGNORECASE) is not None


def _is_monetary(s):
    """Is this a monetary value? currency symbol/word, or '<number>k' (thousands).
    A counting unit ('20 pallets', '5000 pcs') means a QUANTITY, never money."""
    s = str(s).lower()
    # a real quantity wins - never treat it as money
    if re.search(r'\b(pallets?|plt|pll|pal|cases?|cartons?|ctn|units?|pcs|'
                 r'pieces?|box(?:es)?|layers?|sku|items?)\b', s):
        return False
    if re.search(r'(€|\$|£|aed)', s):
        return True
    # word currencies: 'MOQ 33 000 EUR', '8000 USD', '5.000 euros'
    if re.search(r'\b(eur|euros?|usd|dollars?|gbp|pounds?)\b', s):
        return True
    # A currency word glued straight onto the digits kills the \b anchor above,
    # so '20KUSD' and '33.000EUR' read as plain quantities and never became an
    # MOV. Match the currency without requiring a word boundary before it.
    if re.search(r'\d\s*k?\s*(usd|eur|gbp|aed)', s):
        return True
    if re.search(r'\d\s*k\b', s):       # 20k = 20,000
        return True
    return False


def _normalize_mov(mov_raw, symbol):
    """Normalize MOV with a currency symbol. If it has none, prepend the price-list symbol."""
    s = str(mov_raw).strip()
    if re.search(r'(€|\$|£|aed)', s, re.IGNORECASE):
        return s                         # already has a symbol, leave as-is
    m = re.search(r'[\d.,]+\s*k?', s, re.IGNORECASE)
    if m:
        return f"{symbol}{m.group(0).replace(' ', '')}"
    return s


def _extract_weeks(val):
    """'2 weeks' or selection key '2' -> number of weeks"""
    m = re.search(r'\d+', str(val))
    if not m:
        return None
    n = int(m.group(0))
    if re.search(r'month', str(val), re.IGNORECASE):  return n * 4
    if re.search(r'day',   str(val), re.IGNORECASE):  return max(1, round(n / 7))
    return n


def _norm_country(s):
    s = str(s).strip().lower()
    s = re.sub(r'[.\-_/]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


_MONTH_NAMES = {
    'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3,
    'april': 4, 'apr': 4, 'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7,
    'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'sept': 9,
    'october': 10, 'oct': 10, 'november': 11, 'nov': 11, 'december': 12, 'dec': 12,
}
_MONTH_RE = re.compile(
    r'\b(%s)\b' % '|'.join(sorted(_MONTH_NAMES, key=len, reverse=True)),
    re.IGNORECASE)


def _weeks_until_month(month_no, today=None):
    """
    Weeks from today until the END of the next occurrence of `month_no`.

    Some suppliers state the delivery as a MONTH rather than a duration -
    'Delivery: October'. That is still a lead time, it just has to be measured.
    The END of the month is used because naming a month promises delivery
    WITHIN it, not on its first day; anchoring to the 1st would quote a lead
    time the shipment can miss by four weeks.
    """
    today = today or date.today()
    year = today.year if month_no >= today.month else today.year + 1
    last_day = calendar.monthrange(year, month_no)[1]
    delta = (date(year, month_no, last_day) - today).days
    if delta <= 0:
        return None
    return int(math.ceil(delta / 7.0))


def standardize_lead_time(raw, today=None):
    """Any text -> 'n Week(s)'. Converts days/months to weeks, ALWAYS rounding
    weeks UP (7-10 days -> 2 weeks). Ranges take the upper bound. A bare month
    name is measured to the end of that month. None if nothing is readable."""
    if not raw:
        return None
    s = str(raw)
    m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*week', s, re.IGNORECASE)
    if m:                                    # range like '2-3 weeks' -> upper bound
        n = int(m.group(2))
        return f"{n} Week{'s' if n > 1 else ''}"
    m = re.search(r'(\d+)\s*week', s, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        return f"{n} Week{'s' if n > 1 else ''}"
    m = re.search(r'(\d+)\s*month', s, re.IGNORECASE)
    if m:
        n = int(m.group(1)) * 4
        return f"{n} Week{'s' if n > 1 else ''}"
    # days: accept a range (take the upper bound) and round UP to whole weeks.
    m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*day', s, re.IGNORECASE)
    if m:
        n = max(1, math.ceil(int(m.group(2)) / 7))
        return f"{n} Week{'s' if n > 1 else ''}"
    m = re.search(r'(\d+)\s*day', s, re.IGNORECASE)
    if m:
        n = max(1, math.ceil(int(m.group(1)) / 7))
        return f"{n} Week{'s' if n > 1 else ''}"
    # No duration anywhere. A month name is still a delivery promise -
    # 'Delivery: October' - so measure it before giving up.
    # A bare range with no unit, in a cell that is already labelled as the lead
    # time: 'ETA 4/5' means four to five WEEKS. Weeks are assumed because that is
    # the unit suppliers omit; days and months are always spelled out. Kept tight
    # on purpose - both numbers small, ascending and close together - so that
    # dates ('13/07'), article codes and percentages cannot slip through.
    rng = re.search(r'(?<![\d.,])(\d{1,2})\s*[/\-\u2013]\s*(\d{1,2})(?![\d.,%])', s)
    if rng and len(s.split()) <= 4:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if 0 < lo < hi <= 52 and hi - lo <= 3:
            return "%d Week%s" % (hi, '' if hi == 1 else 's')

    # ...but only when the cell is SHORT enough to be a delivery statement.
    # Several month abbreviations are ordinary English words - 'may', 'mar',
    # 'sep' - and left unguarded they matched inside prose: '***Orders below
    # £5,000 may incur delivery charges***' became a 44-week lead time.
    mm = _MONTH_RE.search(s) if len(s.split()) <= 4 else None
    if mm:
        weeks = _weeks_until_month(_MONTH_NAMES[mm.group(1).lower()], today)
        if weeks:
            return "%d Week%s" % (weeks, '' if weeks == 1 else 's')
    return None                              # e.g. 'In stock', 'floor stock'


def standardize_mov(raw, symbol):
    """
    Normalize MOV to 'nK<sym>' when it's a round-thousands value,
    otherwise '<sym><number>'. Keeps an existing symbol if present.
    """
    if not raw:
        return None
    s = str(raw).strip()
    # find existing symbol - symbols first, then spelled-out currency codes so
    # a value written as '20KUSD' / '5000 EUR' keeps its own currency instead of
    # silently inheriting the price-list symbol.
    sym_m = re.search(r'(€|\$|£|aed)', s, re.IGNORECASE)
    if sym_m:
        sym = sym_m.group(1).upper()
    else:
        word_m = re.search(r'(usd|eur|gbp|aed|dollars?|euros?|pounds?)', s, re.IGNORECASE)
        _WORD_SYM = {'usd': '$', 'dollar': '$', 'dollars': '$',
                     'eur': '€', 'euro': '€', 'euros': '€',
                     'gbp': '£', 'pound': '£', 'pounds': '£', 'aed': 'AED'}
        sym = _WORD_SYM.get(word_m.group(1).lower(), symbol) if word_m else symbol
    # find the number, including spaces as thousands separators ('8 000') and a
    # trailing 'k' suffix.
    num_m = re.search(r'([\d][\d.,\s]*\d|\d)\s*(k)?', s, re.IGNORECASE)
    if not num_m:
        return s
    # strip spaces (thousands) -> plain number, then resolve the separators.
    num = num_m.group(1).replace(' ', '')
    has_k = bool(num_m.group(2))
    # Separators: a '.' or ',' followed by exactly 3 digits (and no other
    # decimal) is a THOUSANDS separator (European '33.000' = 33000, or '33,000').
    # A separator with 1-2 trailing digits is a decimal point.
    if '.' in num and ',' in num:
        # both present: the LAST one is the decimal, the other is thousands
        if num.rfind('.') > num.rfind(','):
            num = num.replace(',', '')          # 1,234.56 -> 1234.56
        else:
            num = num.replace('.', '').replace(',', '.')   # 1.234,56 -> 1234.56
    elif '.' in num:
        if re.search(r'\.\d{3}$', num) and num.count('.') == 1:
            num = num.replace('.', '')          # 33.000 -> 33000
        # else: keep as decimal
    elif ',' in num:
        if re.search(r',\d{3}$', num):
            num = num.replace(',', '')          # 33,000 -> 33000
        else:
            num = num.replace(',', '.')         # 33,5 -> 33.5
    try:
        value = float(num) * (1000 if has_k else 1)
    except ValueError:
        return s
    # express in K if it's a clean multiple of 1000
    if value >= 1000 and value % 1000 == 0:
        return f"{int(value // 1000)}K{sym}"
    return f"{sym}{int(value) if value == int(value) else value}"


class ImportDataWizard(models.TransientModel):
    _name = 'sbs.import.wizard'
    _description = 'SBS Import Wizard'

    file = fields.Binary(string='Excel File')
    file_name = fields.Char(string='Filename')
    import_number = fields.Char(string='Import Number', default=False)

    currency_id = fields.Many2one('res.currency', string='Default Currency',
                                  default=lambda self: self.env.ref('base.USD'))
    total_imported = fields.Integer(string="Imported Records", readonly=True)
    total_skipped = fields.Integer(string="Skipped Records", readonly=True)
    show_results = fields.Boolean(string="Show Results", default=False)
    result_error = fields.Char(string='Result Error')
    unstated_note = fields.Text(
        string='Not Stated In File', readonly=True,
        help="Offer-level facts the supplier's file never stated. They are left "
             "empty (or defaulted) and usually have to be confirmed by email.")
    cleanup_msg = fields.Char(string='CleanUP Message')

    from_doc = fields.Boolean(string="From Documents", default=False)
    from_rpc = fields.Boolean(string="From RPC", default=False)

    document_id = fields.Many2one('documents.document', string="Excel File")

    supplier_id = fields.Many2one('res.partner', string='Supplier')
    template_id = fields.Many2one('sbs.import.template', string='Template',
                                  domain="[('supplier_id', '=', supplier_id)]")

    # =================================================================
    # Dynamic-field helper methods
    # =================================================================
    def _get_or_create_brand(self, brand_name):
        """Find the brand; create it if missing. None if name is empty or model is absent."""
        if not brand_name or not str(brand_name).strip():
            return None
        if 'product.brand' not in self.env:
            _logger.warning("[SBS Brand] model 'product.brand' not installed.")
            return None
        name = str(brand_name).strip()
        Brand = self.env['product.brand']
        brand = Brand.search([('name', '=ilike', name)], limit=1)
        if not brand:
            brand = Brand.sudo().create({'name': name})
            _logger.info("[SBS Brand] created brand '%s' (id=%s)", name, brand.id)
        return brand

    def _apply_brand_to_product(self, product, brand_name, is_new_product):
        """
        Logic:
        - new product + has brand -> set the brand
        - existing product with no brand_id + has brand -> set the brand
        - existing product that already has a brand -> leave untouched
        """
        if not brand_name or not hasattr(product, 'brand_id'):
            return
        if not is_new_product and product.brand_id:
            return                                  # already has a brand, leave it
        brand = self._get_or_create_brand(brand_name)
        if brand:
            product.sudo().write({'brand_id': brand.id})
            _logger.info("[SBS Brand] set brand '%s' on product '%s'",
                         brand.name, product.name)

    def _apply_intrinsic_fields_to_product(self, product, coo_country, hs_code,
                                           is_new_product, cover_language=None):
        """
        Write intrinsic product attributes (Country of Origin, HS Code, Cover
        Language) onto the product.template using the same three-state logic as
        the brand:
          - new product + value present        -> set it
          - existing product, field empty + val -> set it
          - existing product, field already set -> leave untouched
        sbs.data reads these back via stored related fields, so nothing is
        written directly on sbs.data for these columns.
        """
        vals = {}
        if coo_country and hasattr(product, 'country_origin'):
            if is_new_product or not product.country_origin:
                vals['country_origin'] = coo_country.id
        if hs_code and hasattr(product, 'hs_code'):
            if is_new_product or not product.hs_code:
                vals['hs_code'] = str(hs_code).strip()
        if cover_language and hasattr(product, 'cover_language'):
            if is_new_product or not product.cover_language:
                vals['cover_language'] = str(cover_language).strip()
        if vals:
            product.sudo().write(vals)
            _logger.info("[SBS] set intrinsic fields %s on product '%s'",
                         list(vals.keys()), product.name)

    def _country_record(self, raw, country_lookup=None):
        """
        Resolve a CoO string to a res.country record (or False), branching on the
        LENGTH of the trimmed CoO text (per the agreed algorithm):

            len > 3  -> inclusive (partial) match against country NAMES
            len = 2  -> exact match against the 2-letter code  [res.country.code]
            len = 3  -> exact match against the 3-letter code  [res.country.code3]
            (len < 2 -> nothing)

        If the chosen branch finds nothing, return False (write nothing) -
        branches are NOT chained.
        """
        if not raw or not str(raw).strip():
            return False
        Country = self.env['res.country'].with_context(active_test=False)
        has_code3 = 'code3' in Country._fields

        text = str(raw).strip()
        token = re.sub(r'[^a-z]', '', text.lower())   # letters only, for codes
        n = len(token)

        # len = 2 -> exact 2-letter code
        if n == 2:
            country = Country.search([('code', '=ilike', token)], limit=1)
            return country or False

        # len = 3 -> exact 3-letter code
        if n == 3:
            if has_code3:
                country = Country.search([('code3', '=ilike', token)], limit=1)
                return country or False
            return False

        # len > 3 -> inclusive (partial) match against names
        if n > 3:
            # try a translated/canonical English name first, then the raw text
            en_name = self.translate_country(text, country_lookup) or text
            # exact name first (still "inclusive" branch, but exact wins if present)
            country = Country.search([('name', '=ilike', en_name)], limit=1)
            if country:
                return country
            needle = _norm_country(en_name)
            if needle and len(needle) >= 3:
                for c in Country.search([]):
                    cn = _norm_country(c.name or '')
                    if cn and (cn == needle or cn in needle or needle in cn):
                        return c
            return False

        # len < 2 -> nothing usable
        return False

    def standardize_incoterm(self, raw, country_lookup=None, city_lookup=None):
        """
        Normalize to 'CODE: Country(City)'.
        e.g. 'EXW Zvolen, SLOVAKIA' -> 'EXW: Slovakia(Zvolen)'
        A place that is only a CITY (e.g. 'FOB Jakarta') is resolved to its
        country through res.city when that city is known -> 'FOB: Indonesia(Jakarta)'.
        Keeps only the FIRST incoterm and stops before a second one or a MOQ/MOV clause.
        """
        if not raw:
            return None
        s = str(raw).strip()
        codes = r'EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP'
        m = re.search(rf'\b({codes})\b', s, re.IGNORECASE)
        if m:
            code = m.group(1).upper()
            start = m.end()
        else:
            mm = re.search(r'ex[\s\-]?works', s, re.IGNORECASE)
            if not mm:
                return s
            code = 'EXW'
            start = mm.end()
        tail = s[start:]
        # metadata is often multi-line in one cell ('EXW PL 41-700\nOther:'), so
        # keep only THIS line - the rest belongs to other labels.
        tail = tail.split('\n')[0]
        # cut before a second incoterm / "ex works" / MOQ / MOV
        cut = re.search(rf'\b({codes}|ex[\s\-]?works|moq|mov)\b', tail, re.IGNORECASE)
        if cut:
            tail = tail[:cut.start()]
        # cut at " and " join
        tail = re.split(r'\s+and\s+', tail, flags=re.IGNORECASE)[0]
        # drop postal codes ('41-700', '40-018', 'SW1A 1AA') - they aren't cities
        tail = re.sub(r'\b\d[\d\-\s]{2,}\d\b', ' ', tail)
        tail = re.sub(r'\b[A-Z]{1,2}\d[A-Z\d\s]{0,4}\b', ' ', tail)  # UK-style codes
        tail = tail.strip(' :,-')
        if not tail:
            return code
        # split tail into tokens; also split on whitespace so a bare country code
        # like 'PL' is isolated from any leftover words. A token that translates
        # to a known country is the country; the first other token is the city.
        # Split on commas/parens FIRST, then match the longest word n-gram inside
        # each phrase against the country lookup. Splitting straight down to
        # single words breaks every multi-word country name: 'EXW Our warehouse
        # Hong Kong' became ['Our','warehouse','Hong','Kong'], neither 'Hong' nor
        # 'Kong' is a country, so the place was dropped entirely and the city
        # slot got filled with the filler word 'Our'. Same for United Kingdom,
        # Saudi Arabia, South Africa, United Arab Emirates, Czech Republic...
        if country_lookup is None:
            country_lookup = self._build_country_lookup()
        # Strip trailing currency / unit words: they describe the PRICE column,
        # not a place. 'EXW USD PCS' is the header of a price column that
        # happens to name the incoterm - taking 'USD PCS' as the place produced
        # 'EXW: USD PCS'. Nothing left after stripping means the code was
        # stated without a place at all.
        tail = re.sub(r'\b(?:usd|eur|gbp|aed|chf|jpy|cny|hkd|try|pln|'
                      r'pcs?|pieces?|units?|boxe?s?|cases?|cartons?|ctns?|'
                      r'pallets?|kg|ltr?|each|per)\b',
                      ' ', tail, flags=re.IGNORECASE)
        tail = tail.strip(' :,-/')
        if not tail:
            return code

        phrases = [p.strip() for p in re.split(r'[,\(\)]+', tail) if p.strip()]
        country, city = None, None
        leftovers = []
        for phrase in phrases:
            words = [w for w in re.split(r'\s+', phrase) if w]
            i = 0
            while i < len(words):
                hit = None
                # longest span first: 'United Arab Emirates' must beat 'United'
                for span in range(min(4, len(words) - i), 0, -1):
                    cand = ' '.join(words[i:i + span])
                    cand_key = _norm_country(cand)
                    en = country_lookup.get(cand_key) \
                        or country_lookup.get(cand_key.replace(' ', ''))
                    if not en and span == 1:
                        # single tokens may still go through the fuzzy path
                        # (ISO codes, other languages, substring match). Multi-word
                        # spans must match EXACTLY, otherwise translate_country's
                        # substring scan lets 'Dubai United Arab Emirates' match as
                        # a single country and swallows the city.
                        guess = self.translate_country(cand, country_lookup)
                        if guess and _norm_country(guess) != _norm_country(cand):
                            en = guess
                    if en:
                        hit = (span, en)
                        break
                if hit:
                    if not country:
                        country = hit[1]
                    i += hit[0]
                else:
                    leftovers.append(words[i])
                    i += 1
        # The city slot is whatever is left over after the country is matched,
        # so it accepts words no lookup ever validated. That is deliberate -
        # res.city is empty in a stock Odoo, so requiring a match there would
        # throw away every real city. But "leftover" must at least LOOK like a
        # place name, otherwise the label of the NEXT statement lands in it:
        # 'EXW HK    MOA:  5,000 USD' produced 'EXW: Hong Kong(MOA:)'.
        _PLACE_FILLER = {'our', 'the', 'a', 'an', 'ex', 'from', 'at', 'in',
                         'warehouse', 'warehouses', 'store', 'stores', 'depot',
                         'factory', 'plant', 'port', 'terminal', 'facility',
                         'other', 'others'}
        for w in leftovers:
            if w.lower() in _PLACE_FILLER:
                continue
            if not _looks_like_place_name(w):
                _logger.info("[SBS] %r sits where the incoterm place should be "
                             "but does not read as a place name - ignored.", w)
                continue
            city = w
            break
        # Only a city was given (e.g. 'FOB Jakarta'): look the city up to get its
        # country. Falls back to the raw place when the city isn't in res.city.
        if city and not country:
            if city_lookup is None:
                city_lookup = self._build_city_lookup()
            country = city_lookup.get(_norm_country(city))
        if country and city:
            return f"{code}: {country}({city})"
        if country:
            return f"{code}: {country}"
        # No country resolved. Only keep the leftover tail if it looks like a
        # real place - a short run of place words, not a prose fragment such as
        # '& offered subject to final confirmation.' Otherwise emit just the
        # code. (This is the last-line defence behind the detection guard that
        # already rejects such footer sentences.)
        tail_clean = tail.strip(' :,-&').strip()
        JUNK = {'and', 'or', 'to', 'the', 'a', 'of', 'offered', 'subject',
                'final', 'confirmation', 'quoted', 'only', 'please', 'other',
                'others', 'for', 'is', 'in', 'as', 'at', 'be', 'no'}
        tokens = [t for t in re.split(r'[\s,]+', tail_clean) if t]
        real = [t for t in tokens if t.lower() not in JUNK and re.search(r'[^\W\d_]', t)]
        if tokens and real and len(real) <= 3 and len(real) >= len(tokens) - 1:
            return f"{code}: {' '.join(real)}"
        return code

    def _currency_from_price_format(self, file_content, template):
        """
        Detect currency from the price column's cell number-format
        (e.g. a cell rendered as "€0.70" whose stored value is 0.70).
        Reads cell styles directly so it works even when openpyxl drops formats.
        Returns a res.currency id or None. XLSX only.
        """
        try:
            import zipfile
            from io import BytesIO as _BIO
            with zipfile.ZipFile(_BIO(file_content)) as z:
                names = z.namelist()
                if 'xl/styles.xml' not in names:
                    return None
                styles = z.read('xl/styles.xml').decode('utf-8', errors='ignore')
            # collect any currency-bearing format codes
            for m in re.finditer(r'formatCode="([^"]*)"', styles):
                cur = self._detect_currency_id(m.group(1))
                if cur:
                    return cur
        except Exception as e:
            _logger.warning("[SBS] currency-from-format scan failed: %s", e)
        return None

    def _detect_currency_id(self, text):
        """Map a currency hint (symbol or code/word) to a res.currency id, or None."""
        if not text:
            return None
        s = str(text).lower()
        code = None
        if '€' in str(text) or re.search(r'\beur\b|euro', s):
            code = 'EUR'
        elif '£' in str(text) or re.search(r'\bgbp\b|pound|sterling', s):
            code = 'GBP'
        elif re.search(r'\baed\b|dirham|dhs?\b', s):
            code = 'AED'
        elif '$' in str(text) or re.search(r'\busd\b|dollar', s):
            code = 'USD'
        if not code:
            return None
        cur = self.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', code)], limit=1)
        return cur.id if cur else None

    def _build_city_lookup(self):
        """
        Map: city name (normalized) -> its country's English name, from Odoo's
        res.city. Lets 'FOB Jakarta' resolve to Indonesia.

        NOTE: res.city is EMPTY in a stock Odoo - it's filled by localization
        modules (l10n_*_cities). Any city that isn't there simply won't resolve,
        and the incoterm keeps the raw place, so this is safe either way.
        """
        lookup = {}
        City = self.env.get('res.city')
        if City is None:
            return lookup
        try:
            cities = City.with_context(active_test=False).search([])
        except Exception:
            return lookup
        # res.country.state ships WITH Odoo (unlike res.city), and suppliers
        # very often name a state or province rather than a city: 'EXW: New
        # York' resolved to nothing at all because New York is a state here, not
        # a populated res.city row. States are loaded first so a real city of
        # the same name can still win below.
        State = self.env.get('res.country.state')
        if State is not None:
            try:
                for st in State.with_context(active_test=False).search([]):
                    if not st.name or not st.country_id:
                        continue
                    en = st.country_id.with_context(lang='en_US').name
                    if en:
                        lookup.setdefault(_norm_country(st.name), en)
            except Exception:
                pass

        for city in cities:
            if not city.name or not city.country_id:
                continue
            en_country = city.country_id.with_context(lang='en_US').name
            if not en_country:
                continue
            key = _norm_country(city.name)
            # first one wins; ambiguous city names across countries are rare
            # enough here and we prefer a stable, deterministic result.
            lookup.setdefault(key, en_country)
        return lookup

    def _build_country_lookup(self):
        """One-time map: country name (any language, normalized) or ISO code -> English name"""
        lookup = {}
        countries = self.env['res.country'].with_context(active_test=False).search([])
        langs = self.env['res.lang'].search([('active', '=', True)]).mapped('code')
        if 'en_US' not in langs:
            langs.append('en_US')
        for country in countries:
            en_name = country.with_context(lang='en_US').name
            if not en_name:
                continue
            # ISO code kept UPPERCASE and matched case-sensitively (see the
            # code-branch in translate_country). If it were lowercased into the
            # same map as names, the English word 'to' would match Tonga's code
            # 'to', 'is'->Iceland, 'in'->India ... which is how a footer
            # sentence produced 'EXW: Tonga'.
            if country.code:
                lookup['\x00' + country.code.upper()] = en_name
            for lang in langs:
                nm = country.with_context(lang=lang).name
                if nm:
                    key = _norm_country(nm)
                    lookup[key] = en_name
                    # Space-collapsed alias: suppliers write multi-word countries
                    # as one word ('EXW HONGKONG', 'SOUTHAFRICA', 'UNITEDKINGDOM').
                    # Without this the lookup missed them and the place was
                    # dropped from the incoterm entirely.
                    squashed = key.replace(' ', '')
                    if squashed != key:
                        lookup.setdefault(squashed, en_name)

        # Everyday abbreviations that are NOT the ISO code, so nothing else
        # resolves them: suppliers write 'EXW UK', never 'EXW GB'.
        _INFORMAL = {
            'uk': 'United Kingdom', 'gb': 'United Kingdom',
            'great britain': 'United Kingdom', 'england': 'United Kingdom',
            'usa': 'United States', 'us': 'United States',
            'u s a': 'United States', 'america': 'United States',
            'uae': 'United Arab Emirates', 'emirates': 'United Arab Emirates',
            'holland': 'Netherlands', 'korea': 'South Korea',
        }
        by_name = {v.lower(): v for v in lookup.values()}
        for alias, en in _INFORMAL.items():
            real = by_name.get(en.lower())
            if real:
                lookup.setdefault(_norm_country(alias), real)
                lookup.setdefault(_norm_country(alias).replace(' ', ''), real)
        return lookup

    def translate_country(self, raw, country_lookup=None):
        """Country name in any language -> English name. If no match, return the input."""
        if not raw or not str(raw).strip():
            return None
        raw_str = str(raw).strip()
        if country_lookup is None:
            country_lookup = self._build_country_lookup()

        key = _norm_country(raw_str)

        # 0. ISO code: only when the token was written UPPERCASE ('PL', 'DE').
        #    Codes live under a '\x00' prefix so a lowercase word like 'to'
        #    can never collide with Tonga's code.
        if raw_str.isupper() and len(raw_str) in (2, 3):
            hit = country_lookup.get('\x00' + raw_str)
            if hit:
                return hit

        # 1. exact match
        if key in country_lookup:
            return country_lookup[key]

        # 2. partial match - longest country name contained in the input
        best = None
        for name_key, en in country_lookup.items():
            if name_key[:1] == '\x00':
                continue        # skip ISO-code entries in the substring scan
            if len(name_key) >= 4 and name_key in key:
                if best is None or len(name_key) > best[0]:
                    best = (len(name_key), en)
        if best:
            return best[1]

        # 3. pycountry
        #    GUARD: pycountry maps 2-letter ISO codes and fuzzy-matches short
        #    tokens, so ordinary English words become countries -
        #    'to'->Tonga, 'is'->Iceland, 'in'->India, 'and'->Andorra. That is
        #    how 'subject TO final...' produced 'EXW: Tonga(&)'. So:
        #      * fuzzy search only for tokens long enough to be a real name (>=4);
        #      * alpha-2/alpha-3 code lookup only when the token was written in
        #        UPPERCASE (a real country CODE is 'PL'/'DE', never 'to'/'is').
        try:
            import pycountry
            if len(raw_str) >= 4:
                try:
                    matches = pycountry.countries.search_fuzzy(raw_str)
                    if matches:
                        return matches[0].name
                except LookupError:
                    pass
            if raw_str.isupper() and len(raw_str) in (2, 3):
                c = (pycountry.countries.get(alpha_2=raw_str)
                     or pycountry.countries.get(alpha_3=raw_str))
                if c:
                    return c.name
        except ImportError:
            pass

        # 4. no match
        return raw_str

    def _ai_extract(self, metadata_cells, missing_fields, template):
        """
        Ask the model to read the AMBIGUOUS metadata cells for fields the regex
        rules couldn't resolve. Routed through SbsAIProvider, so it works with a
        local Ollama server or a cloud endpoint depending on Settings.

        Safety:
          * runs only when AI + metadata assist are enabled (checked here)
          * the model's answer is validated against each field's regex pattern
            (hallucination guard) - a value that doesn't look right is dropped
          * any failure returns {} and the caller keeps the regex result

        Output: {fkey: {'value','addr','method':'ai'}}
        """
        if not missing_fields or not metadata_cells:
            return {}

        from odoo.addons.oe_sbs.models.sbs_ai_provider import SbsAIProvider
        provider = SbsAIProvider(self.env)
        if not provider.metadata_enabled():
            _logger.warning(
                "[SBS AI] skipped - %s. (regex could not resolve: %s) "
                "[settings: enabled=%r, model=%r, for_metadata=%r, lib=%r]",
                provider.why_disabled(),
                ", ".join(missing_fields.keys()),
                provider.enabled, provider.model, provider.for_metadata,
                provider.has_library())
            return {}

        # Don't spend ~15s on the model when there's almost nothing to read. If
        # the metadata region is just a couple of short cells (often stray table
        # headers), there's no free-text metadata to extract - keep regex only.
        meaningful = [c for c in metadata_cells
                      if len(str(c.get('value') or '').strip()) >= 3]
        total_text = sum(len(str(c.get('value') or '')) for c in meaningful)
        if len(meaningful) < 2 or total_text < 15:
            _logger.warning(
                "[SBS AI] skipped the model call - metadata region too sparse "
                "(%d usable cell(s), %d chars). Nothing to extract; if you "
                "expected metadata here, check the template's header row / "
                "Metadata Scan Mode.", len(meaningful), total_text)
            return {}

        _logger.warning(
            "[SBS AI] calling model '%s' at %s for %d unresolved field(s): %s",
            provider.model, provider.base_url or 'default',
            len(missing_fields), ", ".join(missing_fields.keys()))

        cells_text = "\n".join(f"{c['addr']}: {c['value']}" for c in metadata_cells)

        # Show exactly what the model is given. If everything comes back null,
        # this tells us whether the cells actually held the fields (model missed
        # them) or the metadata region was empty/wrong (nothing to find).
        _logger.warning("[SBS AI] %d metadata cell(s) sent to model:\n%s",
                        len(metadata_cells), cells_text[:2000])

        # Human-readable meaning per field. The model kept inventing its own key
        # names ('movement_type' for 'mov'!), so the keys are spelled out as an
        # explicit, closed list and repeated in the schema.
        FIELD_HELP = {
            'mov': "Minimum Order VALUE - a sum of money (e.g. '8 000 EUR', '33.000EUR', '10k')",
            'moq': "Minimum Order QUANTITY - a count with a unit (e.g. '5 pallets', '16 cases')",
            'incoterms': "Incoterm code, optionally with a place (e.g. 'EXW Spain', 'FOB Jakarta')",
            'payment_term': "Payment terms (e.g. '30% in advance, 70% before shipping')",
            'offer_validity': "How long the offer is valid (e.g. '2 weeks', 'valid until 30/06')",
            'lead_time': "Delivery/production lead time (e.g. '6-8 weeks', '10 days')",
            'coo': "Country of origin of the goods (e.g. 'Poland', 'Germany')",
            't1': "Is the stock T1 (not customs-cleared)? Yes / No",
            't2': "Is the stock T2 / EU Clean? Yes, No, or Available (can be arranged on request)",
            'euro1': "Is an EUR.1 movement certificate provided? Yes / No",
            'currency': "Currency of the prices (e.g. 'EUR', 'USD', '£')",
        }
        keys = list(missing_fields.keys())
        fields_desc = "\n".join(
            '- "%s": %s' % (k, FIELD_HELP.get(k, ", ".join(
                missing_fields[k].get('keywords', [])[:3])))
            for k in keys
        )
        schema = ", ".join('"%s": ...' % k for k in keys)

        system = (
            "You read metadata from a supplier price list. You get cells taken "
            "from OUTSIDE the product table, each with its spreadsheet address.\n"
            "RULES:\n"
            "1. Answer with ONE JSON object and nothing else. No prose, no "
            "markdown, no ``` fences.\n"
            "2. Use EXACTLY the keys you are given - never rename them, never "
            "invent new ones, never translate them.\n"
            "3. Each key maps to {\"value\": \"<copied verbatim from a cell>\", "
            "\"addr\": \"<that cell's address>\"} or to null if it is absent.\n"
            "4. The value MUST be copied character-for-character from a cell. "
            "Never paraphrase, never compute, never invent.\n"
            "5. If a field is not clearly present, use null. A wrong guess is "
            "worse than null."
        )
        user = (
            "Cells:\n%s\n\n"
            "Fields to find:\n%s\n\n"
            "Return exactly this shape (same keys, in this order):\n{%s}\n\n"
            "Worked example -- if the cells were:\n"
            "  B2: Min Order Value\n"
            "  C2: 33.000EUR\n"
            "  B5: EXW\n"
            "  C5: Spain\n"
            "and the fields asked were \"mov\" and \"incoterms\", the answer is:\n"
            '{"mov": {"value": "33.000EUR", "addr": "C2"}, '
            '"incoterms": {"value": "EXW", "addr": "B5"}}\n\n'
            "Answer with the JSON only. Do not reason step by step. /no_think"
        ) % (cells_text, fields_desc, schema)

        parsed = provider.chat_json(system, user, max_tokens=1024)
        if not isinstance(parsed, dict):
            _logger.warning(
                "[SBS AI] no usable answer (model unreachable, timed out, or bad "
                "JSON) - keeping the regex result")
            return {}

        # The model is supposed to reuse our keys verbatim. If it renamed them
        # ('mov' -> 'movement_type'), nothing can match - say so loudly instead
        # of reporting a silent 'nothing accepted'.
        unknown = [k for k in parsed.keys() if k not in missing_fields]
        if unknown:
            _logger.warning(
                "[SBS AI] model returned keys we did not ask for: %s "
                "(asked for: %s) - these are ignored",
                ", ".join(unknown), ", ".join(missing_fields.keys()))

        result = {}
        rejected = []
        for fkey, cfg in missing_fields.items():
            item = parsed.get(fkey)
            if not (item and isinstance(item, dict) and item.get('value')):
                if fkey in parsed:
                    rejected.append("%s=%r (null/!dict)" % (fkey, parsed.get(fkey)))
                continue
            val = str(item['value']).strip()
            # hallucination guard: the value must still match the field's own
            # regex, and must actually appear in one of the metadata cells.
            pattern = cfg.get('pattern')
            if pattern and not re.search(pattern, val, re.IGNORECASE):
                rejected.append("%s=%r (pattern)" % (fkey, val))
                continue
            if not any(val in str(c['value']) for c in metadata_cells):
                rejected.append("%s=%r (not in any cell)" % (fkey, val))
                continue    # value not found verbatim in any cell -> reject
            result[fkey] = {'value': val, 'addr': item.get('addr', ''), 'method': 'ai'}

        if result:
            _logger.warning("[SBS AI] accepted: %s", ", ".join(
                "%s=%r" % (k, v['value']) for k, v in result.items()))
        else:
            _logger.warning("[SBS AI] nothing accepted from the model")
        if rejected:
            _logger.warning("[SBS AI] rejected by guard: %s", "; ".join(rejected))
        return result

    def _sym(self, currency):
        if not currency:
            return '$'
        if currency.symbol in ('$', '€', '£'):
            return currency.symbol
        return {'USD': '$', 'EUR': '€', 'GBP': '£', 'AED': 'AED'}.get(
            currency.name, currency.symbol or '$')

    def _compute_mov_from_moq(self, moq_str, temp_records):
        """
        DEPRECATED: MOV is no longer derived from MOQ. Kept for reference only;
        not called anywhere in the current flow.

        Compute MOV from a quantity MOQ, per the agreed algorithm:
            MOV = (1 + Default Profit Margin%) * MOQ(pallets)
                  * MAX[(Unit/Pallet) * Prices]
        then rounded UP to the nearest 1000 monetary units.
          - Unit/Pallet comes from packaging: unit_per_pallet, else case_size * pallet
            (case_size = units per case, pallet = cases per pallet)
          - MAX over items: the most expensive line drives the value
        Packaging is taken from any row that has it (not only one row), so a
        missing value on a single item doesn't blank out the whole MOV.
        Returns a value string, or None if it truly cannot be computed.
        """
        num, unit = parse_moq_quantity(moq_str)
        if not num or not temp_records:
            return None
        priced = [r for r in temp_records if r.get('supplier_unit_price')]
        if not priced:
            return None

        # packaging: prefer the most expensive row, else any row that has it
        dearest = max(priced, key=lambda r: r.get('converted_price') or 0)

        def pick(field):
            v = dearest.get(field)
            if v:
                return v
            for r in priced:
                if r.get(field):
                    return r[field]
            return 0

        units = compute_mov_units(num, unit,
                                  pick('case_size'),
                                  pick('pallet'),
                                  pick('unit_per_pallet'))
        if not units:
            return None

        # MAX[(Unit/Pallet) * Prices] -> the most expensive item's unit price
        max_price = dearest.get('supplier_unit_price') or 0

        margin = self._get_default_profit_margin()
        raw_value = (1 + margin) * units * max_price
        value = self._round_up_to(raw_value, 1000)

        cur = self.env['res.currency'].browse(dearest['currency_id']) \
            if dearest.get('currency_id') else self.env.ref('base.USD')
        return f"{self._sym(cur)}{int(value)}"

    def _get_default_profit_margin(self):
        """Default profit margin as a fraction (e.g. 8% -> 0.08)."""
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            return float(ICP.get_param('oe_sbs.default_profit_margin', '8')) / 100
        except (TypeError, ValueError):
            return 0.08

    def _mov_to_number(self, mov_value, apply_margin=False):
        """
        Parse a found MOV (text like '20K€', '€8,103', or a number) into a raw
        numeric amount in the price-list currency. When apply_margin is True,
        gross it up by the default profit margin and round UP to the nearest
        1000:  MOV = (1 + margin) * MOV. Returns a float, or None if unparsable.
        """
        if mov_value is None:
            return None
        s = str(mov_value).strip()
        # strip currency-noise like a leading dot ('€.3500' = 3500) and a
        # trailing '.-' (Dutch price notation) before parsing.
        s = re.sub(r'[€$£]\s*\.', '', s)        # '€.' -> '' (drop the false decimal)
        s = re.sub(r'\.\-\s*$', '', s)          # trailing '.-'
        s = s.rstrip('.-').strip()
        # support a trailing 'k' meaning thousands (e.g. '20k')
        # A trailing 'k' means thousands. '\\b' after the k is not enough: in
        # '20KUSD' the k is followed by another letter, so the boundary never
        # matched, the value parsed as 20 and a 20,000 MOV became 1,000.
        k = bool(re.search(r'\d\s*k(?![a-z])', s, re.IGNORECASE)) \
            or bool(re.search(r'\d\s*k\s*(usd|eur|gbp|aed)', s, re.IGNORECASE)) \
            or s.lower().endswith('k')
        # European thousands dot/comma: a separator followed by exactly 3 digits
        # (and nothing else after) means thousands, so '33.000' / '33,000' are
        # 33000, not 33. Only applied to MOV, where sub-euro decimals are moot.
        # Take ONLY the first monetary number. Cells sometimes hold two values
        # (a min/max like '7.000€/12.000€', or leftover label text), and parsing
        # the whole string glued them into 700012. Grab the first number and
        # resolve its own separators, ignoring anything after it.
        m = re.search(r'\d[\d.,\s]*\d|\d', s)
        if not m:
            return None
        num = m.group(0).replace(' ', '')
        if '.' in num and ',' in num:
            if num.rfind('.') > num.rfind(','):
                num = num.replace(',', '')                 # 1,234.56 -> 1234.56
            else:
                num = num.replace('.', '').replace(',', '.')   # 1.234,56 -> 1234.56
        elif re.search(r'[.,]\d{3}$', num) and num.count('.') + num.count(',') == 1:
            num = num.replace('.', '').replace(',', '')     # 33.000 -> 33000
        else:
            num = num.replace(',', '.')                     # 33,5 -> 33.5
        try:
            amount = float(num)
        except ValueError:
            return None
        if k:
            amount *= 1000
        if apply_margin:
            margin = self._get_default_profit_margin()
            amount = self._round_up_to((1 + margin) * amount, 1000)
        return float(amount)

    @staticmethod
    def _round_up_to(value, step):
        """Round a number UP to the nearest multiple of `step` (e.g. 1000)."""
        if not step:
            return round(value)
        import math
        return int(math.ceil(float(value) / step) * step)

    # Wording that means "we don't hold it cleared, but we can arrange it".
    _T2_AVAILABLE_RE = re.compile(
        r'\bavailable\b|on\s+request|upon\s+request|if\s+(?:required|requested|needed)|'
        r'can\s+be\s+(?:arranged|provided|done)|possible|optional|negotiable',
        re.IGNORECASE)
    _NEGATIVE_RE = re.compile(
        r'\bno\b|\bnot\b|\bnone\b|\bwithout\b|\bn/?a\b|\bexcluded\b', re.IGNORECASE)
    _POSITIVE_RE = re.compile(r'\byes\b|\bincluded\b|\bavail\b|\ball\b|\bconfirmed\b',
                              re.IGNORECASE)

    @staticmethod
    def _strip_t_label(txt):
        """
        Remove the FIELD LABEL 'T1/T2' so only an answer can survive.

        This is the recurring trap: 'T1/T2' is what suppliers call the field, so
        the label and the answer are spelled identically. 'T1/T2   EXW NL' is a
        label with no answer, and matching the first token stamped the offer T1.
        """
        out = re.sub(r'\bT1\s*[/\\|&\-\u2013]\s*T2\b', ' ', str(txt or ''), flags=re.IGNORECASE)
        out = re.sub(r'\bT2\s*[/\\|&\-\u2013]\s*T1\b', ' ', out, flags=re.IGNORECASE)
        out = re.sub(r'\bT1\s+or\s+T2\b', ' ', out, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', out).strip()

    @classmethod
    def _resolve_yes_no(cls, raw, token_re, allow_available=False):
        """
        Read a Yes / No (/ Available) answer out of free text.

        Suppliers state these three ways:
          'T2: Yes'                    -> explicit answer
          'All goods are EU Clean'     -> the mere assertion IS the answer
          'EUR.1 - on request'         -> available, not held

        Returns 'yes' / 'no' / 'available' / None.
        """
        txt = cls._strip_t_label(raw)
        if not txt or not token_re.search(txt):
            return None
        # look at what surrounds the token, not the token itself
        rest = token_re.sub(' ', txt)
        if allow_available and cls._T2_AVAILABLE_RE.search(rest):
            return 'available'
        if cls._NEGATIVE_RE.search(rest):
            return 'no'
        if cls._POSITIVE_RE.search(rest):
            return 'yes'
        # the supplier named the status with no qualifier -> they are asserting it
        return 'yes'

    def _take_all_mov(self, temp_records):
        """
        MOV for a 'take all' offer = the SELLING value of the whole basket.

        The supplier is selling the entire stock as one lot, so the minimum
        order value is simply what that lot is worth to us:
            sum(available units x selling price per unit)
        selling_price_2 is already supplier price x (1 + default margin) in the
        price-list currency, so the profit is included by construction and the
        margin stays defined in exactly one place (the config parameter).

        Returns (mov_with_margin, mov_base) - both rounded UP to the nearest
        1000, or (None, None) when the rows carry no usable quantities/prices.
        """
        gross, base = 0.0, 0.0
        for rec in temp_records or []:
            try:
                qty = float(rec.get('availabale_qty') or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty <= 0:
                continue
            try:
                sell = float(rec.get('selling_price_2') or 0)
                cost = float(rec.get('supplier_unit_price') or 0)
            except (TypeError, ValueError):
                continue
            gross += qty * sell
            base += qty * cost
        if gross <= 0:
            return None, None
        return float(self._round_up_to(gross, 1000)), float(self._round_up_to(base, 1000))

    @staticmethod
    def _row_lead_time_weeks(temp_records):
        """Slowest per-row lead time, in whole weeks, or None when the rows
        carry none. Values are already standardised to 'n Week(s)' at row level,
        so only the number has to be read back."""
        weeks = []
        for rec in temp_records or []:
            m = re.search(r'(\d+)\s*week', str(rec.get('lead_time') or ''), re.IGNORECASE)
            if m:
                weeks.append(int(m.group(1)))
        return max(weeks) if weeks else None

    def _default_mov_amount(self, template, temp_records):
        """Last fallback: a default MOV amount (raw number) in the list currency.
        Reads oe_sbs.default_mov (e.g. '5000'); falls back to 5000."""
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            return float(ICP.get_param('oe_sbs.default_mov', '5000'))
        except (TypeError, ValueError):
            return 5000.0

    def _incoterm_fixed_text(self, template):
        """
        Build the offer's incoterm text from the template's FIXED incoterm.

        Uses the 3-letter CODE ('FCA'), not the descriptive name
        ('Free Carrier'), for two reasons:
          * it is what standardize_incoterm() writes for incoterms read from
            the file, so both paths produce one consistent value instead of
            two spellings of the same thing;
          * account.incoterms.name is translatable, so it would change with
            the user's language, while the code never does.
        Output shape matches standardize_incoterm(): 'CODE: Country(City)'.
        """
        if not template.incoterm_id:
            return None
        code = (template.incoterm_id.code or template.incoterm_id.name or '').strip()
        country = (template.incoterm_country_id.name
                   if template.incoterm_country_id else None)
        city = (template.incoterm_city or '').strip() or None
        if country and city:
            return f"{code}: {country}({city})"
        if country:
            return f"{code}: {country}"
        if city:
            return f"{code}: {city}"
        return code

    def _moq_failure_reason(self, moq_value, num, unit, temp_records):
        """
        Explain, in the rejection message, WHY an MOQ could not be turned into
        a carton count - so the user knows what to fix instead of guessing.
        """
        raw = str(moq_value).strip()
        if not num:
            return _("no quantity could be read from '%s'.", raw)
        if unit in ('pallet', 'layer'):
            ratio_name = _("Case/Pallet") if unit == 'pallet' else _("Case/Layer")
            unit_word = _("pallets") if unit == 'pallet' else _("layers")
            alt = (_("'Unit/Pallet' + 'Unit/Case'") if unit == 'pallet'
                   else _("'Unit/Layer' + 'Unit/Case'"))
            return _(
                "MOQ is '%(raw)s' but no %(ratio)s value exists in this file, "
                "so %(units)s cannot be turned into cartons. Map the "
                "'%(ratio)s' column (or %(alt)s) in the column mapping, "
                "then use Retry.",
                raw=raw, ratio=ratio_name, units=unit_word, alt=alt)
        if unit in ('unit', 'piece'):
            return _(
                "MOQ '%s' is expressed in single units/pieces, and this file "
                "gives no case size to convert them with. Map the 'Case Size' "
                "column (units per case) in the column mapping, then use Retry.",
                raw)
        return _(
            "the unit of MOQ '%s' was not recognised (expected cases, "
            "cartons, pallets or layers).", raw)

    def _resolve_offer_fields(self, found, template, temp_records, country_lookup=None):
        """
        found:        result of pre_ai_extract (+ AI)
        temp_records: all processed rows
        Output: (resolved_dict, actions_list)
        """
        resolved, actions = {}, []

        def from_fixed(fkey):
            ff = DYNAMIC_FIELDS[fkey].get('fixed_field')
            if not ff or not hasattr(template, ff):
                return None
            val = getattr(template, ff)
            if not val:
                return None
            fo = template._fields.get(ff)
            if fo and fo.type == 'many2one':
                return val.name
            if fo and fo.type == 'selection':
                return dict(fo.selection).get(val, val)
            return val

        # MOQ (+ MOQ->MOV correction: currency symbol or 'k' = monetary value, not a quantity)
        moq_value = found.get('moq', {}).get('value') or from_fixed('moq')

        # 'MOQ: Take all' is not a quantity - it means the supplier only sells
        # the WHOLE basket. Converting it to cartons is impossible and used to
        # abort the whole import with "MOQ could not be converted to cartons".
        # Such an offer has no MOQ at all; its minimum is the basket value, so
        # hand the decision straight over to the MOV branch below.
        take_all = _is_take_all(moq_value) or _is_take_all(found.get('mov', {}).get('value'))
        if take_all:
            moq_value = None
            found.pop('moq', None)
            if _is_take_all(found.get('mov', {}).get('value')):
                found.pop('mov', None)

        if moq_value and _is_monetary(moq_value):
            # An explicit 'MOQ <money>' (e.g. 'MOQ 33.000€') is the supplier's
            # binding minimum order VALUE and OVERRIDES a weaker MOV candidate.
            # This used to be a setdefault(), which silently dropped it whenever
            # MOV had already been filled from a vaguer label - e.g. a
            # 'Min / Max Order Value ... 7.000€/12.000€' range, where only the
            # LOW end of the range was picked up.
            prev = found.get('mov', {}).get('value')
            if prev and not _is_monetary(prev):
                found.setdefault('mov', {'value': moq_value, 'method': 'moq_to_mov'})
            else:
                found['mov'] = {'value': moq_value, 'method': 'moq_to_mov'}
            moq_value = None
        if moq_value:
            # Standardize MOQ to a CASE count: an MOQ in pallets/layers is
            # multiplied by the largest Case/Pallet (or Case/Layer) across the
            # offer. e.g. '10 Pallet' with max Case/Pallet 32 -> '320 Case'.
            _num, _unit = parse_moq_quantity(moq_value)
            cases = compute_moq_in_cases(_num, _unit, temp_records)
            if cases:
                resolved['moq'] = "%d Case" % cases
            else:
                # Previously the raw text was kept ('10 pallet'), which silently
                # produced an MOQ nobody could act on downstream. An MOQ that
                # cannot be expressed in cartons is a blocking data problem, so
                # the file is rejected with the actual cause.
                # NOTE: keep the word "template" OUT of these messages - the
                # caller routes any error mentioning it to the 'no_template'
                # state instead of 'reject'.
                raise UserError(_(
                    "MOQ could not be converted to cartons: %s",
                    self._moq_failure_reason(moq_value, _num, _unit, temp_records)))

        # price-list currency used to normalize MOV (from the records)
        price_cur = False
        if temp_records and temp_records[0].get('currency_id'):
            price_cur = self.env['res.currency'].browse(temp_records[0]['currency_id'])
        price_sym = self._sym(price_cur) if price_cur else '$'

        # MOV resolution (per the new algorithm). MOV is now a Monetary value,
        # so we store a raw number (in the price-list currency), not text:
        #   1. MOV found directly -> MOV = (1 + margin) * MOV, rounded up to 1000
        #   2. else if MOQ is present -> MOQ is recorded, MOV stays empty
        #   3. else (no MOV and no MOQ) -> MOV = default
        mov_from_file = found.get('mov', {}).get('value')
        mov_value = mov_from_file or from_fixed('mov')
        if take_all and not mov_from_file:
            ta_mov, ta_base = self._take_all_mov(temp_records)
            if ta_mov:
                resolved['mov'] = ta_mov
                resolved['mov_base'] = ta_base
                _logger.info("[SBS] 'take all' offer: MOV set to the full basket "
                             "selling value %s (cost basis %s).", ta_mov, ta_base)
            else:
                resolved['mov'] = self._default_mov_amount(template, temp_records)
                resolved['mov_base'] = resolved['mov']
                _logger.warning("[SBS] 'take all' offer but no usable quantities/"
                                "prices - fell back to the default MOV.")
        elif mov_from_file:
            resolved['mov'] = self._mov_to_number(mov_from_file, apply_margin=True)
            # keep the raw (pre-margin) amount so MOV can be recomputed later
            resolved['mov_base'] = self._mov_to_number(mov_from_file, apply_margin=False)
        elif resolved.get('moq'):
            # The file states an MOQ, so THAT is the minimum this supplier
            # accepts and the offer has no MOV. This has to win over the
            # template's fixed MOV and over the computed default as well: both
            # exist for files that state neither, and filling them in alongside
            # a real MOQ invented a second, contradictory minimum.
            _logger.info("[SBS] MOQ %s stated in the file - MOV left empty.",
                         resolved['moq'])
        elif mov_value:
            resolved['mov'] = self._mov_to_number(mov_value, apply_margin=True)
            resolved['mov_base'] = self._mov_to_number(mov_value, apply_margin=False)
        else:
            resolved['mov'] = self._default_mov_amount(template, temp_records)
            # default already has no margin notion; treat it as its own base
            resolved['mov_base'] = resolved['mov']

        # Payment Terms
        pay = (found.get('payment_term', {}).get('value') or from_fixed('payment_term')
               or DYNAMIC_FIELDS['payment_term']['fallback_value'])
        pay = str(pay).strip()
        # Business rule: the advance/deposit percentage must be at least 30%. If
        # the supplier states a lower advance (e.g. '20% in advance, 80% ...'),
        # bump the FIRST percentage up to 30% and keep the rest of the text.
        pm = re.search(r'(\d+(?:\.\d+)?)\s*%', pay)
        if pm:
            try:
                pct = float(pm.group(1))
            except ValueError:
                pct = None
            if pct is not None and pct < 30:
                # replace only the first percentage occurrence with 30%
                pay = pay[:pm.start(1)] + '30' + pay[pm.end(1):]
        # A cell reading 'Deposit 20%' yields just '20%' once the label is
        # stripped, which is meaningless on its own - say what the percentage IS.
        if re.fullmatch(r'\d+(?:\.\d+)?\s*%', pay):
            pay = "%s Deposit" % pay
        resolved['payment_term'] = pay

        # Offer Validity (in weeks)
        ov = found.get('offer_validity', {}).get('value') or from_fixed('offer_validity')
        weeks = _extract_weeks(ov) if ov else None
        resolved['_offer_weeks'] = weeks or DYNAMIC_FIELDS['offer_validity']['fallback_value']

        # Lead Time -> 'n Week(s)'; keep non-numeric text (e.g. 'In stock');
        # default to 4 Weeks only when nothing was found at all.
        lt = found.get('lead_time', {}).get('value') or from_fixed('lead_time')
        if lt:
            std = standardize_lead_time(lt)
            resolved['lead_time'] = std if std else str(lt).strip()
        else:
            # Some suppliers give the lead time PER PRODUCT, as a table column,
            # and say nothing about it around the table. The metadata scan can
            # never see it (a full column is table data, not metadata), so the
            # offer used to fall back to the default even though the file stated
            # it on every row. Take the SLOWEST row: the offer as a whole can
            # only be promised at the speed of its slowest line.
            row_weeks = self._row_lead_time_weeks(temp_records)
            if row_weeks:
                resolved['lead_time'] = "%d Week%s" % (row_weeks,
                                                       '' if row_weeks == 1 else 's')
                _logger.info("[SBS] offer lead time taken from the per-row column: "
                             "%s (slowest of %s rows).",
                             resolved['lead_time'], len(temp_records or []))
            else:
                resolved['lead_time'] = DYNAMIC_FIELDS['lead_time']['fallback_value']

        # T1/T2
        # Customs status: three independent answers. A fixed value on the
        # template is already 'yes'/'no'/'available', so it is used as-is.
        for key, token_re, avail in (
                ('t1', re.compile(r'\bT1\b', re.IGNORECASE), False),
                ('t2', re.compile(r'\bT2\b|eu[\s\-+/]*(?:clean(?:ed)?|clear(?:ed|ance)?)|clean(?:ed)?[\s\-+/]*eu', re.IGNORECASE), True),
                ('euro1', re.compile(r'\beur\.?\s*1\b|\beuro\s*1\b', re.IGNORECASE), False)):
            fixed = from_fixed(key)
            if fixed:
                resolved[key] = fixed
                continue
            raw_val = found.get(key, {}).get('value')
            resolved[key] = self._resolve_yes_no(raw_val, token_re,
                                                 allow_available=avail)

        # Incoterms -> 'CODE: Country(City)'  (if found nowhere -> email action)
        inc = found.get('incoterms', {}).get('value')
        if inc:
            _logger.info("[SBS] Incoterms read from the file (%s): %r",
                         found.get('incoterms', {}).get('addr'), inc)
        else:
            inc = self._incoterm_fixed_text(template)
            if inc:
                # Nothing in the file - this value comes from the TEMPLATE's fixed
                # incoterm. Logged explicitly because an incoterm appearing on an
                # offer whose file never mentioned one is otherwise unexplainable.
                _logger.info("[SBS] Incoterms absent from the file; using the "
                             "template's fixed incoterm: %r", inc)
        if inc:
            city_lookup = self._build_city_lookup()
            resolved['incoterms'] = self.standardize_incoterm(
                inc, country_lookup, city_lookup) or str(inc).strip()

            # The file may name the TERM but not the PLACE - 'Quoted Ex works'
            # with nothing after it, or a place spelling the lookup can't
            # resolve. When that happens and the template carries a fixed
            # incoterm with the SAME code, take the place from the template
            # instead of storing a bare 'EXW'. The file still wins on the term
            # itself; only the missing half is filled in.
            if ':' not in str(resolved['incoterms']):
                fixed_text = self._incoterm_fixed_text(template)
                if fixed_text and ':' in fixed_text:
                    fixed_code = fixed_text.split(':', 1)[0].strip().upper()
                    if fixed_code == str(resolved['incoterms']).strip().upper():
                        _logger.info(
                            "[SBS] file gave the incoterm code but no place; "
                            "completing it from the template: %r", fixed_text)
                        resolved['incoterms'] = fixed_text
        else:
            actions.append({
                'type': 'email_supplier',
                'field': 'incoterms',
                'supplier_id': template.supplier_id.id if template.supplier_id else False,
            })

        # Offer-level facts the file never stated. T1/T2 in particular is very
        # often missing or given only as a field label, and an empty value is
        # easy to miss on a freshly imported offer - so the wizard reports them
        # instead of leaving the user to spot the blanks.
        UNSTATED_LABELS = {
            't1': 'T1 (customs status)',
            't2': 'T2 / EU Clean',
            'euro1': 'EUR.1 certificate',
            'incoterms': 'Incoterms',
            'moq': 'MOQ',
            'mov': 'MOV',
            'payment_term': 'Payment Terms',
        }
        unstated = [label for key, label in UNSTATED_LABELS.items()
                    if not resolved.get(key)]
        if not found.get('lead_time', {}).get('value') and not from_fixed('lead_time') \
                and resolved.get('lead_time') == DYNAMIC_FIELDS['lead_time']['fallback_value']:
            unstated.append('Lead Time (default %s applied)'
                            % DYNAMIC_FIELDS['lead_time']['fallback_value'])
        if unstated:
            actions.append({'type': 'unstated_fields', 'fields': unstated})
            _logger.info("[SBS] offer fields not stated in the file: %s",
                         ', '.join(unstated))

        return resolved, actions

    def _queue_incoterms_email(self, action, import_number=None):
        """Incoterms not found -> must ask the supplier (currently log only)."""
        supplier_id = action.get('supplier_id')
        if not supplier_id:
            _logger.info("[SBS] Incoterms missing, no supplier to email.")
            return
        _logger.info("[SBS] Incoterms missing for supplier %s — email needed (import %s).",
                     supplier_id, import_number)
        # TODO: send email via mail.template or create a mail.activity

    # =================================================================
    # onchange and template helpers
    # =================================================================
    @api.onchange('template_id')
    def _onchange_template_id(self):
        """Auto-fill sheet name when template is selected"""
        if self.template_id:
            self.sheet_name = self.template_id.sheet_name or 'climax'

    def _get_template_column_mapping(self):
        """Build column mapping from template lines"""
        if not self.template_id:
            return {}
        mapping = {}
        for line in self.template_id.line_ids:
            mapping[line.excel_column.strip().lower()] = line.field_name
        return mapping

    def _get_template_required_columns(self):
        """Get list of required columns from template"""
        if not self.template_id:
            return []
        required = []
        for line in self.template_id.line_ids:
            if line.is_required:
                required.append(line.excel_column.strip().lower())
        return required

    def _safe_unidecode(self, text):
        result = ""
        for i, ch in enumerate(text):
            converted = unidecode(ch)
            # if output is a single char wrongly upper-cased, fix it
            if len(converted) == 1 and ch.islower() and converted.isupper():
                result += converted.lower()
            else:
                result += converted
        return result

    def _parse_accounting_number(self, cell):
        """Parse Excel cells with flexible currency and accounting formats."""
        try:
            # --- 1. Extract raw_value safely ---
            if hasattr(cell, "value"):  # a real cell object
                raw_value = cell.value
                fmt = getattr(cell, "number_format", "") or ""
            else:  # a plain str or number was passed
                raw_value = cell
                fmt = ""

            if raw_value is None or raw_value == "":
                return 0.0, False

            fmt_lower = fmt.lower()
            currency_id = False
            code = None

            # --- 2. Currency from number_format symbol or value string ---
            # works for symbols (€ $ £) and 3-letter codes (EUR/USD/GBP/AED)
            hint = f"{fmt} {raw_value}" if isinstance(raw_value, str) else fmt
            if '€' in hint or re.search(r'\beur\b|euro', hint, re.IGNORECASE):
                code = 'EUR'
            elif '£' in hint or re.search(r'\bgbp\b|pound|sterling', hint, re.IGNORECASE):
                code = 'GBP'
            elif re.search(r'\baed\b|dirham', hint, re.IGNORECASE):
                code = 'AED'
            elif '$' in hint or re.search(r'\busd\b|dollar', hint, re.IGNORECASE):
                code = 'USD'

            if code:
                cur = self.env['res.currency'].with_context(active_test=False).search(
                    [('name', '=', code)], limit=1)
                currency_id = cur.id if cur else False

            # --- 3. Extract numeric value ---
            amount = 0.0
            if isinstance(raw_value, (int, float)):
                amount = float(raw_value)
            elif isinstance(raw_value, str):
                negative = '(' in raw_value and ')' in raw_value
                amount = self._smart_parse_number(raw_value) or 0.0
                if negative:
                    amount = -abs(amount)

            # --- 4. Handle negative from number format ---
            if '(' in fmt and amount > 0:
                amount = -amount

            return amount, currency_id

        except Exception:
            return 0.0, False

    @staticmethod
    def _smart_parse_number(s):
        """Parse a number string handling both European (8,79) and US (1,234.56) formats."""
        s = re.sub(r'[^\d,.\-]', '', str(s))
        if not s:
            return None
        has_comma, has_dot = ',' in s, '.' in s
        if has_comma and has_dot:
            if s.rfind(',') > s.rfind('.'):       # comma last -> European: 1.234,56
                s = s.replace('.', '').replace(',', '.')
            else:                                  # dot last -> US: 1,234.56
                s = s.replace(',', '')
        elif has_comma:
            parts = s.split(',')
            if len(parts[-1]) == 2:                # 2 digits after comma -> decimal (8,79)
                s = s.replace(',', '.')
            else:                                  # thousands separator (1,234)
                s = s.replace(',', '')
        try:
            return float(s)
        except ValueError:
            return None

    def excel_date_to_str(self, value):
        try:
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            elif isinstance(value, (int, float)):
                value = int(value)
            else:
                return value  # not a date at all
            base_date = datetime(1899, 12, 30)
            date_obj = base_date + timedelta(days=value)
            return date_obj.strftime("%d/%m/%Y")
        except Exception:
            return value

    def _get_or_create_uom(self, factor, name_prefix='Case'):
        """
        Find or create a UOM with the given relative factor (Odoo 19 tree-based).
        name_prefix lets callers label it, e.g. 'Case: 12', 'Layer: 72',
        'Pallet: 720'. A factor <= 1 returns the base Unit.
        """
        UoM = self.env['uom.uom']
        try:
            unit_uom = self.env.ref('uom.product_uom_unit')
        except ValueError:
            unit_uom = UoM.search([
                ('relative_uom_id', '=', False),
                ('relative_factor', '=', 1.0),
            ], limit=1)

        if not unit_uom:
            _logger.warning("[SBS UOM] Base Unit of Measure not found.")
            return False

        if not factor or int(factor) <= 1:
            return unit_uom

        factor_float = float(int(factor))

        # match an existing UOM with this factor and the same name prefix, so
        # 'Pack of 72' and 'Layer of 72' can coexist for the same factor.
        uom = UoM.search([
            ('relative_uom_id', '=', unit_uom.id),
            ('relative_factor', '=', factor_float),
            ('name', '=', f'{name_prefix}: {int(factor)}'),
        ], limit=1)

        if not uom:
            try:
                uom = UoM.sudo().create({
                    'name': f'{name_prefix}: {int(factor)}',
                    'relative_uom_id': unit_uom.id,
                    'relative_factor': factor_float,
                })
                _logger.info(
                    "[SBS UOM] New UOM created: '%s' (id=%s, factor=%s)",
                    uom.name, uom.id, factor_float
                )
            except Exception as e:
                _logger.warning("[SBS UOM] Failed to create UOM: %s", e)
                return unit_uom

        return uom

    def _sync_uom_to_product(self, product_tmpl, uom):
        """Add the UOM to product.template.uom_ids (Many2many)."""
        if not product_tmpl or not uom:
            return

        if product_tmpl.uom_id.id == uom.id:
            _logger.debug(
                "[SBS UOM] UOM '%s' is the default UOM of product '%s' — skipping",
                uom.name, product_tmpl.name
            )
            return

        if uom in product_tmpl.uom_ids:
            _logger.debug(
                "[SBS UOM] UOM '%s' already in uom_ids of product '%s' — skipping",
                uom.name, product_tmpl.name
            )
            return

        try:
            product_tmpl.sudo().write({'uom_ids': [(4, uom.id)]})
            _logger.info(
                "[SBS UOM] UOM '%s' added to uom_ids of product '%s' (id=%s)",
                uom.name, product_tmpl.name, product_tmpl.id
            )
        except Exception as e:
            _logger.warning(
                "[SBS UOM] Failed to add UOM '%s' to product '%s': %s",
                uom.name, product_tmpl.name, e
            )

    # =================================================================
    # Main import
    # =================================================================
    def _read_source_file(self):
        """
        Return (file_content, is_json) for this wizard's source.

        Extracted so the manual-send template picker can score the very
        same bytes the import will read - including the .xls conversion,
        which changes the column layout the scorer sees.
        """
        if not self.from_doc:
            file_content = base64.b64decode(self.file)
            is_json = False
        else:
            mimetype = self.document_id.mimetype
            doc_name = (self.document_id.name or '').lower()
            if mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                file_content = base64.b64decode(self.document_id.datas)
                is_json = False
            elif mimetype in ('application/vnd.ms-excel', 'application/excel') \
                    or doc_name.endswith('.xls'):
                # legacy .xls -> convert to .xlsx bytes in memory
                file_content = base64.b64decode(self.document_id.datas)
                is_json = False
            elif mimetype == 'application/o-spreadsheet':
                file_content = self.document_id.export_final_xlsx()
                is_json = True
            else:
                # Unknown mimetype: peek at the bytes. A legacy .xls (OLE2) or a
                # zip-based .xlsx can arrive as application/octet-stream etc.,
                # so accept it when the content clearly looks like a spreadsheet.
                raw = base64.b64decode(self.document_id.datas)
                if _looks_like_xls(raw) or raw[:2] == b'PK':   # OLE2 (.xls) or ZIP (.xlsx)
                    file_content = raw
                    is_json = False
                else:
                    raise UserError(_('Unsupported document type: %s') % mimetype)

        # If this is an old .xls (or got served as one), convert to xlsx bytes
        if not is_json and _looks_like_xls(file_content):
            try:
                file_content = _xls_to_xlsx_bytes(file_content)
            except Exception as e:
                raise UserError(_(
                    'Could not read this .xls file. Please re-save it as .xlsx '
                    'and try again. (%s)') % e)

        return file_content, is_json

    def _score_all_templates(self, file_content, is_json, available_templates):
        """
        Score EVERY candidate template against the file and return them all,
        best first, as [(template, score, sheet_data), ...].

        Both the import itself and the manual-send template picker need these
        scores. Returning the full ranked list instead of just the winner is
        what lets the picker exist without a second, drifting copy of the
        matching rules: there is one scorer, and the picker simply shows what it
        found rather than re-deciding.

        Templates that do not match at all (score <= 0) are left out - offering
        one would only produce a column error further down.
        """
        scored = []
        if is_json:
            data = file_content if isinstance(file_content, dict) else json.loads(file_content)
            sheets = data.get("sheets", [])

            for t in available_templates:
                # print("tttttttttttttttttttttttttttttttttttttttttttttt")
                # print(t)

                t_sheet_name = t.sheet_name.strip().lower() if getattr(t, 'sheet_name', False) else None
                if t_sheet_name:
                    sheet = next((s for s in sheets if s["name"].strip().lower() == t_sheet_name), None)
                else:
                    sheet = sheets[0] if sheets else None

                if not sheet:
                    continue

                cells = sheet.get("cells", {})

                def get_json_val(cell_data):
                    if isinstance(cell_data, dict):
                        return cell_data.get("content", "")
                    return str(cell_data) if cell_data else ""

                temp_sheet_data = []
                max_row = sheet.get("rowNumber", 100)
                max_col = 50
                for r in range(1, max_row + 1):
                    row_vals = []
                    for c in range(1, max_col + 1):
                        col_letter = chr(64 + c) if c <= 26 else chr(64 + c // 26) + chr(64 + c % 26)
                        key = f"{col_letter}{r}"
                        row_vals.append(get_json_val(cells.get(key, "")))
                    temp_sheet_data.append(row_vals)

                # Score this template; keep the highest-scoring valid one.
                score = score_template_headers(t, temp_sheet_data)
                if score > 0:
                    scored.append((t, score, temp_sheet_data))

            # print("TTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTT")
            # print(template)

        else:  # XLSX mode
            try:
                workbook = load_workbook(filename=BytesIO(file_content), data_only=True)
                # Fill merged cells in the DATA area only. We don't know the final
                # template yet, so use the smallest header_row among candidate
                # templates (default 1) - metadata merges above that are left
                # alone, data merges at/below it get filled.
                hr_candidates = [int(t.header_row) for t in available_templates
                                 if getattr(t, 'header_row', None)]
                unmerge_header_row = min(hr_candidates) if hr_candidates else 1
                _sbs_unmerge_fill(workbook, header_row=unmerge_header_row)
            except Exception as e:
                # Some files embed images/drawings that the normal reader chokes on;
                # read_only mode skips drawing parsing and still gives cell values.
                # (read_only can't unmerge, but such files rarely rely on merges.)
                _logger.warning("[SBS] load_workbook failed (%s); retrying in read_only mode.", e)
                workbook = load_workbook(filename=BytesIO(file_content),
                                         data_only=True, read_only=True)

            for t in available_templates:
                t_sheet_name = t.sheet_name.strip().lower() if getattr(t, 'sheet_name', False) else None
                if t_sheet_name:
                    sheet_name = next((n for n in workbook.sheetnames if n.strip().lower() == t_sheet_name), None)
                else:
                    sheet_name = workbook.sheetnames[0] if workbook.sheetnames else None

                if not sheet_name:
                    continue

                sheet = workbook[sheet_name]
                temp_sheet_data = []
                for row in sheet.iter_rows():
                    temp_sheet_data.append([cell.value for cell in row])

                # Score this template; keep the highest-scoring valid one
                # (a fully-valid template that matches more columns wins).
                score = score_template_headers(t, temp_sheet_data)
                if score > 0:
                    scored.append((t, score, temp_sheet_data))
        # A template created FROM this exact file wins outright, whatever its
        # score. Scores rank templates by how many headers line up, which is a
        # good guess when nothing better exists - but "this mapping was built
        # for this document" is not a guess, and a rival template with more
        # matching headers should not quietly displace it.
        doc = self.document_id
        if doc:
            def _own_doc(item):
                return 0 if item[0].document_id.id == doc.id else 1
            scored.sort(key=lambda x: (_own_doc(x), -x[1]))
            if scored and scored[0][0].document_id.id == doc.id:
                _logger.info("[SBS] template %s was created from this document "
                             "- preferred over the header score.",
                             scored[0][0].display_name)
        else:
            scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def action_import(self):
        self.ensure_one()
        if not self.from_doc and not self.file:
            raise UserError(_('Please upload a file first.'))
        if self.from_doc and not self.document_id:
            raise UserError(_('Please select a file first.'))

        imported_count = 0
        validation_errors = []
        temp_records = []
        import_date = date.today()

        # =================================================================
        # 1. Read the file
        # =================================================================
        file_content, is_json = self._read_source_file()

        # =================================================================
        # 2. Find templates
        # =================================================================
        if hasattr(self, 'supplier_id') or not self.supplier_id:
            available_templates = self.env['sbs.import.template'].search([
                ('supplier_id', '=', self.supplier_id.id),
                ('active', '=', True)
            ])

        if not available_templates:
            available_templates = self.env['sbs.import.template'].search(
                [('active', '=', True), ('supplier_id', '=', False)])

        template = None
        sheet_data = []
        best_score = -1   # highest validate_template_headers score seen so far

        # print(self.supplier_id)
        # print(available_templates)
        # print("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFffffffffffffffffffffff")
        # print(is_json)

        # ── get_val ──
        def get_val(col_ref, current_row_idx_0_based):
            if not col_ref:
                return None
            c_idx = col_letter_to_index(col_ref)
            if c_idx is None:
                return None
            try:
                val = sheet_data[current_row_idx_0_based][c_idx]
                return val.value if hasattr(val, 'value') else val
            except IndexError:
                return None

        scored = self._score_all_templates(file_content, is_json,
                                           available_templates)

        # An explicit choice from the manual-send picker wins over the score.
        forced = self.env.context.get('sbs_forced_template_id')
        if forced:
            pick = next((x for x in scored if x[0].id == forced), None)
            if not pick:
                raise UserError(_(
                    "The selected mapping does not match this file's columns. "
                    "Pick another mapping or fix the template's headers."))
            template, best_score, sheet_data = pick
            _logger.info("[SBS] template forced by the user: %s (score %s).",
                         template.display_name, best_score)
        elif scored:
            template, best_score, sheet_data = scored[0]

        # no template matched
        if not template:
            raise UserError(_('No matching template found. Please ensure both the column '
                              'number and the expected column headers match the uploaded file.'))

        # Record which template matched so callers (RPC/controller) can store it
        # on the document (template_id is 'Template used').
        if self.template_id.id != template.id:
            self.with_context(sbs_no_learn=True).write({'template_id': template.id})

        # =================================================================
        # 3. setup: country map, metadata, start row
        # =================================================================
        country_lookup = self._build_country_lookup()
        scan_mode = self.env['ir.config_parameter'].sudo().get_param(
            'oe_sbs.metadata_scan_mode', 'outside')
        metadata_cells = extract_metadata_cells(sheet_data, template, scan_mode)

        start_row = int(getattr(template, 'header_row', 1) or 1) + 1

        # --- Offer-level currency from metadata (e.g. "Prices in EUR") ---
        # Used only as a fallback when a row's price cell has no currency symbol.
        offer_currency_id = None
        cur_fields = {'currency': DYNAMIC_FIELDS['currency']}
        cur_found = pre_ai_extract(metadata_cells, cur_fields)
        cur_hint = cur_found.get('currency', {}).get('value')
        if not cur_hint:
            # bare-symbol fallback: scan metadata for any currency token
            for c in metadata_cells:
                if self._detect_currency_id(c['value']):
                    cur_hint = c['value']
                    break
        if not cur_hint:
            # currency is often embedded in the price column header (e.g. "PIECE PRICE €")
            header_row_idx = int(getattr(template, 'header_row', 1) or 1) - 1
            price_idx = col_letter_to_index(template.price_col) if template.price_col else None
            if price_idx is not None and 0 <= header_row_idx < len(sheet_data):
                hdr_row = sheet_data[header_row_idx]
                if price_idx < len(hdr_row) and self._detect_currency_id(hdr_row[price_idx]):
                    cur_hint = hdr_row[price_idx]
        if not cur_hint:
            # last resort: currency symbol embedded in the price column's cell FORMAT
            # (e.g. a cell showing "€0.70" whose stored value is just 0.70).
            offer_currency_id = self._currency_from_price_format(file_content, template)
        if cur_hint:
            offer_currency_id = self._detect_currency_id(cur_hint)

        # --- helper functions ---
        def get_final_val(col_ref, fixed_val, current_row_idx):
            val = get_val(col_ref, current_row_idx) if col_ref else None
            if val not in (False, None, ''):
                return val
            if fixed_val not in (False, None, ''):
                return fixed_val
            return None

        def parse_date_value(val, fmt_list=("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y")):
            if not val:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, date):
                return datetime.combine(val, datetime.min.time())
            for fmt in fmt_list:
                try:
                    return datetime.strptime(str(val).strip(), fmt)
                except ValueError:
                    continue
            return None

        SBSData = self.env['sbs.data']
        if SBSData.with_context(prefetch_fields=False).search([('excel_filename', '=', self.file_name)]):
            raise UserError(_('File Already Exist!'))

        valid_currency_ids = self.env['res.currency'].search([]).ids
        ICP = self.env['ir.config_parameter'].sudo()
        margin = float(ICP.get_param('oe_sbs.default_profit_margin', '8')) / 100
        min_margin = float(ICP.get_param('oe_sbs.min_profit_margin', '7')) / 100
        usd_currency = self.env.ref('base.USD')

        # --- Brand source ---------------------------------------------------
        # template.brand_col is a "Brand Cell": it accepts either a plain COLUMN
        # letter ('A' = one brand per row) or an ABSOLUTE cell reference ('B2' =
        # a single brand for the whole file). Single-brand suppliers write their
        # brand once above the table and give the products a bare description;
        # without the absolute form every row imported with no brand at all.
        # Known brands. Used twice: to tell a BRAND caption row apart from a
        # plain category caption, and to pull the brand out of a decorated
        # heading (below).
        brand_names = {}
        if 'product.brand' in self.env:
            for b in self.env['product.brand'].with_context(active_test=False).search([]):
                if b.name:
                    brand_names[b.name.strip().lower()] = b.name

        def _match_brand(text):
            """
            Resolve a heading to a known brand.

            Exact match first. Failing that, look for a known brand INSIDE the
            text: a file-level brand cell is usually a title rather than a bare
            brand - 'SHISEIDO XMAS SETS', 'FENTY BEAUTY - Offer List' - and an
            exact-only match left every one of those rows with no brand at all.
            The longest known brand wins so 'Fenty Skin' beats 'Fenty'.
            """
            raw = re.sub(r'\s+', ' ', str(text or '')).strip()
            if not raw:
                return None
            exact = brand_names.get(raw.lower())
            if exact:
                return exact
            low = raw.lower()
            hits = [name for key, name in brand_names.items()
                    if len(key) >= 3 and re.search(r'\b%s\b' % re.escape(key), low)]
            if hits:
                return max(hits, key=len)
            return None

        brand_col_letter, brand_fixed_row = _parse_cell_ref(
            getattr(template, 'brand_col', False))
        current_brand = None
        if brand_col_letter and brand_fixed_row:
            _bv = get_val(brand_col_letter, brand_fixed_row - 1)
            if _bv not in (None, ''):
                current_brand = _match_brand(_bv) or str(_bv).strip()
                _logger.info("[SBS Brand] file-level brand %r read from %s%s (cell: %r)",
                             current_brand, brand_col_letter, brand_fixed_row,
                             str(_bv).strip())

        for row_idx_0_based in range(start_row - 1, len(sheet_data)):
            row_index = row_idx_0_based + 1
            row_vals_list = sheet_data[row_idx_0_based]

            # fully empty row -> skip
            if not any(val not in (None, '') for val in row_vals_list):
                continue

            # both EAN and product name empty -> skip
            ean_check = get_val(template.ean_col, row_idx_0_based)
            desc_check = get_val(template.product_name_col, row_idx_0_based)
            if not ean_check and not desc_check:
                continue

            # A caption row: a description with no EAN. When it names a brand
            # that already exists in product.brand it switches the brand for
            # every row below it; otherwise it is only a category caption
            # ('Killawatt Highlighter', 'ACCESORIES'). Either way it is not a
            # product, so it is skipped instead of being reported as a row with
            # a missing EAN.
            if not ean_check:
                caption = str(desc_check).strip()
                known_brand = _match_brand(caption)
                if known_brand:
                    current_brand = known_brand
                    _logger.info("[SBS Brand] brand switches to %r at row %s",
                                 known_brand, row_index)
                continue
            fixed_brand_name = current_brand

            record_vals = {'excel_filename': self.file_name}
            row_errors = []

            # --- supplier ---
            if template.supplier_id:
                record_vals['supplier_id'] = template.supplier_id.id
                record_vals['supplier_name'] = template.supplier_id.name
                if hasattr(template.supplier_id, 'partner_code'):
                    record_vals['supplier_code'] = template.supplier_id.partner_code
            else:
                record_vals['supplier_id'] = False
                if hasattr(template, 'supplier_code_col') and template.supplier_code_col:
                    record_vals['supplier_code'] = get_val(template.supplier_code_col, row_idx_0_based)

            # --- EAN / Barcode ---
            ean_raw = get_val(template.ean_col, row_idx_0_based)
            # numbers may arrive as int or float (e.g. 5999109582843.0) -> normalize
            if isinstance(ean_raw, float) and ean_raw.is_integer():
                ean_val = str(int(ean_raw))
            elif isinstance(ean_raw, int):
                ean_val = str(ean_raw)
            else:
                ean_val = str(ean_raw or '').strip()
            # drop a trailing '.0' if any slipped through, and surrounding spaces
            ean_val = re.sub(r'\.0$', '', ean_val).strip()
            if not ean_val:
                row_errors.append("Missing EAN (barcode)")
            elif not ean_val.isdigit():
                row_errors.append(f"Invalid EAN (non-numeric): {ean_val}")
            elif len(ean_val) > 13:
                row_errors.append(f"Invalid EAN length > 13: {ean_val}")
            else:
                record_vals['ean'] = ean_val.zfill(13)

            # --- Product Name ---
            desc_val = get_val(template.product_name_col, row_idx_0_based)
            if not desc_val:
                row_errors.append("Missing product name")
            else:
                record_vals['product_name'] = unidecode(str(desc_val).strip()).title()

            # --- Price & Currency ---
            # Unit price comes from the Price column. If that isn't mapped/empty
            # but a Case Price column is, derive the unit price as
            # case_price / Unit-per-Case. A mapped unit Price always wins.
            price_val = get_val(template.price_col, row_idx_0_based) \
                if getattr(template, 'price_col', False) else None
            price_value, currency_id = self._parse_accounting_number(price_val)

            used_case_price = False
            if (price_value is None or price_value == 0) \
                    and getattr(template, 'case_price_col', False):
                case_val = get_val(template.case_price_col, row_idx_0_based)
                case_price, case_cur = self._parse_accounting_number(case_val)
                # packaging fields are read later in this loop, so read Unit/Case
                # straight from its column here.
                units_per_case = 0
                if getattr(template, 'case_size_col', False):
                    units_per_case = _parse_pack_count(
                        get_val(template.case_size_col, row_idx_0_based))
                if case_price and units_per_case:
                    price_value = case_price / units_per_case
                    if case_cur and not currency_id:
                        currency_id = case_cur
                    used_case_price = True

            # If the price cell had no currency symbol, fall back to the
            # offer-level currency detected from the metadata region.
            if not currency_id and offer_currency_id:
                currency_id = offer_currency_id

            if not currency_id or currency_id not in valid_currency_ids or price_value is None or price_value == 0:
                _cs_mapped = getattr(template, 'case_size_col', False)
                if getattr(template, 'case_price_col', False) and not getattr(template, 'price_col', False) and not _cs_mapped:
                    row_errors.append("Case Price is mapped but Unit/Case (case "
                                      "size) is missing, so unit price can't be "
                                      "computed for this row")
                else:
                    row_errors.append("Invalid or missing price/currency "
                                      "(no symbol in price cell and no currency found in the file header)")
            else:
                record_vals['supplier_unit_price'] = abs(price_value)
                record_vals['currency_id'] = currency_id

            # --- Available QTY ---
            # Prefer Available Qty in units. If absent, derive it from Available
            # Case x Unit/Case, or Available Pallet x Unit/Pallet. Packaging cols
            # are read later in this loop, so read them straight from their
            # columns here.
            avail_val = get_val(template.available_qty_col, row_idx_0_based) \
                if getattr(template, 'available_qty_col', False) else None
            avail_units = None
            if avail_val not in (None, ''):
                val_str = str(avail_val).strip()
                if re.search(r'(€|\$|£|aed)', val_str, re.IGNORECASE):
                    row_errors.append(f"Row {row_index}: Available Units must not contain currency symbols")
                else:
                    try:
                        avail_units = float(val_str)
                    except ValueError:
                        row_errors.append(f"Row {row_index}: Available Units must be numeric")

            if avail_units is None and getattr(template, 'available_case_col', False):
                ac = _parse_pack_count(get_val(template.available_case_col, row_idx_0_based))
                cs = _parse_pack_count(get_val(template.case_size_col, row_idx_0_based)) \
                    if getattr(template, 'case_size_col', False) else 0
                if ac and cs:
                    avail_units = float(ac * cs)

            if avail_units is None and getattr(template, 'available_pallet_col', False):
                ap = _parse_pack_count(get_val(template.available_pallet_col, row_idx_0_based))
                upp = _parse_pack_count(get_val(template.unit_per_pallet_col, row_idx_0_based)) \
                    if getattr(template, 'unit_per_pallet_col', False) else 0
                if ap and upp:
                    avail_units = float(ap * upp)

            if avail_units is not None:
                record_vals['availabale_qty'] = avail_units

            # --- Optional fields ---
            # Note: hs_code and coo are intrinsic product attributes; they are
            # written onto the product (three-state) and read back via stored
            # related fields, so they are NOT written directly on sbs.data here.
            optional_fields = {
                'case_size': getattr(template, 'case_size_col', False),
                'layer': getattr(template, 'layer_col', False),
                'pallet': getattr(template, 'pallet_col', False),
                'note': getattr(template, 'note_col', False),
                # Batch / lot code, stored as the supplier wrote it. No date is
                # inferred from it: '04/25' could be a production month, an
                # expiry, or neither, and guessing wrong is worse than blank.
                'batch_code': getattr(template, 'batch_code_col', False),
                'unit_per_layer': getattr(template, 'unit_per_layer_col', False),
                'unit_per_pallet': getattr(template, 'unit_per_pallet_col', False),
            }
            for odoo_field, col_ref in optional_fields.items():
                if not col_ref:
                    continue
                val = get_val(col_ref, row_idx_0_based)
                if val not in (None, ''):
                    if odoo_field in ['case_size', 'layer', 'pallet', 'unit_per_layer', 'unit_per_pallet']:
                        record_vals[odoo_field] = _parse_pack_count(val)
                    else:
                        record_vals[odoo_field] = str(val).strip()

            # --- Packaging: derive missing ratios from the ones we have ---
            # Relationships (all integers):
            #   Unit/Layer  = Unit/Case * Case/Layer
            #   Unit/Pallet = Unit/Case * Case/Pallet
            # Any missing field is filled from the two others when derivable.
            # Existing (file-provided) values are NEVER overwritten - we only fill
            # blanks, so real supplier data always wins.
            _derive_packaging(record_vals)

            # --- HS Code (intrinsic -> stored on product, kept in a temp key) ---
            hs_raw = get_val(template.hs_code_col, row_idx_0_based) \
                if getattr(template, 'hs_code_col', False) else None
            if hs_raw not in (None, ''):
                record_vals['_hs_code'] = str(hs_raw).strip()

            # --- Cover Language (intrinsic -> stored on product, temp key) ---
            lang_raw = get_val(template.cover_language_col, row_idx_0_based) \
                if getattr(template, 'cover_language_col', False) else None
            if lang_raw not in (None, ''):
                record_vals['_cover_language'] = str(lang_raw).strip()

            # --- CoO (intrinsic -> stored on product as res.country, temp key) ---
            coo_raw = get_val(template.coo_col, row_idx_0_based) if template.coo_col else None
            if coo_raw not in (None, ''):
                record_vals['_coo_raw'] = coo_raw

            # --- Lead Time (per-row if a column is defined) ---
            lt_raw = get_val(template.lead_time_col, row_idx_0_based) \
                if getattr(template, 'lead_time_col', False) else None
            if lt_raw not in (None, ''):
                std_lt = standardize_lead_time(lt_raw)
                record_vals['lead_time'] = std_lt if std_lt else str(lt_raw).strip()

            # --- Product Expiry Date (per-row; the date printed on the pack) ---
            exp_raw = get_val(template.product_expiry_col, row_idx_0_based) \
                if getattr(template, 'product_expiry_col', False) else None
            if exp_raw not in (None, ''):
                exp_dt = parse_date_value(exp_raw)
                if exp_dt:
                    record_vals['product_expiry_date'] = exp_dt.date()

            # --- Brand (per-row; created/linked after the product is found) ---
            if fixed_brand_name:
                record_vals['_brand_name'] = fixed_brand_name
            elif brand_col_letter:
                brand_raw = get_val(brand_col_letter, row_idx_0_based)
                if brand_raw not in (None, ''):
                    record_vals['_brand_name'] = str(brand_raw).strip()

            # --- record errors or compute price ---
            if row_errors:
                validation_errors.append(f"Row {row_index}: " + "; ".join(row_errors))
            else:
                cur = self.env['res.currency'].browse(record_vals.get('currency_id') or False)
                converted_price = 0
                converted_rate = 0

                if cur == usd_currency:
                    converted_price = record_vals.get('supplier_unit_price', 0)
                    converted_rate = 1
                elif cur and cur.exists():
                    converted_price = cur._convert(record_vals.get('supplier_unit_price', 0),
                                                   usd_currency,  self.env['res.company'].browse(1), date.today())
                    converted_rate = cur._get_conversion_rate(cur, usd_currency,  self.env['res.company'].browse(1), date.today())

                record_vals['converted_price'] = converted_price
                record_vals['selling_price'] = converted_price * (1 + margin)
                record_vals['selling_price_2'] = record_vals.get('supplier_unit_price', 0) * (1 + margin)
                record_vals['min_sell'] = record_vals.get('supplier_unit_price', 0) * (1 + min_margin)
                record_vals['converted_rate'] = converted_rate

                # NEW: AED / EUR / GBP from the Original-Currency selling price
                record_vals.update(
                    SBSData._convert_selling_prices(cur, record_vals['selling_price_2'], date.today())
                )

                temp_records.append(record_vals)

        # =================================================================
        # 5. Second pass - resolve offer-level fields
        # =================================================================
        # print("VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV")
        # print(temp_records)
        # print(validation_errors)

        actions = []
        if temp_records:
            offer_fields = {k: v for k, v in DYNAMIC_FIELDS.items()
                            if v['scope'] in (SCOPE_OFFER, SCOPE_BOTH)}

            found = pre_ai_extract(metadata_cells, offer_fields)

            # MOQ/MOV embedded in the PRICE COLUMN HEADER (e.g. 'MOQ 5 PLT', 'MOV 20K').
            # This takes priority over metadata, since it describes this exact price column.
            header_row_idx0 = int(getattr(template, 'header_row', 1) or 1) - 1
            price_idx0 = col_letter_to_index(template.price_col) if template.price_col else None
            if price_idx0 is None and getattr(template, 'case_price_col', False):
                price_idx0 = col_letter_to_index(template.case_price_col)
            if price_idx0 is not None and 0 <= header_row_idx0 < len(sheet_data):
                hdr_row = sheet_data[header_row_idx0]
                price_header = hdr_row[price_idx0] if price_idx0 < len(hdr_row) else None
                hv, is_mov = extract_moq_from_header(price_header)
                if hv:
                    key = 'mov' if is_mov else 'moq'
                    found[key] = {'value': hv, 'addr': 'price_header', 'method': 'price_header'}

                # The INCOTERM often lives in the price header too, e.g.
                # 'FOB Jakarta' or '5 PALLETS PRICE EXW ŚWIDNIK PL'. Single-price
                # files are never split, so this header is the only place it
                # appears - read it here (metadata scan skips in-table columns).
                if 'incoterms' not in found and price_header:
                    ph = str(price_header)
                    im = re.search(
                        r'\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b',
                        ph, re.IGNORECASE)
                    if im:
                        # keep the code plus whatever place follows it
                        val = ph[im.start():].split('\n')[0].strip()
                        found['incoterms'] = {'value': val, 'addr': 'price_header',
                                              'method': 'price_header'}

            # regex first: only ask the model for what's still missing. The
            # provider itself checks the global AI switch + metadata toggle, so
            # this is a no-op (and makes no network call) when AI is off.
            missing = {k: v for k, v in offer_fields.items() if k not in found}
            if missing:
                found.update(self._ai_extract(metadata_cells, missing, template))

            # MOQ/MOV can also live in a MAPPED COLUMN (e.g. an 'MOQ' column whose
            # value is merged/repeated down the rows, like '33 pll'). Metadata
            # scan ignores in-table columns, so pull the value straight from the
            # mapped column's first non-empty data cell when we didn't find it
            # elsewhere.
            def _first_col_value(col_ref):
                ci = col_letter_to_index(col_ref) if col_ref else None
                if ci is None:
                    return None
                for r in range(header_row_idx0 + 1, len(sheet_data)):
                    row = sheet_data[r]
                    if ci < len(row) and row[ci] not in (None, ''):
                        return str(row[ci]).strip()
                return None

            if 'moq' not in found and getattr(template, 'moq_col', False):
                cv = _first_col_value(template.moq_col)
                if cv:
                    found['moq'] = {'value': cv, 'addr': template.moq_col,
                                    'method': 'mapped_column'}
            if 'mov' not in found and getattr(template, 'mov_col', False):
                cv = _first_col_value(template.mov_col)
                if cv:
                    found['mov'] = {'value': cv, 'addr': template.mov_col,
                                    'method': 'mapped_column'}

            resolved, actions = self._resolve_offer_fields(found, template, temp_records, country_lookup)

            # offer-level CoO raw value (resolved to a country later, on product)
            offer_coo = found.get('coo', {}).get('value')
            if not offer_coo and template.coo_fixed:
                offer_coo = template.coo_fixed.name

            # EUR.1 movement certificate: if any metadata cell says 'EUR 1 - YES'
            # (customs origin certificate for preferential tariff), record it in
            # the note. \xa0 and other odd spaces are normalized first.
            offer_note_lines = []

            # Conditions that have no field of their own. 'clean' belongs here
            # and NOT in the T1/T2 field: 'ALL GOODS ARE EU CLEAN' is the
            # supplier describing the goods, not a declared customs status.
            NOTE_HINTS = re.compile(
                r'deposit|subject\s+(?:to\s+)?unsold|unsold|assorted|'
                r'full\s+carton|orders?\s+in\s+full|carton\s+qty|'
                r'full\s+box(?:es)?|\bfresh\b|'
                r'full\s*pallets?|pallets?\s+only|mixed\s+pallets?|'
                r'per\s*sku|per\s*set|units?\s+per\s+\w+|pcs\s+per\s+\w+|'
                r'qty\s*[:\-]|up\s+to\s+\d+|minimum\s+\d+|'
                r'eu\s*clean|clean\s*eu|\bclean\b|'
                r'terms?\s*&?\s*conditions?|proforma|'
                r'goods\s+condition|warranty', re.IGNORECASE)

            # A cell that already fed a field is normally NOT repeated in the
            # note - the note is for what has no field, and echoing the lead
            # time / MOV / validity back made it unreadable.
            # The one exception is MOV and MOQ: suppliers routinely bolt a
            # buying condition onto the amount ('MOV 5000 GBP / Full Pallets',
            # 'MOV: 20KUSD & ASSORTED ORDER'). There only the LEFTOVER text is
            # kept, never the whole cell.
            consumed = {}
            for key, d in found.items():
                if not isinstance(d, dict):
                    continue
                if d.get('addr'):
                    consumed[d['addr']] = key
                if d.get('label_addr'):
                    consumed.setdefault(d['label_addr'], key)
            LEFTOVER_FIELDS = ('mov', 'moq')

            def _leftover(text):
                """
                What the cell says BESIDES the amount that became the MOV/MOQ.

                Only the FIRST monetary amount is removed, and only once: the
                old version stripped every number in the cell, so
                'Minimum Order: £3000 (Minimum 24 units per SKU)' lost the 24
                as well and the per-SKU condition became unreadable.
                """
                out = re.sub(
                    r'(?:[\u20ac$\u00a3]|aed)?\s*\d[\d.,]*\s*k?\s*'
                    r'(?:usd|eur|gbp|aed|dollars?|euros?|pounds?)?',
                    ' ', text, count=1, flags=re.IGNORECASE)
                out = re.sub(r'^[^:]{0,30}:', '', out)          # drop 'Minimum Order:'
                out = re.sub(r'^\s*(mov|moq|min(?:imum)?\.?\s*order(?:\s+value)?)\b',
                             '', out, flags=re.IGNORECASE)
                # the currency the amount was quoted in belongs to the MOV, not
                # to the condition: 'EUR 20K & ASSORTED' must leave 'ASSORTED'
                out = re.sub(r'\b(usd|eur|gbp|aed|dollars?|euros?|pounds?)\b',
                             ' ', out, flags=re.IGNORECASE)
                out = re.sub(r'[\u20ac$\u00a3]', ' ', out)
                out = out.strip(' \t()[]/&,-\u2013|.')
                return re.sub(r'\s+', ' ', out).strip()

            for c in metadata_cells:
                txt = re.sub(r'\s+', ' ', str(c.get('value') or '')).strip()
                if len(txt) < 4 or len(txt) > 300:
                    continue
                key = consumed.get(c.get('addr'))
                if key:
                    if key not in LEFTOVER_FIELDS:
                        continue
                    txt = _leftover(txt)
                    if len(txt.split()) < 2:
                        continue
                if not NOTE_HINTS.search(txt):
                    continue
                if txt not in offer_note_lines:
                    offer_note_lines.append(txt)
                if len(offer_note_lines) >= 8:
                    break
            # ' - ' between entries so the note reads as one line of conditions
            offer_note = " - ".join(offer_note_lines) if offer_note_lines else None
            if offer_note:
                _logger.info("[SBS] offer note built from %s condition(s).",
                             len(offer_note_lines))

            # apply to all records
            for rec in temp_records:
                # pure offer-level fields (always applied)
                for k in ('mov', 'moq', 'payment_term', 't1', 't2', 'euro1', 'incoterms'):
                    if k in resolved:
                        rec[k] = resolved[k]
                weeks = resolved.get('_offer_weeks')
                if weeks:
                    rec['end_date'] = import_date + timedelta(weeks=int(weeks))
                # SCOPE_BOTH fields: fill from offer only if per-row is empty
                if not rec.get('lead_time') and resolved.get('lead_time'):
                    rec['lead_time'] = resolved['lead_time']
                if not rec.get('_coo_raw') and offer_coo:
                    rec['_coo_raw'] = offer_coo
                # merge the EUR.1 note without clobbering an existing note
                if offer_note:
                    existing = (rec.get('note') or '').strip()
                    if offer_note not in existing:
                        rec['note'] = (existing + '\n' + offer_note).strip() if existing else offer_note

                rec['import_date'] = import_date

        # =================================================================
        # 6. Empty check
        # =================================================================
        if not temp_records:
            if validation_errors:
                error_msg = '\n'.join(validation_errors)
            else:
                error_msg = _(
                    'No valid data rows found.\n'
                    '- Template column mapping is incorrect, or\n'
                    '- Data starts at a different row than configured, or\n'
                    '- File is empty or all rows failed validation\n'
                    f'(Template: {template.name}, Start row: {start_row}, Sheet rows: {len(sheet_data)})'
                )

            if getattr(self, 'from_rpc', False):
                return {"status": "no", "result_error": error_msg}

            self.write({
                'total_imported': 0,
                'result_error': error_msg,
                'show_results': True,
            })
            return {
                'name': _('Import Results'),
                'type': 'ir.actions.act_window',
                'res_model': 'sbs.import.wizard',
                'view_mode': 'form',
                'res_id': self.id,
                'view_id': self.env.ref('oe_sbs.view_import_wizard_results').id,
                'target': 'new',
                'context': self.env.context,
            }

        # =================================================================
        # 7. Save
        # =================================================================
        import_number = self.env['ir.sequence'].next_by_code('sbs.import.sequence') or _('New')
        Product = self.env['product.template']

        # print("tttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttt")

        # Drop duplicate barcodes within THIS import: if the same EAN appears in
        # several rows, keep only the first occurrence and skip the rest.
        seen_eans = set()
        deduped_records = []
        duplicate_count = 0
        for rec in temp_records:
            ean = rec.get('ean')
            if ean and ean in seen_eans:
                duplicate_count += 1
                continue
            if ean:
                seen_eans.add(ean)
            deduped_records.append(rec)
        if duplicate_count:
            _logger.info("[SBS] skipped %s duplicate barcode row(s) in this import.",
                         duplicate_count)
        temp_records = deduped_records

        for rec in temp_records:
            # --- resolve supplier ---
            if not rec.get('supplier_id') and rec.get('supplier_code'):
                partner = self.env['res.partner'].search(
                    [('partner_code', '=', str(rec['supplier_code']).strip())], limit=1)
                if partner:
                    rec['supplier_id'] = partner.id
                    rec['supplier_name'] = partner.name

            product = Product.search([('barcode', '=', rec['ean'])], limit=1)
            if product:
                is_new_product = False
                rec['product_id'] = product.id
                product.sudo().write({'is_published': True})
            else:
                is_new_product = True
                product = Product.create({
                    'name': rec['product_name'],
                    'barcode': rec['ean'],
                    'type': 'consu',
                    'is_storable': True,
                    'tracking': 'lot',
                    'creation_method': 'sbs',
                    'is_published': True,
                })
                rec['product_id'] = product.id

            # ── BRAND ──
            brand_name = rec.pop('_brand_name', None)   # temp key, not an sbs.data field
            if brand_name:
                self._apply_brand_to_product(product, brand_name, is_new_product)

            # ── INTRINSIC PRODUCT FIELDS (CoO, HS Code, Cover Language) ──
            # temp keys; written onto the product (three-state), then sbs.data
            # reads them back via stored related fields.
            coo_raw = rec.pop('_coo_raw', None)
            hs_code = rec.pop('_hs_code', None)
            cover_language = rec.pop('_cover_language', None)
            coo_country = self._country_record(coo_raw, country_lookup) if coo_raw else False
            if coo_country or hs_code or cover_language:
                self._apply_intrinsic_fields_to_product(
                    product, coo_country, hs_code, is_new_product,
                    cover_language=cover_language)

            # ── UOM SYNC ──
            # Pack (Unit/Case), Layer (Unit/Layer) and Pallet (Unit/Pallet) are
            # each added as a UOM on the product so they can be used on the site.
            case_size = rec.get('case_size', 0)
            if case_size and int(case_size) > 0:
                uom = self._get_or_create_uom(case_size, name_prefix='Case')
                if uom:
                    rec['uom_id'] = uom.id
                    self._sync_uom_to_product(product, uom)

            upl = rec.get('unit_per_layer', 0)
            if upl and int(upl) > 1:
                layer_uom = self._get_or_create_uom(upl, name_prefix='Layer')
                if layer_uom:
                    self._sync_uom_to_product(product, layer_uom)

            upp = rec.get('unit_per_pallet', 0)
            if upp and int(upp) > 1:
                pallet_uom = self._get_or_create_uom(upp, name_prefix='Pallet')
                if pallet_uom:
                    self._sync_uom_to_product(product, pallet_uom)

            rec['import_number'] = import_number
            rec['document_id'] = self.document_id.id if self.from_doc else False
            SBSData.create(rec)
            imported_count += 1

        # --- actions (once, after the loop) ---
        unstated_note = ''
        for act in actions:
            if act['type'] == 'email_supplier':
                self._queue_incoterms_email(act, import_number=import_number)
            elif act['type'] == 'unstated_fields':
                unstated_note = "\n".join("- %s" % f for f in act['fields'])

        # print("wwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwww")

        self.write({
            'import_number': import_number,
            'total_imported': imported_count,
            'result_error': '',
            'unstated_note': unstated_note,
            'show_results': True
        })

        # Build the offer-list summary for what was just imported. Without this
        # a fresh import produced no sbs.offer.list at all until somebody
        # pressed a button by hand - the only caller was the retired
        # import_wizard__.py, so the live path had silently lost it.
        if imported_count > 0:
            try:
                self.env['sbs.offer.list'].sudo()._sync_for_import_number(import_number)
            except Exception:
                _logger.exception("[SBS] offer-list sync failed for import %s",
                                  import_number)

        if ICP.get_param('oe_sbs.auto_rank') == 'True' and imported_count > 0:
            self.env['sbs.data'].action_rank_products()

        cleanup_msg = ''
        if ICP.get_param('oe_sbs.auto_cleanup_old_lists') == 'True' and imported_count > 0:
            cleanup_summary = self.env['sbs.data'].action_cleanup_old_lists(
                new_import_number=import_number,
                new_import_date=fields.Date.today()
            )
            if cleanup_summary.get('deleted_lists', 0) > 0:
                cleanup_msg = (
                    f"\n\n🧹 Cleanup Summary:\n"
                    f"Supplier: {cleanup_summary.get('supplier_name', '')}\n"
                    f"Old lists removed: {cleanup_summary['deleted_lists']}\n"
                    f"Records deleted: {cleanup_summary['total_records_deleted']}"
                )

        self.write({'cleanup_msg': cleanup_msg})

        if getattr(self, 'from_rpc', False):
            return {"status": "ok", 'import_number': import_number,
                    'template_id': self.template_id.id if self.template_id else False,
                    'total_imported': imported_count, 'cleanup_msg': cleanup_msg}

        return {
            'name': _('Import Results'),
            'type': 'ir.actions.act_window',
            'res_model': 'sbs.import.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'view_id': self.env.ref('oe_sbs.view_import_wizard_results').id,
            'target': 'new',
            'context': self.env.context,
        }

    def action_new_import(self):
        """Create a new import wizard for another import"""
        return {
            'name': _('Import Excel Data'),
            'type': 'ir.actions.act_window',
            'res_model': 'sbs.import.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('oe_sbs.view_import_wizard_form').id,
            'target': 'new',
            'context': {},
        }

    def action_view_imported(self):
        """View imported records in the main SBS data model"""
        return {
            'name': _('Imported Data'),
            'type': 'ir.actions.act_window',
            'res_model': 'sbs.data',
            'view_mode': 'list,form',
            'domain': [('import_number', '=', self.import_number)],
            'context': {'search_default_group_by_ean': 1},
            'target': 'current',
        }
