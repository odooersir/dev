from odoo import models, api

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_force_delete(self):
        for picking in self:
            # محصولات و لا‌ین‌های مرتبط رو پیدا کنیم
            self.env.cr.execute("""
                SELECT DISTINCT product_id 
                FROM stock_move_line 
                WHERE picking_id = %s
            """, (picking.id,))
            products = [r[0] for r in self.env.cr.fetchall()]

            # حذف لا‌ین‌ها و مووها
            self.env.cr.execute("DELETE FROM stock_move_line WHERE picking_id = %s", (picking.id,))
            self.env.cr.execute("DELETE FROM stock_move WHERE picking_id = %s", (picking.id,))
            
            # حذف خود picking
            self.env.cr.execute("DELETE FROM stock_picking WHERE id = %s", (picking.id,))

            # آپدیت موجودی فقط برای محصولات مربوطه
            self.env['stock.quant'].sudo().action_balance_qty_for_products(products)
