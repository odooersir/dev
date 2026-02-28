# oe_custom_website/models/sale_order.py
from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _cart_find_product_line(
        self,
        product_id,
        uom_id=None,
        linked_line_id=False,
        no_variant_attribute_value_ids=None,
        **kwargs
    ):
        """
        اگر marketplace_offer_id باشد، فقط line مطابق با
        همان offer برگردان (هر offer = سبد مجزا).
        """
        offer_id = kwargs.get('marketplace_offer_id')

        if not offer_id:
            return super()._cart_find_product_line(
                product_id,
                uom_id,
                linked_line_id=linked_line_id,
                no_variant_attribute_value_ids=no_variant_attribute_value_ids,
                **kwargs,
            )

        offer_id   = int(offer_id)
        product_id = int(product_id)

        return self.order_line.filtered(
            lambda sol:
                sol.sbs_data_id.id == offer_id
                and sol.product_id.id == product_id
        )

    def _prepare_order_line_values(self, product_id, quantity, uom_id=None, **kwargs):
        """
        ذخیره snapshot اطلاعات offer هنگام ایجاد line جدید.
        """
        values = super()._prepare_order_line_values(
            product_id, quantity, uom_id, **kwargs
        )

        offer_id = kwargs.get('marketplace_offer_id')
        if offer_id:
            offer_id = int(offer_id)
            offer = self.env['sbs.data'].sudo().browse(offer_id)
            if offer.exists():
                values.update({
                    'sbs_data_id':           offer.id,
                    'snapshot_rank':         offer.rank,
                    'snapshot_price':        offer.selling_price,
                    'snapshot_seller_id':    offer.supplier_id.id,
                    'snapshot_seller_name':  (
                        offer.supplier_name or offer.supplier_id.name
                    ),
                    'snapshot_ean':          offer.ean or '',
                    # ← کلید اصلی برای basket_totals
                    'snapshot_import_number': str(offer.import_number or ''),
                    'price_unit':            offer.selling_price,
                })

        return values
