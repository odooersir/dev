from odoo import models, fields, api

class PosOrder(models.Model):
    _inherit = "pos.order"

    is_cash = fields.Boolean(
        string='Cash Payment',
        default=False,
        help="Indicates if this order uses cash payment method"
    )
    is_kiosk = fields.Boolean(
        string='Kiosk Order',
        default=False,
        help="Indicates if this order was created from a kiosk"
    )

    def print_cash_slip(self):
        """Print a simple cash slip with order number and instructions"""
        slip_content = f"""
        <div style="text-align: center; width: 58mm; font-family: monospace;">
            <h3>Order Number</h3>
            <h2>{self.pos_reference or self.name}</h2>
            <br/>
            <p>Veuillez vous rendre en caisse accompagné du ticket pour payer votre commande.</p>
            <br/>
            <p>Please go to the cashier with this ticket to pay for your order.</p>
        </div>
        """
        return {
            'type': 'ir.actions.client',
            'tag': 'pos_receipt_print',
            'params': {
                'receipt': slip_content
            }
        }
