# -*- coding: utf-8 -*-

from odoo import fields, models, api

class ResCountry(models.Model):
    _inherit = "res.country"



    code3 = fields.Char(
        string='Country Code 3', size=3,
        required=True,
        help='The ISO country code in three chars. \nYou can use this field for quick search.')



    @api.depends('code3', 'name')
    def _compute_display_name(self):
        for country in self:
            country.display_name = country.code3 or country.name
