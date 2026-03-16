# oe_custom_website/models/product_template.py

import re
import logging
from odoo import models

_logger = logging.getLogger(__name__)

# شماره واتساپ — با کد کشور بدون + و فاصله
WHATSAPP_NUMBER = '971503001370 '  # <-- شماره خودت رو اینجا بذار


def _parse_numeric(value, cast=float):
    if value is None:
        return cast(0)
    s = str(value).strip()
    if not s:
        return cast(0)
    s_lower = s.lower()
    multiplier = 1
    if s_lower.endswith('k'):
        multiplier = 1_000
        s_lower = s_lower[:-1]
    elif s_lower.endswith('m'):
        multiplier = 1_000_000
        s_lower = s_lower[:-1]
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
        self.ensure_one()

        barcode = self.barcode
        if not barcode:
            return {'offers': [], 'cheapest_id': None, 'count': 0}

        query = """
            WITH ranked AS (
                SELECT DISTINCT ON (import_number)
                    sd.id,
                    sd.selling_price::float                             AS unit_price,
                    COALESCE(sd.supplier_id, 0)                         AS supplier_id,
                    COALESCE(sd.import_number, '')                      AS import_number,
                    sd.mov::text                                        AS mov_raw,
                    sd.moq::text                                        AS moq_raw,
                    COALESCE(sd.lead_time,   '')                        AS lead_time,
                    COALESCE(sd.incoterms,   '')                        AS incoterms,
                    COALESCE(sd.t1_t2,       '')                        AS t1_t2,
                    sd.rank,
                    COALESCE(sd.case_size, 1)                           AS case_size,
                    sd.uom_id,
                    COALESCE(u.name->>'en_US', u.name::text, 'Unit')    AS uom_name,
                    sd.is_expired                                       AS is_expired,
                    sd.end_date                                      AS expiry_date
                FROM sbs_data sd
                LEFT JOIN uom_uom u ON u.id = sd.uom_id
                WHERE sd.ean           = %s
                AND sd.selling_price > 0
                AND (
                    sd.is_expired = FALSE
                    OR (
                        sd.is_expired = TRUE
                        AND sd.end_date >= (CURRENT_DATE - INTERVAL '3 months')
                    )
                )
                ORDER BY
                    import_number,
                    sd.is_expired   ASC,
                    sd.rank         ASC NULLS LAST,
                    sd.selling_price ASC
            )
            SELECT * FROM ranked
            ORDER BY is_expired ASC, unit_price ASC
        """

        self.env.cr.execute(query, (barcode,))
        rows = self.env.cr.dictfetchall()

        if not rows:
            return {'offers': [], 'cheapest_id': None, 'count': 0}

        for row in rows:
            unit_price = float(row.get('unit_price') or 0)
            case_size  = max(int(row.get('case_size') or 1), 1)

            row['unit_price']    = unit_price
            row['selling_price'] = unit_price
            row['bundle_price']  = round(unit_price * case_size, 4)
            row['case_size']     = case_size
            row['is_expired']    = bool(row.get('is_expired', False))

            expiry_date = row.get('expiry_date')
            row['expiry_date'] = str(expiry_date) if expiry_date else ''

            # ── UOM ──────────────────────────────────────────────────────
            uom_id = row.get('uom_id')
            if case_size > 1:
                uom = self._get_or_create_uom(case_size)
                if uom:
                    row['uom_id']   = uom.id
                    row['uom_name'] = uom.name  # ✅ اینجا uom_name رو از آبجکت بخون
                    self._sync_uom_to_product(self, uom)
                else:
                    # ✅ fallback اگر uom ساخته نشد
                    row['uom_name'] = f'Pack of {case_size}'
            else:
                row['uom_id']   = False
                row['uom_name'] = 'Unit'
 
            # ── این fallback دیگه لازم نیست ولی به عنوان safety net نگهش دار ──
            if not row.get('uom_name') or row['uom_name'] in ('{}', 'null', ''):
                row['uom_name'] = f'Pack of {case_size}' if case_size > 1 else 'Unit'

            row['mov'] = _parse_numeric(row.pop('mov_raw'), cast=float)
            row['moq'] = _parse_numeric(row.pop('moq_raw'), cast=int)

            if not row.get('uom_name') or row['uom_name'] in ('{}', 'null', ''):
                row['uom_name'] = f'Pack of {case_size}' if case_size > 1 else 'Unit'

        
        
        
        # cheapest_id فقط از offer های فعال (منقضی نشده)
        active_rows = [r for r in rows if not r['is_expired']]
        cheapest_id = active_rows[0]['id'] if active_rows else (rows[0]['id'] if rows else None)

        return {
            'offers':           rows,
            'cheapest_id':      cheapest_id,
            'count':            len(rows),
            'whatsapp_number':  WHATSAPP_NUMBER,
        }

    def _get_or_create_uom(self, case_size):
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

        if not case_size or int(case_size) <= 1:
            return unit_uom

        case_size_float = float(int(case_size))
        uom = UoM.search([
            ('relative_uom_id', '=', unit_uom.id),
            ('relative_factor', '=', case_size_float),
        ], limit=1)

        if not uom:
            try:
                uom = UoM.sudo().create({
                    'name': f'Pack of {int(case_size)}',
                    'relative_uom_id': unit_uom.id,
                    'relative_factor': case_size_float,
                })
                _logger.info(
                    "[SBS UOM] New UOM created: '%s' (id=%s, factor=%s)",
                    uom.name, uom.id, case_size_float
                )
            except Exception as e:
                _logger.warning("[SBS UOM] Failed to create UOM: %s", e)
                return unit_uom

        return uom

    def _sync_uom_to_product(self, product_tmpl, uom):
        """
        Add the UOM to product.template.uom_ids (Many2many field).

        uom_ids = fields.Many2many('uom.uom', string='Packagings',
            domain="[('id', '!=', uom_id)]")
        """
        if not product_tmpl or not uom:
            return

        # اگر همان uom_id پیش‌فرض محصول است → skip
        if product_tmpl.uom_id.id == uom.id:
            _logger.debug(
                "[SBS UOM] UOM '%s' is the default UOM of product '%s' — skipping",
                uom.name, product_tmpl.name
            )
            return

        # اگر قبلاً در uom_ids وجود دارد → skip
        if uom in product_tmpl.uom_ids:
            _logger.debug(
                "[SBS UOM] UOM '%s' already in uom_ids of product '%s' — skipping",
                uom.name, product_tmpl.name
            )
            return

        # اضافه کردن به Many2many با command (4, id)
        try:
            product_tmpl.sudo().write({
                'uom_ids': [(4, uom.id)]
            })
            _logger.info(
                "[SBS UOM] UOM '%s' added to uom_ids of product '%s' (id=%s)",
                uom.name, product_tmpl.name, product_tmpl.id
            )
        except Exception as e:
            _logger.warning(
                "[SBS UOM] Failed to add UOM '%s' to product '%s': %s",
                uom.name, product_tmpl.name, e
            )

