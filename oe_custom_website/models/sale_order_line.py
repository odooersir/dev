# oe_custom_website/models/sale_order_line.py
from odoo import models, fields


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # ─── Link to original offer ───────────────────────────────────
    sbs_data_id = fields.Many2one(
        'sbs.data',
        string='Marketplace Offer',
        ondelete='set null',
        index=True,
        help='Link to the original marketplace offer'
    )

    # ─── Snapshot: captured at add-to-cart time ───────────────────
    snapshot_seller_id = fields.Many2one(
        'res.partner',
        string='Seller (Snapshot)',
        help='Seller at the time of adding to cart'
    )
    snapshot_seller_name = fields.Char(
        string='Seller Name (Snapshot)'
    )
    snapshot_price = fields.Float(
        string='Price (Snapshot)',
        digits='Product Price',
        help='Selling Price at add time'
    )
    snapshot_rank = fields.Integer(
        string='Rank (Snapshot)',
        help='Offer rank at add time'
    )
    snapshot_ean = fields.Char(
        string='EAN (Snapshot)'
    )
    # ← فیلد جدید برای progress bar
    snapshot_import_number = fields.Char(
        string='Import Number (Snapshot)',
        help='شناسه لیست قیمت در زمان افزودن به سبد'
    )
    snapshot_add_date = fields.Datetime(
        string='Added to Cart',
        default=fields.Datetime.now,
        readonly=True
    )

    # ─── SQL Constraint ────────────────────────────────────────────
    _sql_constraints = [
        (
            'unique_product_offer_per_order',
            'UNIQUE(order_id, product_id, sbs_data_id)',
            'Cannot add the same offer for the same product twice in one order!'
        )
    ]
