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



    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        
        print ("DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD")

        args = args or []
        domain = []
        if name:
            domain = ['|', ('barcode', operator, name), ('name', operator, name)]
        return self._search(domain + args, limit=limit, access_rights_uid=name_get_uid)

    def _search_display_name(self, operator, value):
        
        print ("SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSsssss")
        domain = super()._search_display_name(operator, value)
        
        # اگر مقدار جستجو عدد یا رشته‌ای شبیه بارکد باشه، بارکد رو هم جستجو کن
        if value:
            barcode_domain = [('product_variant_ids.barcode', operator, value)]
            if operator in Domain.NEGATIVE_OPERATORS:
                domain = Domain.AND([domain, barcode_domain])
            else:
                query = SQL(
                    """((%s) UNION ALL (%s))""",
                    self._search(domain).select(),
                    self._search(barcode_domain).select(),
                )
                domain = [('id', 'in', query)]
        
        return domain



    def _search_get_detail(self, website, order, options):
        res = super()._search_get_detail(website, order, options)
        res['search_fields'].extend(['product_variant_ids.barcode', 'brand_id.name'])
        return res


    def _search_render_results(self, fetch_fields, mapping, icon, limit):
        
        print ("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        print (fetch_fields)
        fetch_fields.append('barcode')
        fetch_fields.append('brand_id')

        with_image = 'image_url' in mapping
        with_category = 'extra_link' in mapping
        #with_price = 
        if 'detail' in mapping:
            mapping.pop('detail')
        #with_price=False
        results_data = super()._search_render_results(fetch_fields, mapping, icon, limit)
        print("KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKkk")
        print (results_data)
        current_website = self.env['website'].get_current_website()
        for product, data in zip(self, results_data):
            categ_ids = product.public_categ_ids.filtered(lambda c: not c.website_id or c.website_id == current_website)
            #if with_price:
            #    combination_info = product._get_combination_info(only_template=True)
            #   data['price'], list_price = self._search_render_results_prices(
            #        mapping, combination_info
            #    )
            #    if list_price:
            #        data['list_price'] = list_price

            if with_image:
                #data['image_url'] = '/web/image/product.template/%s/image_128' % data['id']
                data['image_url'] = "https://img.cliimax.io/awr3dxEq__0MAeCuu3w82ONS97QFbUkUlhTUBrgQdGk/plain/local:///climax1/product.template/"+str(data['id'])+"/"+str(data['id'])+".jpg"
            if with_category and categ_ids:
                data['category'] = self.env['ir.ui.view'].sudo()._render_template(
                    "website_sale.product_category_extra_link",
                    {
                        'categories': categ_ids,
                        'slug': self.env['ir.http']._slug,
                        'shop_path': SHOP_PATH,
                    }
                )
        print (results_data)
        return results_data

   
