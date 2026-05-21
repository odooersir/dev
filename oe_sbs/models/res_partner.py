# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    offer_list_frequency = fields.Selection([
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('on_demand', 'On Demand'),
    ], string='Offer List Frequency')
    
    last_offer_date = fields.Date(
        string='Last Offer Date',
        compute='_compute_offer_stats',
        store=True
    )
    
    offer_count = fields.Integer(
        string='Offers Count',
        compute='_compute_offer_stats',
        store=True
    )
    
    offer_list_ids = fields.One2many(
        'sbs.offer.list',
        'supplier_id',
        string='Offer Lists'
    )
    
    supplier_rating = fields.Selection([
        ('1', '⭐'),
        ('2', '⭐⭐'),
        ('3', '⭐⭐⭐'),
        ('4', '⭐⭐⭐⭐'),
        ('5', '⭐⭐⭐⭐⭐'),
    ], string='Supplier Rating')
    
    payment_terms_note = fields.Text(string='Payment Terms Notes')
    delivery_time_days = fields.Integer(string='Average Delivery Time (Days)')

    @api.depends('offer_list_ids')
    def _compute_offer_stats(self):
        for partner in self:
            partner.offer_count = len(partner.offer_list_ids)
            if partner.offer_list_ids:
                latest = partner.offer_list_ids.sorted('import_date', reverse=True)[0]
                partner.last_offer_date = latest.import_date.date() if latest.import_date else False
            else:
                partner.last_offer_date = False

    def action_sync_offer_lists(self):
        """Sync offer lists from sbs.data"""
        self.ensure_one()
        
        # Get unique import_numbers for this supplier
        sbs_data = self.env['sbs.data'].search([('supplier_id', '=', self.id)])
        import_numbers = sbs_data.mapped('import_number')
        unique_imports = list(set([x for x in import_numbers if x]))
        
        # Clear existing
        self.offer_list_ids.unlink()
        
        # Create summary records
        for import_num in unique_imports:
            items = sbs_data.filtered(lambda r: r.import_number == import_num)
            first_item = items[0] if items else False
            
            if first_item:
                self.env['sbs.offer.list'].create({
                    'import_number': import_num,
                    'supplier_id': self.id,
                    'import_date': first_item.create_date,
                    'end_date': first_item.end_date,
                    'document_id': first_item.document_id.id if first_item.document_id else False,
                    'moq': first_item.moq,
                    'mov': first_item.mov,
                    'incoterms': first_item.incoterms,
                    't1_t2': first_item.t1_t2,
                    'payment_term': first_item.payment_term,
                    'lead_time': first_item.lead_time,
                })


