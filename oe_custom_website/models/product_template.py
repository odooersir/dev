# oe_custom_website/models/product_template.py

import re
from odoo import models


def _parse_numeric(value, cast=float):
    """
    تبدیل امن رشته به عدد.
    مقادیری مثل "€20k", "1,500", "$100.5", "N/A", "" را پشتیبانی می‌کند.
    اگر تبدیل ممکن نبود، صفر برمی‌گرداند.
    """
    if value is None:
        return cast(0)

    # تبدیل به string و پاک‌سازی
    s = str(value).strip()

    if not s:
        return cast(0)

    # حذف کاراکترهای غیرعددی به جز نقطه، منفی، e (scientific)
    # ابتدا k/m/b را پردازش کنیم
    s_lower = s.lower()

    # مضرب‌های رایج
    multiplier = 1
    if s_lower.endswith('k'):
        multiplier = 1_000
        s_lower = s_lower[:-1]
    elif s_lower.endswith('m'):
        multiplier = 1_000_000
        s_lower = s_lower[:-1]

    # حذف همه چیز به جز اعداد، نقطه، منها
    cleaned = re.sub(r'[^\d.\-]', '', s_lower)

    if not cleaned:
        return cast(0)

    try:
        return cast(float(cleaned) * multiplier)
    except (ValueError, OverflowError):
        return cast(0)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def get_marketplace_offers(self):
        """
        دریافت بهترین پیشنهاد هر (supplier_id, import_number).
        
        نکته: فیلدهای mov و moq در دیتابیس VARCHAR هستند و ممکن است
        مقادیر غیرعددی مثل "€20k", "N/A", "" داشته باشند.
        پس cast در SQL انجام نمی‌شود - پردازش در Python صورت می‌گیرد.
        """
        self.ensure_one()

        barcode = self.barcode
        if not barcode:
            return {'offers': [], 'cheapest_id': None, 'count': 0}

        # فقط فیلدهای مطمئناً عددی را در SQL پردازش می‌کنیم
        # mov و moq را خام (AS TEXT) می‌گیریم
        query = """
            SELECT DISTINCT ON (supplier_id, import_number)
                id,
                selling_price::float                      AS selling_price,
                COALESCE(supplier_id, 0)                    AS supplier_id,
                COALESCE(import_number, '')                 AS import_number,
                mov::text                                   AS mov_raw,
                moq::text                                   AS moq_raw,
                COALESCE(lead_time, '')                     AS lead_time,
                COALESCE(incoterms, '')                     AS incoterms,
                COALESCE(t1_t2, '')                         AS t1_t2,
                rank
            FROM sbs_data
            WHERE ean = %s
              AND is_expired = FALSE
              AND selling_price > 0
            ORDER BY supplier_id, import_number, rank ASC
        """

        self.env.cr.execute(query, (barcode,))
        rows = self.env.cr.dictfetchall()

        if not rows:
            return {'offers': [], 'cheapest_id': None, 'count': 0}

        # پردازش در Python - امن در برابر هر مقدار رشته‌ای
        for row in rows:
            row['selling_price'] = float(row['selling_price'] or 0)
            row['mov']             = _parse_numeric(row.pop('mov_raw'), cast=float)
            row['moq']             = _parse_numeric(row.pop('moq_raw'), cast=int)

        # مرتب‌سازی بر اساس قیمت (ارزان‌ترین اول)
        rows.sort(key=lambda r: r['selling_price'])

        cheapest_id = rows[0]['id'] if rows else None

        return {
            'offers':      rows,
            'cheapest_id': cheapest_id,
            'count':       len(rows),
        }
