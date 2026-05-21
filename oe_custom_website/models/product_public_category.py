# -*- coding: utf-8 -*-
"""
Override product.public.category برای حل مشکل N+1 کند در /shop

مشکل از log:
  Thread 1 این query را 20 بار با ~250ms پشت سر هم اجرا می‌کند.

راه‌حل:
  از ormcache (registry-level) استفاده کنیم.
  نتیجه برای همه workers و همه requests یکسان است
  تا زمانی که محصولی publish/unpublish نشود.

FIX:
  @classmethod + @ormcache('website_id') → NameError: 'self' not defined
  چون ormcache برای key lambda از 'self' به عنوان arg[0] استفاده می‌کند.
  با @classmethod اولین arg برابر 'cls' است → کرش.
  راه‌حل: @api.model به جای @classmethod
"""
from odoo import api, models
from odoo.tools import ormcache


class ProductPublicCategory(models.Model):
    _inherit = 'product.public.category'

    @api.depends('product_tmpl_ids.is_published', 'child_id.has_published_products')
    def _compute_has_published_products(self):
        """
        Override: یک query برای همه categories به جای N query.
        """
        if not self:
            return

        website_id = self.env.context.get('website_id') or False

        # ormcache registry-level — یک بار اجرا برای هر website_id
        all_published = set(self._fetch_published_ids(website_id))

        # محاسبه برای هر category
        for category in self:
            if category.id in all_published:
                category.has_published_products = True
                continue
            category.has_published_products = self._has_published_descendant(
                category, all_published
            )

    def _has_published_descendant(self, category, published_ids):
        """بدون query اضافه — recursive روی child_id."""
        for child in category.child_id:
            if child.id in published_ids:
                return True
            if self._has_published_descendant(child, published_ids):
                return True
        return False

    @api.model
    def _search_has_published_products(self, operator, value):
        if operator != 'in':
            return NotImplemented
        website_id = self.env.context.get('website_id') or False
        published_categ_ids = list(self._fetch_published_ids(website_id))
        return [
            '|',
            ('id', 'in', published_categ_ids),
            ('id', 'parent_of', published_categ_ids),
        ]

    @api.model
    @ormcache('website_id')
    def _fetch_published_ids(self, website_id=False):
        """
        ormcache روی @api.model — کار می‌کند چون:
          - ormcache برای key از 'self' (arg[0]) استفاده می‌کند ✓
          - @api.model → self = model singleton (env-independent برای cache key)
          - نتیجه در registry RAM می‌ماند تا clear_cache() فراخوانی شود

        ⚠️  @classmethod + @ormcache → NameError: 'self' not defined (bug قبلی)
        """
        cr = self.env.cr
        if website_id:
            cr.execute("""
                SELECT DISTINCT rel.product_public_category_id
                FROM product_public_category_product_template_rel rel
                JOIN product_template pt ON pt.id = rel.product_template_id
                WHERE pt.is_published = true
                  AND pt.active = true
                  AND (pt.website_id IS NULL OR pt.website_id = %s)
            """, (website_id,))
        else:
            cr.execute("""
                SELECT DISTINCT rel.product_public_category_id
                FROM product_public_category_product_template_rel rel
                JOIN product_template pt ON pt.id = rel.product_template_id
                WHERE pt.is_published = true
                  AND pt.active = true
            """)
        return frozenset(row[0] for row in cr.fetchall())

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS idx_ppc_rel_tmpl
                ON product_public_category_product_template_rel (product_template_id);

            CREATE INDEX IF NOT EXISTS idx_ppc_rel_categ
                ON product_public_category_product_template_rel (product_public_category_id);

            CREATE INDEX IF NOT EXISTS idx_pt_published_active
                ON product_template (is_published, active, website_id)
                WHERE is_published = true AND active = true;
        """)
        return result


class ProductTemplatePublish(models.Model):
    _inherit = 'product.template'

    def write(self, vals):
        result = super().write(vals)
        if 'is_published' in vals or 'active' in vals or 'public_categ_ids' in vals:
            self.env.registry.clear_cache()
        return result
