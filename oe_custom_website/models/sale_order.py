# oe_custom_website/models/sale_order.py
from odoo import models
import logging
_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _cart_find_product_line(self, product_id, uom_id=None, linked_line_id=False,no_variant_attribute_value_ids=None, **kwargs ):
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
        print ("_prepare_order_line_values _prepare_order_line_values")
        
        values = super()._prepare_order_line_values(
            product_id, quantity, uom_id, **kwargs
        )

        offer_id = kwargs.get('marketplace_offer_id')
        if offer_id:
            offer_id = int(offer_id)
            offer = self.env['sbs.data'].sudo().browse(offer_id)
            if offer.exists():
                # ✅ case_size را برای محاسبه قیمت بسته استفاده کن
                case_size = max(int(offer.case_size or 1), 1)
                bundle_price = round(float(offer.selling_price) * case_size, 4)

                print ("caseeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee sizeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
                print (case_size)
                print (bundle_price)

                values.update({
                    'sbs_data_id':            offer.id,
                    'snapshot_rank':          offer.rank,
                    'snapshot_price':         offer.selling_price,
                    'snapshot_seller_id':     offer.supplier_id.id,
                    'snapshot_seller_name':   (
                        offer.supplier_name or offer.supplier_id.name
                    ),
                    'snapshot_ean':           offer.ean or '',
                    'snapshot_import_number': str(offer.import_number or ''),
                    # ✅ قیمت بسته = قیمت واحد × تعداد در بسته
                    'price_unit':             bundle_price,
                })

        return values

    def _cart_update_line_quantity(self, line_id, quantity, **kwargs):
        """
        آپدیت تعداد خط سبد.
        اگر خط marketplace offer باشد، price_unit را دوباره محاسبه کنید.
        """
        line = self.order_line.browse(line_id)
        
        # ✅ اگر این خط marketplace offer است
        if line.sbs_data_id:
            offer = line.sbs_data_id
            case_size = max(int(offer.case_size or 1), 1)
            
            # ✅ Debug log
            _logger.info(f"MARKETPLACE UPDATE: line_id={line_id}, qty={quantity}, "
                        f"selling_price={offer.selling_price}, case_size={case_size}")
            
            # قیمت را دوباره محاسبه کنید
            new_price_unit = offer.selling_price * case_size
            
            # ✅ محاسبه added_qty (اختلاف quantity جدید و قدیمی)
            old_qty = line.product_uom_qty
            added_qty = quantity - old_qty
            
            line.write({
                'product_uom_qty': quantity,
                'price_unit': new_price_unit,
            })
            
            _logger.info(f"MARKETPLACE UPDATE: new_price_unit={new_price_unit}, "
                        f"old_qty={old_qty}, added_qty={added_qty}")
            
            # بقیه محاسبات Odoo
            line._compute_amount()
            
            # ✅ برگرداندن همه کلیدهای مورد نیاز controller
            return {
                'line_id': line_id,
                'quantity': quantity,
                'added_qty': added_qty,
            }
        
        # برای محصولات عادی، از روش استاندارد استفاده کنید
        return super()._cart_update_line_quantity(line_id, quantity, **kwargs)



    def _recompute_cart(self):
        """
        Override to protect marketplace offer lines from price reset.
        Lines that have sbs_data_id set should keep their custom price_unit.
        """
        # ابتدا price_unit لاین‌های marketplace را ذخیره کنیم
        mp_line_prices = {}
        for line in self.order_line:
            if line.sbs_data_id:
                mp_line_prices[line.id] = {
                    'price_unit': line.price_unit,
                    'product_uom_qty': line.product_uom_qty,
                    'product_uom_id': line.product_uom_id.id,
                }

        # اجرای recompute اصلی
        super()._recompute_cart()

        # بازگرداندن قیمت‌های marketplace lines
        for line in self.order_line:
            if line.id in mp_line_prices:
                saved = mp_line_prices[line.id]
                line.write({
                    'price_unit': saved['price_unit'],
                    'product_uom_qty': saved['product_uom_qty'],
                    'product_uom_id': saved['product_uom_id'],
                })
                line._compute_amount()
