# -*- coding: utf-8 -*-
"""
Override _search_has_published_products برای حل مشکل کندی /shop

مشکل اصلی:
  کد اصلی Odoo:
    self._search([('product_tmpl_ids', 'any', [('is_published', '=', True), ('active', '=', True)])])
    
  این یک nested subquery می‌سازد:
    SELECT id FROM product_public_category
    WHERE EXISTS (
        SELECT 1 FROM product_public_category_product_template_rel rel
        WHERE rel.product_public_category_id = ppc.id
        AND rel.product_template_id IN (
            SELECT id FROM product_template WHERE is_published=True AND active=True
        )
    )
  
  بدون index روی rel table این query بسیار کند است.
  علاوه بر این در هر request چندین بار فراخوانی می‌شود.

راه‌حل:
  1. SQL مستقیم با JOIN که از index استفاده کند
  2. Request-level cache تا در یک page load فقط یک بار اجرا شود
"""
from odoo import api, models


class ProductPublicCategory(models.Model):
    _inherit = 'product.public.category'

    @api.model
    def _search_has_published_products(self, operator, value):
        if operator != 'in':
            return NotImplemented

        published_categ_ids = self._get_published_category_ids()

        # Note that if the `value` is False, the ORM will invert the domain below
        return [
            '|',
            ('id', 'in', published_categ_ids),
            ('id', 'parent_of', published_categ_ids),
        ]

    @api.model
    def _get_published_category_ids(self):
        """
        یک query بهینه برای پیدا کردن categories با published products.
        
        نتیجه را در request object cache می‌کنیم تا در یک page load
        فقط یک بار به DB رفته شود.
        
        :return: list of category IDs that have at least one published product
        :rtype: list[int]
        """
        # سعی می‌کنیم از request-level cache استفاده کنیم
        cache_key = '_sbs_published_categ_ids_v1'
        try:
            from odoo.http import request as http_request
            if http_request:
                cached = getattr(http_request, cache_key, None)
                if cached is not None:
                    return cached
        except RuntimeError:
            # خارج از context یک request HTTP هستیم
            http_request = None

        # website filter — اگر website_id در context بود فیلتر می‌کنیم
        website_id = self.env.context.get('website_id')

        if website_id:
            self.env.cr.execute("""
                SELECT DISTINCT rel.product_public_category_id
                FROM product_public_category_product_template_rel rel
                JOIN product_template pt ON pt.id = rel.product_template_id
                WHERE pt.is_published = true
                  AND pt.active = true
                  AND (pt.website_id IS NULL OR pt.website_id = %s)
            """, (website_id,))
        else:
            self.env.cr.execute("""
                SELECT DISTINCT rel.product_public_category_id
                FROM product_public_category_product_template_rel rel
                JOIN product_template pt ON pt.id = rel.product_template_id
                WHERE pt.is_published = true
                  AND pt.active = true
            """)

        result = [row[0] for row in self.env.cr.fetchall()]

        # ذخیره در request object
        try:
            if http_request:
                setattr(http_request, cache_key, result)
        except Exception:
            pass

        return result

    def _auto_init(self):
        """
        ایجاد index های لازم برای بهبود کارایی.
        این index ها باعث می‌شوند query بالا بسیار سریع‌تر اجرا شود.
        """
        result = super()._auto_init()

        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS website_pricelist_shop_rel_tmpl_idx
                ON product_public_category_product_template_rel (product_template_id);

            CREATE INDEX IF NOT EXISTS website_pricelist_shop_rel_categ_idx
                ON product_public_category_product_template_rel (product_public_category_id);

            CREATE INDEX IF NOT EXISTS website_pricelist_shop_pt_published_idx
                ON product_template (is_published, active, website_id)
                WHERE is_published = true AND active = true;
        """)

        return result
