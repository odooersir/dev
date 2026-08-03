# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Suppliers routinely send offers from several addresses (sales desk,
    # regional office, a personal mailbox). Mail routing matched only the
    # partner's MAIN email, so everything else landed in 'Unmatched'.
    offer_email_ids = fields.One2many(
        'sbs.partner.offer.email', 'partner_id', string='Offer Emails',
        help="Additional addresses this supplier sends offers from. Mail "
             "from any of them is routed to this supplier's folder, just "
             "like mail from the main email.")

    receive_offer = fields.Selection([
        ('mailing_list', 'Mailing List'),
        ('on_request', 'Base on Request'),
    ], string='Receive Offer',
        help="How this supplier's offer lists reach us: they push them to a "
             "mailing list we are subscribed to, or we have to ask each time.")

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
        """Rebuild this supplier's offer-list summaries.

        Delegates to sbs.offer.list._sync_for_import_number - the single
        implementation. The previous version was a third copy of that logic and
        differed from it in two damaging ways: it wrote create_date into
        import_date instead of the offer's own import_date, and it unlinked
        every existing summary before recreating it, so the records changed id
        on every press and anything pointing at them broke. The shared helper
        upserts instead.
        """
        self.ensure_one()
        import_numbers = self.env['sbs.data'].search([
            ('supplier_id', '=', self.id),
        ]).mapped('import_number')
        OfferList = self.env['sbs.offer.list']
        for import_number in sorted({n for n in import_numbers if n}):
            OfferList._sync_for_import_number(import_number)
        return True
