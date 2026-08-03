# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class SbsPartnerOfferEmail(models.Model):
    _name = 'sbs.partner.offer.email'
    _description = 'Additional email a supplier sends offers from'
    _order = 'partner_id, email'

    partner_id = fields.Many2one(
        'res.partner', string='Supplier', required=True,
        ondelete='cascade', index=True)
    email = fields.Char(string='Email', required=True, index=True)
    name = fields.Char(
        string='Label',
        help="Optional note, e.g. 'sales desk' or 'Milan office'.")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        # The whole point of this model is routing an incoming email to ONE
        # supplier. Two suppliers claiming the same address would make that
        # ambiguous, so the address is unique across the table rather than
        # merely per-partner.
        ('email_uniq', 'unique(email)',
         'This email is already registered for a supplier.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('email'):
                vals['email'] = vals['email'].strip().lower()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('email'):
            vals['email'] = vals['email'].strip().lower()
        return super().write(vals)

    @api.constrains('email', 'partner_id')
    def _check_not_main_email_of_other(self):
        """Reject an address that is another partner's MAIN email.

        Routing looks at main emails first, so allowing this would create a
        conflict that only shows up later as mail landing in the wrong folder.
        """
        for record in self:
            if not record.email:
                continue
            clash = self.env['res.partner'].sudo().search([
                ('email', '=ilike', record.email),
                ('id', '!=', record.partner_id.id),
            ], limit=1)
            if clash:
                raise ValidationError(_(
                    "%(email)s is already the main email of %(partner)s.",
                    email=record.email, partner=clash.display_name))
