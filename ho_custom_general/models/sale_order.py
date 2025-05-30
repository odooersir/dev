from odoo import fields, models
class SaleOrder(models.Model):
    _inherit = "sale.order"


    agent_id =fields.Many2one('res.partner', string='Agent', ondelete='restrict') 


