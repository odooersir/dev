# -*- coding: utf-8 -*-
"""
Pre-migration for sbs.data.mov : Char -> Monetary.

Runs BEFORE Odoo loads the new model definition, so the existing text values
(e.g. "20K€", "€8,103", "5k") are converted to plain numbers and preserved in
the same column. Without this, changing the field type would drop the data.

Strategy:
  1. add a temporary numeric column mov_num
  2. read every text mov, parse it to a number, write mov_num
  3. drop the old text column mov
  4. rename mov_num -> mov  (now numeric, ready for the Monetary field)
"""
import re
import logging

_logger = logging.getLogger(__name__)


def _mov_text_to_number(s):
    """'20K€' -> 20000.0, '€8,103' -> 8103.0, '5k' -> 5000.0. None if unparsable."""
    if not s:
        return None
    s = str(s).strip()
    # strip currency symbols / codes
    s = re.sub(r'(€|\$|£|aed|eur|usd|gbp)', '', s, flags=re.IGNORECASE).strip()
    # detect a 'k' (thousands) suffix
    has_k = bool(re.search(r'\d\s*k\b', s, re.IGNORECASE)) or s.lower().endswith('k')
    s = re.sub(r'k', '', s, flags=re.IGNORECASE).strip()
    # keep only number-ish characters
    num = re.sub(r'[^\d,.\-]', '', s)
    if not num:
        return None
    has_comma, has_dot = ',' in num, '.' in num
    if has_comma and has_dot:
        if num.rfind(',') > num.rfind('.'):          # European: 1.234,56
            num = num.replace('.', '').replace(',', '.')
        else:                                        # US: 1,234.56
            num = num.replace(',', '')
    elif has_comma:
        if len(num.split(',')[-1]) == 2:             # decimal comma: 8,79
            num = num.replace(',', '.')
        else:                                        # thousands: 1,234
            num = num.replace(',', '')
    try:
        val = float(num)
        return val * 1000 if has_k else val
    except ValueError:
        return None


def _migrate_mov(cr):
    """Convert sbs_data.mov from text to numeric, preserving values."""
    cr.execute("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'sbs_data' AND column_name = 'mov'
    """)
    row = cr.fetchone()
    if not row:
        _logger.info("[SBS migration] no sbs_data.mov column; skipping.")
        return
    data_type = row[0]
    if data_type not in ('character varying', 'text'):
        _logger.info("[SBS migration] sbs_data.mov already numeric (%s); skipping.",
                     data_type)
        return

    # 1. temporary numeric column
    cr.execute("ALTER TABLE sbs_data ADD COLUMN IF NOT EXISTS mov_num numeric")

    # 2. convert each text value
    cr.execute("SELECT id, mov FROM sbs_data WHERE mov IS NOT NULL AND mov <> ''")
    rows = cr.fetchall()
    converted, skipped = 0, 0
    for rec_id, mov_text in rows:
        value = _mov_text_to_number(mov_text)
        if value is None:
            skipped += 1
            continue
        cr.execute("UPDATE sbs_data SET mov_num = %s WHERE id = %s", (value, rec_id))
        converted += 1

    _logger.info("[SBS migration] mov text->number: %s converted, %s skipped (unparsable).",
                 converted, skipped)

    # 3. drop the old text column, 4. rename the numeric one into its place
    cr.execute("ALTER TABLE sbs_data DROP COLUMN mov")
    cr.execute("ALTER TABLE sbs_data RENAME COLUMN mov_num TO mov")
    _logger.info("[SBS migration] sbs_data.mov is now numeric.")


def _drop_text_column_for_relation(cr, column):
    """
    A column that becomes a Many2one/related (e.g. coo, hs_code) cannot be
    auto-converted from its old text content. Drop the old text column so Odoo
    recreates it with the right type; the new value is then filled from the
    related product field (or by future imports).
    """
    cr.execute("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'sbs_data' AND column_name = %s
    """, (column,))
    row = cr.fetchone()
    if not row:
        return
    data_type = row[0]
    # coo becomes integer (Many2one) -> must drop the old varchar/text.
    # hs_code stays character but becomes a stored related; dropping lets the
    # related recompute cleanly from the product.
    if data_type in ('character varying', 'text'):
        cr.execute("ALTER TABLE sbs_data DROP COLUMN %s" % column)
        _logger.info("[SBS migration] dropped old text column sbs_data.%s "
                     "(will be repopulated via related product field).", column)


def migrate(cr, version):
    if not version:
        return
    _migrate_mov(cr)
    # coo (Char -> Many2one res.country) and hs_code (Char -> stored related):
    # the old text can't be auto-cast, so drop it; values come back from the
    # product via the related fields.
    _drop_text_column_for_relation(cr, 'coo')
    _drop_text_column_for_relation(cr, 'hs_code')