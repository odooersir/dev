# oe_custom_website/controllers/marketplace_controller.py

from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website_sale.controllers.cart import Cart

import re
import logging
_logger = logging.getLogger(__name__)


# ─── Helper ──────────────────────────────────────────────────────────────────
def _parse_numeric_mov(value, cast=float):
    """Parse MOV from Char field (supports k/m suffix)."""
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


# ─── Marketplace Routes ───────────────────────────────────────────────────────
class MarketplaceController(http.Controller):

    @http.route(
        '/marketplace/product/<int:product_id>/offers',
        type='jsonrpc',
        auth='public',
        website=True,
    )
    def get_product_offers(self, product_id):
        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists():
            return {'error': 'Product not found', 'offers': [], 'count': 0}
        data = product.get_marketplace_offers()
        return {
            'offers': [
                {
                    'id':            offer['id'],
                    'price':         offer['selling_price'],
                    'import_number': offer['import_number'],
                    'mov':           offer['mov'],
                    'moq':           offer['moq'],
                    'rank':          offer['rank'],
                }
                for offer in data['offers']
            ],
            'count': data['count'],
        }

    @http.route(
        '/marketplace/cart/basket_totals',
        type='jsonrpc',
        auth='public',
        website=True,
        methods=['POST'],
    )
    def get_basket_totals(self, import_numbers=None):
        result = {}
        if import_numbers:
            for imp in import_numbers:
                result[str(imp)] = {'total_value': 0.0, 'total_qty': 0}

        order = request.cart
        if not order or not order.order_line:
            return result

        for line in order.order_line:
            imp_num = (
                line.snapshot_import_number
                or (line.sbs_data_id and str(line.sbs_data_id.import_number or ''))
                or ''
            )
            if not imp_num:
                continue
            imp_key = str(imp_num)
            if imp_key not in result:
                result[imp_key] = {'total_value': 0.0, 'total_qty': 0}
            result[imp_key]['total_value'] += float(line.price_subtotal)
            result[imp_key]['total_qty']   += int(line.product_uom_qty)

        return result


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


# ─── Override WebsiteSale.shop_checkout ──────────────────────────────────────
class WebsiteSaleMarketplace(WebsiteSale):
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


# ─── Override Cart._cart_values ──────────────────────────────────────────────
class CartMarketplace(Cart):
    """
    Inject mp_mov_violations به context صفحه /shop/cart.
    
    از کد اصلی Cart:
        values.update(self._cart_values(**post))   ← این hook فراخوانی می‌شود
    """

    def _cart_values(self, **post):
        values = super()._cart_values(**post)

        # violations را از session بخوان و پاک کن (flash message pattern)
        violations = request.session.pop('mp_mov_violations', None)
        if violations:
            values['mp_mov_violations'] = violations

        return values
