# oe_custom_website/controllers/marketplace_controller.py
from odoo import http
from odoo.http import request


class MarketplaceController(http.Controller):

    @http.route(
        '/marketplace/product/<int:product_id>/offers',
        type='jsonrpc',
        auth='public',
        website=True,
    )
    def get_product_offers(self, product_id):
        """دریافت لیست پیشنهادهای یک محصول"""
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

    # ─────────────────────────────────────────────────────────────────
    # basket_totals  ←  real-time progress bar + "X in cart"
    # ─────────────────────────────────────────────────────────────────
    @http.route(
        '/marketplace/cart/basket_totals',
        type='jsonrpc',
        auth='public',
        website=True,
        methods=['POST'],
    )
    def get_basket_totals(self, import_numbers=None):
        """
        برگرداندن مجموع ارزش و تعداد آیتم‌های سبد به تفکیک import_number.

        خروجی:
        {
            "ABC123": {"total_value": 150.0, "total_qty": 3},
            "XYZ456": {"total_value": 80.0,  "total_qty": 1},
        }
        """
        result = {}

        # مقداردهی اولیه با صفر برای همه import_numberهای درخواستی
        if import_numbers:
            for imp in import_numbers:
                result[str(imp)] = {'total_value': 0.0, 'total_qty': 0}

        # ── Odoo 19: request.cart ────────────────────────────────────
        order = request.cart
        if not order or not order.order_line:
            return result

        # ── جمع‌آوری اطلاعات از order lines ──────────────────────────
        for line in order.order_line:
            imp_num = (
                line.snapshot_import_number
                or (
                    line.sbs_data_id
                    and str(line.sbs_data_id.import_number or '')
                )
                or ''
            )
            if not imp_num:
                continue

            imp_key = str(imp_num)
            if imp_key not in result:
                result[imp_key] = {'total_value': 0.0, 'total_qty': 0}

            result[imp_key]['total_value'] += float(
                line.price_unit * line.product_uom_qty
            )
            result[imp_key]['total_qty'] += int(line.product_uom_qty)

        return result
