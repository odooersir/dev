from odoo.tools.translate import _

from werkzeug.exceptions import NotFound

from odoo.fields import Domain
from odoo.http import request, route

from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website_sale.const import SHOP_PATH
# ─── MOV Logic ────────────────────────────────────────────────────────────────
def _compute_mov_violations(order_sudo):
    """
    محاسبه MOV violations برای سبد.
    فقط لاین‌هایی که sbs_data_id دارند بررسی می‌شوند.
    
    Returns: list[dict] — violations یا لیست خالی
    """
    import_data = {}

    for line in order_sudo.order_line:
        if not line.sbs_data_id:
            continue

        imp_num = (
            line.snapshot_import_number
            or str(line.sbs_data_id.import_number or '')
            or ''
        ).strip()

        if not imp_num:
            continue

        if imp_num not in import_data:
            import_data[imp_num] = {'total_value': 0.0, 'mov': 0.0}

        import_data[imp_num]['total_value'] += float(line.price_subtotal)

        # MOV از فیلد Char sbs.data → parse
        offer_mov = _parse_numeric_mov(line.sbs_data_id.mov or '', cast=float)
        if offer_mov > import_data[imp_num]['mov']:
            import_data[imp_num]['mov'] = offer_mov

    violations = []
    for imp_num, data in import_data.items():
        if data['mov'] > 0 and data['total_value'] < data['mov']:
            violations.append({
                'import_number': imp_num,
                'mov':           data['mov'],
                'current_value': data['total_value'],
                'remaining':     round(data['mov'] - data['total_value'], 2),
            })

    violations.sort(key=lambda x: x['import_number'])
    return violations



class WebsiteSaleCustom(WebsiteSale):

    """
    بلاک کردن checkout اگر MOV رعایت نشده باشد.
    ریدایرکت به /shop/cart با ذخیره violations در session.
    """

    def shop_checkout(self, try_skip_step=None, **query_params):
        order_sudo = request.cart

        if order_sudo:
            violations = _compute_mov_violations(order_sudo)
            if violations:
                # ذخیره در session — Cart._cart_values() آن را می‌خواند
                request.session['mp_mov_violations'] = violations
                _logger.info(
                    "MOV check failed for order %s: %s violations",
                    order_sudo.name, len(violations)
                )
                return request.redirect('/shop/cart')

        # اگر همه چیز OK بود، violations قدیمی را پاک کن
        request.session.pop('mp_mov_violations', None)
        return super().shop_checkout(try_skip_step=try_skip_step, **query_params)

    def _get_shop_payment_values(self, order, **kwargs):
        # فراخوانی متد والد برای دریافت تمام مقادیر اصلی
        values = super()._get_shop_payment_values(order, **kwargs)

        # تغییر متن دکمه پرداخت
        values['submit_button_label'] = _("Last Confirm")

        return values

    @route(
        [
            f'{SHOP_PATH}/offer/<string:import_number>',
            f'{SHOP_PATH}/offer/<string:import_number>/page/<int:page>',
        ],
        type='http',
        auth='public',
        website=True,
        sitemap=False,
    )
    def shop_by_sbs_import(self, import_number, page=0, search='',
                           min_price=0.0, max_price=0.0, tags='', **post):
        if not request.website.has_ecommerce_access():
            return request.redirect(
                f'/web/login?redirect={request.httprequest.path}'
            )

        normalized = str(import_number).zfill(5)

        # یک کوئری SQL برای همه چیز
        request.env.cr.execute("""
            SELECT
                sd.product_id,
                sd.ean,
                sd.supplier_name,
                sd.end_date
            FROM sbs_data sd
            WHERE sd.import_number = %s
        """, (normalized,))
        rows = request.env.cr.fetchall()

        if not rows:
            raise NotFound()

        # product_id مستقیم
        linked_ids = {row[0] for row in rows if row[0]}

        # EAN های بدون product_id
        eans = [row[1] for row in rows if not row[0] and row[1]]
        if eans:
            request.env.cr.execute(
                "SELECT id FROM product_template WHERE barcode = ANY(%s)",
                (eans,)
            )
            linked_ids |= {row[0] for row in request.env.cr.fetchall()}

        if not linked_ids:
            raise NotFound()

        tmpl_ids = list(linked_ids)
        first = rows[0]

        # ذخیره روی request — فقط برای این request زنده است
        request._sbs_tmpl_ids = tmpl_ids
        request._sbs_info = {
            'sbs_import_number': normalized,
            'sbs_supplier_name': first[2] or '',
            'sbs_end_date': str(first[3]) if first[3] else '',
        }
        request._sbs_base_path = f'{SHOP_PATH}/offer/{normalized}'

        return super().shop(
            page=page,
            search=search,
            min_price=min_price,
            max_price=max_price,
            tags=tags,
            **post,
        )

    # ─── Pagination URL ───────────────────────────────────────────────────────

    @staticmethod
    def _get_shop_path(category=None, page=0):
        sbs_path = getattr(request, '_sbs_base_path', None)
        if sbs_path and not category:
            path = sbs_path
            if page:
                path += f'/page/{page}'
            return path
        return WebsiteSale._get_shop_path(category, page)

    # ─── متغیرهای template ────────────────────────────────────────────────────

    def _get_additional_shop_values(self, values, **kwargs):
        res = super()._get_additional_shop_values(values, **kwargs)
        sbs_info = getattr(request, '_sbs_info', None)
        if sbs_info:
            res.update(sbs_info)
        return res
