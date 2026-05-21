# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    """Inherited the model to add new fields for select vendor and
    purchase order."""
    _inherit = "sale.order"

    #vendor_id = fields.Many2one('res.partner', string="Vendor",help="Choose vendor for create new purchase " "order")
    
    purchase_id = fields.Many2one('purchase.order',
                                  string="Purchase Order",
                                  domain=[('state', '=', 'draft')],
                                  help="Choose a purchase order from the list "
                                       "to add the chosen orders to an "
                                       "existing PO.")

    def action_convert_po(self):
     
        '''
        if self.env['sale.order.line'].search_count(
                [('order_id', '=', self.id), ('is_check', '=', True)]) >= 1:
            if self.purchase_id:
                purchase = self.purchase_id
            elif self.vendor_id:
                purchase = self.env['purchase.order'].create(
                    {'partner_id': self.vendor_id.id})
            else:
                raise ValidationError(_("Select Vendor or Purchase Order"))
        else:
            raise ValidationError(_("Select Order Line"))
        '''
        if self.purchase_id:
            raise ValidationError(_("Purchase Order is Created Before!"))
        else:
            
            purchase = self.env['purchase.order'].create({'partner_id': self.company_id.id})

            for rec in self.env['sale.order.line'].search([('order_id', '=', self.id),('display_type', '=', False),('qty_to_invoice', '!=', -1)  ]):
                    self.env['purchase.order.line'].create({
                        'product_id': rec.product_id.id,
                        'name': rec.name,
                        'product_qty': rec.product_uom_qty,
                        'price_unit': rec.product_id.standard_price,
                        'order_id': purchase.id,
                        'taxes_id': rec.tax_id,
                    })
       
        self.sudo().write({'purchase_id':purchase.id})
       
        action = self.env.ref('purchase.action_rfq_form')

        return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': _('New Purchase Order has been placed. %s',),
                    'links': [{
                        'label': purchase.name,
                        'url': f'#action={action.id}&id={purchase.id}'
                               f'&model=purchase.order'
                    }],
                    'next': {
                        'type': 'ir.actions.act_window_close'
                    },
                }
            }



