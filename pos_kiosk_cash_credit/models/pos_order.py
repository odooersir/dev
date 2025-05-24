from odoo import models, fields

class PosOrder(models.Model):
    _inherit = "pos.order"

    is_kiosk = fields.Boolean(default=False)
    payment_method = fields.Selection(
        selection=[("cash", "Cash"), ("card", "Credit Card")],
        string="Payment Method"
    )