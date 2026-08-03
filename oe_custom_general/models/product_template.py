# -*- coding: utf-8 -*-

from odoo import fields, models, api
class ProductTemplate(models.Model):
    
    _inherit = "product.template"

    net_weight = fields.Float(string='Net Weight')

    height = fields.Float(string='Height')
    width = fields.Float(string='Width')
    depth = fields.Float(string='Depth')


    weight_unit = fields.Char(string="Weight Unit", readonly=True)
    height_unit = fields.Char(string="Height Unit", readonly=True)
    width_unit = fields.Char(string="Width Unit", readonly=True)
    depth_unit = fields.Char(string="Depth Unit", readonly=True)




    country_origin = fields.Many2one('res.country', string='Country Of Origin') 
    hs_code = fields.Char(string='HS Code')

    product_link = fields.Char(string='Product Link')

    brand_id = fields.Many2one('product.brand',ondelete='restrict', string='Brand') 

    creation_method= fields.Selection([
        ('manual', 'Manual Creation'),
        ('sbs', 'Import From SBS'),
        ('excel', 'Import From Excel'),
       
    ], string='Creation Method')

    cover_language = fields.Char(string='Language')

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        domain = []
        if name:
            domain = ['|', ('barcode', operator, name), ('name', operator, name)]
        return self._search(domain + args, limit=limit, access_rights_uid=name_get_uid)


   
