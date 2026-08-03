# -*- coding: utf-8 -*-
"""
Split the single 't1_t2' Char into three independent customs-status fields.

Runs PRE-migrate so the old column is still present and readable: Odoo drops
nothing automatically, but the new Selection columns must be filled from the old
text before anyone looks at the data.

Mapping (deliberately conservative):
    'T1' -> t1 = yes
    'T2' -> t2 = yes
Nothing else is inferred. In particular an old value of 'T2' says nothing about
whether T1 also applied, so t1 is left empty rather than guessed as 'no' - an
empty field reads as "not stated", which is the truth.

EUR.1 used to live in the offer NOTE as the line 'EUR1: Yes' / 'EUR1: No'; that
is parsed back out here so the new euro1 field is populated for existing rows.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    for table in ('sbs_data', 'sbs_offer_list'):
        cr.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = %s AND column_name = 't1_t2'
        """, (table,))
        if not cr.fetchone():
            _logger.info("[SBS migration] %s.t1_t2 absent, nothing to split.", table)
            continue

        for col in ('t1', 't2', 'euro1'):
            cr.execute(
                'ALTER TABLE "%s" ADD COLUMN IF NOT EXISTS "%s" VARCHAR'
                % (table, col))

        cr.execute("""
            UPDATE "%s"
               SET t1 = 'yes'
             WHERE t1 IS NULL AND t1_t2 IS NOT NULL AND upper(trim(t1_t2)) = 'T1'
        """ % table)
        t1_rows = cr.rowcount
        cr.execute("""
            UPDATE "%s"
               SET t2 = 'yes'
             WHERE t2 IS NULL AND t1_t2 IS NOT NULL AND upper(trim(t1_t2)) = 'T2'
        """ % table)
        t2_rows = cr.rowcount
        _logger.info("[SBS migration] %s: %s rows -> t1=yes, %s rows -> t2=yes.",
                     table, t1_rows, t2_rows)

        # keep the old text around for one release so the split can be audited;
        # renaming (not dropping) makes it invisible to the ORM but recoverable.
        cr.execute('ALTER TABLE "%s" RENAME COLUMN t1_t2 TO t1_t2_legacy' % table)

    # EUR.1 was only ever recorded inside the offer note
    cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'sbs_data' AND column_name = 'note'
    """)
    if cr.fetchone():
        cr.execute(r"""
            UPDATE sbs_data
               SET euro1 = CASE
                       WHEN note ~* 'eur\.?\s*1\s*[:\-]?\s*(yes|y)\b' THEN 'yes'
                       WHEN note ~* 'eur\.?\s*1\s*[:\-]?\s*(no|n)\b'  THEN 'no'
                   END
             WHERE euro1 IS NULL AND note ~* 'eur\.?\s*1'
        """)
        _logger.info("[SBS migration] euro1 recovered from the note on %s rows.",
                     cr.rowcount)
