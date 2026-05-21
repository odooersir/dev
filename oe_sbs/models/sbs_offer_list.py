# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SbsOfferList(models.Model):
    _name = 'sbs.offer.list'
    _description = 'Supplier Offer List Summary'
    _order = 'import_number desc'

    import_number = fields.Char(string='Import Number', required=True)
    supplier_id = fields.Many2one('res.partner', string='Supplier', required=True, ondelete='cascade')
    import_date = fields.Datetime(string='Import Date')
    end_date = fields.Date(string='Valid Until')
    items_count = fields.Integer(string='Items Count', compute='_compute_items_count')
    document_id = fields.Many2one('documents.document', string='Document')
    
    # Aggregate fields from sbs.data
    moq = fields.Char(string='MOQ')
    mov = fields.Char(string='MOV')
    incoterms = fields.Char(string='Incoterms')
    t1_t2 = fields.Char(string='T1/T2')
    payment_term = fields.Char(string='Payment Terms')
    lead_time = fields.Char(string='Lead Time')

    @api.depends('import_number', 'supplier_id')
    def _compute_items_count(self):
        for record in self:
            record.items_count = self.env['sbs.data'].search_count([
                ('import_number', '=', record.import_number),
                ('supplier_id', '=', record.supplier_id.id)
            ])

    def action_view_items(self):
        self.ensure_one()
        return {
            'name': f'Items - {self.import_number}',
            'type': 'ir.actions.act_window',
            'res_model': 'sbs.data',
            'view_mode': 'list,form',
            'domain': [
                ('import_number', '=', self.import_number),
                ('supplier_id', '=', self.supplier_id.id)
            ],
        }


    def action_open_spreadsheet(self):
        self.ensure_one()
      
        for record in self:
            return {
                'type': 'ir.actions.act_url',
                'url':f'/odoo/documents/spreadsheet/{record.document_id.id}',
                'target': 'new',  # یا 'self' اگر می‌خواهی در همان تب باز شود
            }



    @api.model
    def _sync_for_import_number(self, import_number):
        """Sync offer lists فقط برای یک import_number خاص"""
        SBSData = self.env['sbs.data']
        
        records = SBSData.search([
            ('import_number', '=', import_number),
            ('is_expired', '=', False)
        ])
        
        grouped = {}
        for rec in records:
            key = (rec.import_number, rec.supplier_id.id)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(rec)
        
        for (imp_num, supp_id), items in grouped.items():
            first = items[0]
            
            existing = self.search([
                ('import_number', '=', imp_num),
                ('supplier_id', '=', supp_id)
            ], limit=1)
            
            vals = {
                'import_number': imp_num,
                'supplier_id': supp_id,
                'import_date': first.import_date,
                'end_date': first.end_date,
                'document_id': first.document_id.id,
                'items_count': len(items),
                'moq': first.moq,
                'mov': first.mov,
                'incoterms': first.incoterms,
                't1_t2': first.t1_t2,
                'payment_term': first.payment_term,
                'lead_time': first.lead_time,
            }
            
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
