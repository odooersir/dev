# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, api


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    mobile = fields.Char(
        'Mobile', tracking=50,
        compute='_compute_mobile', inverse='_inverse_mobile', readonly=False, store=True)

    @api.depends('partner_id.mobile')
    def _compute_mobile(self):
        for lead in self:
            if lead.partner_id.mobile and lead._get_partner_mobile_update():
                lead.mobile = lead.partner_id.mobile

    def _inverse_mobile(self):
        for lead in self:
            if lead._get_partner_mobile_update(force_void=False):
                lead.partner_id.mobile = lead.mobile


    def _get_partner_mobile_update(self, force_void=True):
            """Calculate if we should write the mobile on the related partner. When
            the mobile of the lead / partner is an empty string, we force it to False
            to not propagate a False on an empty string.

            Done in a separate method so it can be used in both ribbon and inverse
            and compute of mobile update methods.

            :param bool force_void: if False, skip when lead has a void mobile value.
            This is used notably to avoid propagating void lead value to a valid
            partner value.
            """
            self.ensure_one()
            if self.partner_id and (force_void or self.mobile) and self.mobile != self.partner_id.mobile:
                lead_mobile_formatted = self._phone_format(fname='mobile') or self.mobile or False
                partner_mobile_formatted = self.partner_id._phone_format(fname='mobile') or self.partner_id.mobile or False
                return lead_mobile_formatted != partner_mobile_formatted
            return False
    