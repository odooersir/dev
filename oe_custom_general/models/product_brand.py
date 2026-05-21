from odoo import models, fields, api


class ProductBrand(models.Model):
    _name = 'product.brand'
    _description = 'Product Brand'

    name = fields.Char(required=True, translate=True)
    description = fields.Text()
    logo = fields.Binary()
    active = fields.Boolean(default=True)


    product_ids = fields.One2many(
        "product.template", "brand_id", string="Brand Products"
    )
    products_count = fields.Integer(
        string="Number of products", compute="_compute_products_count"
    )

    website_url = fields.Char(compute='_compute_website_url')

    @api.depends("product_ids")
    def _compute_products_count(self):
        product_model = self.env["product.template"]
        groups = product_model.read_group(
            [("brand_id", "in", self.ids)],
            ["brand_id"],
            ["brand_id"],
            lazy=False,
        )
        data = {group["brand_id"][0]: group["__count"] for group in groups}
        for brand in self:
            brand.products_count = data.get(brand.id, 0)


    def _compute_website_url(self):
        for brand in self:
            brand.website_url = f'/shop/brand/{ self.env['ir.http']._slug(brand)}'
    

