# -*- coding: utf-8 -*-

import random
import string
from odoo import fields, models, api

class ResPartner(models.Model):
    _inherit = "res.partner"

    partner_code = fields.Char(string='Partner Code', copy=False, index=True)
    mobile = fields.Char(string='Mobile')
    mobile2 = fields.Char(string='Mobile 2')
    phone2 = fields.Char(string='Phone 2')

    @api.model
    def _generate_unique_code(self, length=6):
        """Generate a unique random alphanumeric code (uppercase letters + digits)."""
        charset = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(charset, k=length))
            # بررسی تکراری نبودن کد
            if not self.search([('partner_code', '=', code)], limit=1):
                return code

    @api.model_create_multi
    def create(self, vals_list):

        for vals in vals_list:
            if not vals.get('partner_code'):
                vals['partner_code'] = self._generate_unique_code()
                
        return  super().create(vals_list)

    def _generate_missing_partner_codes(self):
        """Assign unique random partner_code to existing records without one."""
        partners = self.search([('partner_code', '=', False)])
        #partners = self.search([])
        for partner in partners:
            partner.partner_code = self._generate_unique_code()
