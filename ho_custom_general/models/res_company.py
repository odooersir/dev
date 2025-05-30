# -*- coding: utf-8 -*-

from odoo import fields, models
class ResCompany(models.Model):
    _inherit = "res.company"

    national_identity = fields.Char(string='National ID')