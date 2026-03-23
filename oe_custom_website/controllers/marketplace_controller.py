# oe_custom_website/controllers/marketplace_controller.py

from odoo import http
from odoo.http import request
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
