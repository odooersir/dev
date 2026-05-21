from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SaleOrderToPOWizard(models.TransientModel):
    _name = 'sale.order.to.po.wizard'
    _description = 'Wizard to Convert Sale Order to Purchase Order'

    vendor_id = fields.Many2one('res.partner', string="Vendor", required=True)
    sale_order_id = fields.Many2one('sale.order', string="Sale Order", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        sale_order_id = self._context.get('active_id')
        if sale_order_id:
            res['sale_order_id'] = sale_order_id
        return res

    def action_confirm(self):
        if not self.vendor_id:
            raise ValidationError(_("Please select a vendor."))

        sale_order = self.sale_order_id

        if sale_order.purchase_id:
            raise ValidationError(_("Purchase Order is already created!"))
        
        purchase = self.env['purchase.order'].create({
            'partner_id': self.vendor_id.id
        })

        for rec in sale_order.order_line.filtered(lambda l: not l.display_type and l.qty_to_invoice != -1):
            self.env['purchase.order.line'].create({
                'product_id': rec.product_id.id,
                'name': rec.name,
                'product_qty': rec.product_uom_qty,
                'product_uom_id': rec.product_uom_id.id,
                'price_unit': rec.product_id.standard_price,
                'order_id': purchase.id,
            #    'taxe_ids': rec.tax_id,
            })
        
        sale_order.sudo().write({'purchase_id': purchase.id})

        action = self.env.ref('purchase.action_rfq_form')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': _('New Purchase Order has been created.'),
                'links': [{
                    'label': purchase.name,
                    'url': f'#action={action.id}&id={purchase.id}&model=purchase.order'
                }],
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
