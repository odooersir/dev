from odoo import models, api

class StockQuantBalance(models.Model):
    _inherit = 'stock.quant'

    def action_balance_qty_for_products(self, product_ids):
        if not product_ids:
            return

        # صفر کردن فقط کوانت‌های همین محصولات
        self.sudo().search([('product_id', 'in', product_ids)]).write({'quantity': 0})

        sqlscrpt = """
            SELECT product_id, location_id, location_dest_id, quantity, lot_id
            FROM stock_move_line
            WHERE state = 'done' AND product_id = ANY(%s)
        """
        self._cr.execute(sqlscrpt, (product_ids,))
        res = self._cr.dictfetchall()

        for i in res:
            # location_id -
            domain = [
                ('product_id', '=', i['product_id']),
                ('location_id', '=', i['location_id']),
                ('lot_id', '=', i.get('lot_id'))
            ]
            sqrcrd = self.sudo().search(domain, limit=1)
            if not sqrcrd:
                self.sudo().create({
                    'product_id': i['product_id'],
                    'location_id': i['location_id'],
                    'lot_id': i.get('lot_id'),
                    'quantity': -i['quantity']
                })
            else:
                sqrcrd.sudo().write({
                    'quantity': sqrcrd.quantity - i['quantity']
                })

            # location_dest_id +
            domain = [
                ('product_id', '=', i['product_id']),
                ('location_id', '=', i['location_dest_id']),
                ('lot_id', '=', i.get('lot_id'))
            ]
            sqrcrd = self.sudo().search(domain, limit=1)
            if not sqrcrd:
                self.sudo().create({
                    'product_id': i['product_id'],
                    'location_id': i['location_dest_id'],
                    'lot_id': i.get('lot_id'),
                    'quantity': i['quantity']
                })
            else:
                sqrcrd.sudo().write({
                    'quantity': sqrcrd.quantity + i['quantity']
                })
