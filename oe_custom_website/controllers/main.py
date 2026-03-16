from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.tools.translate import _


class WebsiteSaleCustom(WebsiteSale):

    def _get_shop_payment_values(self, order, **kwargs):
        # فراخوانی متد والد برای دریافت تمام مقادیر اصلی
        values = super()._get_shop_payment_values(order, **kwargs)

        # تغییر متن دکمه پرداخت
        values['submit_button_label'] = _("Last Confirm")

        return values
