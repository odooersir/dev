from odoo import models, fields, api, _
from odoo.exceptions import UserError
from collections import defaultdict
from datetime import date
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)



class SBS(models.Model):
    _name = 'sbs.data'
    _description = 'Smart Buying System Data'
    _order = 'import_number desc'
    
    import_date = fields.Date(string='Import Date', required=True, index=True)
    ean = fields.Char(string='Barcode', required=True, index=True)
    product_name = fields.Char(string='Product Name')
    case_size = fields.Integer(string='Unit/Case')
    layer = fields.Integer(string='Case/Layer')
    pallet = fields.Integer(string='Case/Pallet')
    note = fields.Text(string='Note')
    coo = fields.Many2one('res.country', string='CoO', help='Country of Origin',
                          related='product_id.country_origin', store=True, readonly=False)
    supplier_unit_price = fields.Monetary(string='Supplier Unit Price', help='Supplier Unit Price', currency_field='currency_id', index=True, groups="oe_sbs.group_sbs_purchase,oe_sbs.group_sbs_admin")
    currency_id = fields.Many2one('res.currency', string='Currency')
    usd_currency_id = fields.Many2one('res.currency', string='USD Currency',
                                      compute='_compute_display_currencies',
                                      help='Helper to render USD-denominated prices with a symbol.')
    supplier_name = fields.Char(string='Supplier Name', index=True, groups="oe_sbs.group_sbs_purchase,oe_sbs.group_sbs_admin")

    # New fields
    excel_filename = fields.Char(string='Excel File Name', readonly=True, index=True, groups="oe_sbs.group_sbs_purchase,oe_sbs.group_sbs_admin")
    end_date = fields.Date(string='Offer Validity', index=True)
    # Expiry of the physical product (e.g. the date printed on the pack), which
    # can differ per offer/batch - so it lives per-row on sbs.data, not on
    # product.template. Distinct from end_date (offer/price validity).
    product_expiry_date = fields.Date(string='Product Expiry Date', index=True)

    converted_price = fields.Monetary(string='Converted Supplier Price (USD)', currency_field='usd_currency_id')
    selling_price = fields.Monetary(string='Selling Price ($)', help='Selling Price (USD)', currency_field='usd_currency_id')
    selling_price_2 = fields.Monetary(string='Selling Price', help='Selling Price (Original Currency)', currency_field='currency_id')

   

    selling_price_aed = fields.Monetary(string='Selling Price (Đ)', currency_field='aed_currency_id',
                                        help='Selling Price in AED (Dirham)')
    selling_price_eur = fields.Monetary(string='Selling Price (€)',   currency_field='eur_currency_id',
                                        help='Selling Price in EUR')
    selling_price_gbp = fields.Monetary(string='Selling Price (£)',   currency_field='gbp_currency_id',
                                        help='Selling Price in GBP')

    
    aed_currency_id = fields.Many2one('res.currency', string='AED', compute='_compute_display_currencies')
    eur_currency_id = fields.Many2one('res.currency', string='EUR', compute='_compute_display_currencies')
    gbp_currency_id = fields.Many2one('res.currency', string='GBP', compute='_compute_display_currencies')

    def _compute_display_currencies(self):
        aed = self.env.ref('base.AED', raise_if_not_found=False)
        eur = self.env.ref('base.EUR', raise_if_not_found=False)
        gbp = self.env.ref('base.GBP', raise_if_not_found=False)
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        for rec in self:
            rec.aed_currency_id = aed
            rec.eur_currency_id = eur
            rec.gbp_currency_id = gbp
            rec.usd_currency_id = usd



        
    min_sell = fields.Monetary(string='Min Sell', help='Min Sell (Original Currency)', currency_field='currency_id')

    rank = fields.Integer(string='Rank', readonly=True, index=True)
    no_of_ranks = fields.Integer(string='No of Ranks')
    import_number = fields.Char(string='IN', help='Import Number', readonly=True, index=True)

    supplier_code = fields.Char(string='Supplier Code', help='Supplier Code')

    is_expired = fields.Boolean(index=True)

    lead_time = fields.Char(string='Lead Time')
    moq = fields.Char(string='MOQ')
    mov = fields.Monetary(string='MOV', currency_field='currency_id',
                          help='Minimum Order Value (in the price-list currency)')
    # Raw MOV as found in the supplier file, BEFORE the profit margin is applied.
    # Kept so MOV can be recomputed when the profit margin changes, without
    # re-importing. mov = round_up((1 + margin) * mov_base, 1000).
    mov_base = fields.Monetary(string='MOV (base)', currency_field='currency_id',
                               help='MOV before profit margin; used to recompute MOV.')
    availabale_qty = fields.Char(string='Available Units')
    incoterms = fields.Char(string='Incoterms')
    # Customs status, split into three independent facts. A single 'T1/T2' Char
    # could not express them: a stock can be partly T1 and partly T2, and EUR.1
    # is a separate document question altogether. 'available' means the supplier
    # can arrange EU clearance on request rather than holding cleared stock.
    t1 = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='T1')
    t2 = fields.Selection([('yes', 'Yes'), ('no', 'No'),
                           ('available', 'Available')], string='T2 (EU Clean)')
    euro1 = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='EUR.1')
    batch_code = fields.Char(string='Batch Code')
    payment_term = fields.Char(string='Payment Term')

    document_id = fields.Many2one('documents.document', string='Document', ondelete='restrict', index=True)

    def action_open_template(self):
        """Open the Import Mapping (template) used for this row, taken from the
        row's related document. Opens in a new page (act_window)."""
        self.ensure_one()
        template = self.document_id.template_id if self.document_id else False
        if not template:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _("Import Mapping"),
            'res_model': 'sbs.import.template',
            'res_id': template.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    doc_is_spreadsheet = fields.Boolean(
        related='document_id.sbs_is_spreadsheet', readonly=True,
        string="Source Is Spreadsheet",
        help="Technical: drives the visibility of the Excel preview button.")

    def action_sbs_preview_excel(self):
        """
        Open this row's SOURCE file in the read-only Excel viewer.
        Delegates to the document so both list views share one implementation.
        """
        self.ensure_one()
        if not self.document_id:
            return False
        return self.document_id.action_sbs_preview_excel()

    def action_view_same_document(self):
        """Open the Documents list focused on this row's source document, with a
        REMOVABLE name filter so clearing it returns to the normal list."""
        self.ensure_one()
        if not self.document_id:
            return False
        ctx = dict(self.env.context)
        ctx['search_default_name'] = self.document_id.name or ''
        return {
            'type': 'ir.actions.act_window',
            'name': _("Document - %s") % (self.document_id.name or ''),
            'res_model': 'documents.document',
            'view_mode': 'list,form',
            'target': 'current',
            'context': ctx,
        }

    supplier_id = fields.Many2one('res.partner', ondelete='restrict', string='Supplier', index=True)
    product_id = fields.Many2one('product.template', ondelete='restrict', string='Product', index=True)

    brand_id = fields.Many2one('product.brand', string='Brand', ondelete='restrict',
                               related='product_id.brand_id', store=True)

    spreadsheet_url = fields.Char(string='Spreadsheet URL', compute='_compute_spreadsheet_url', store=False)

    converted_rate = fields.Float(string='Converted Rate', digits=(16, 2))

    uom_id = fields.Many2one('uom.uom', string='Unit of Measure',  help='Unit of measure derived from case_size', readonly=True, )


    unit_per_layer = fields.Integer(string='Unit/Layer')
    unit_per_pallet = fields.Integer(string='Unit/Pallet')
    hs_code = fields.Char(string='HS Code(Tariff)',
                          related='product_id.hs_code', store=True, readonly=False)
    # Languages printed on the product packaging (free text, for customer info).
    # Intrinsic product attribute -> stored related; the source field lives on
    # product.template in another module.
    cover_language = fields.Char(string='Language',
                                 related='product_id.cover_language',
                                 store=True, readonly=False)

    size = fields.Char(string='Size')

    def _auto_init(self):
        res = super()._auto_init()
        # Composite indexes for most common query patterns
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sbs_data_import_number_ean_idx
                ON sbs_data (import_number, ean);

            CREATE INDEX IF NOT EXISTS sbs_data_supplier_import_date_idx
                ON sbs_data (supplier_name, import_date);

            CREATE INDEX IF NOT EXISTS sbs_data_ean_expired_idx
                ON sbs_data (ean, is_expired);

            CREATE INDEX IF NOT EXISTS sbs_data_product_import_idx
                ON sbs_data (product_id, import_number)
                WHERE product_id IS NOT NULL;

            CREATE INDEX IF NOT EXISTS sbs_data_ean_price_idx
                ON sbs_data (ean, converted_price);
        """)
        return res


    
    @api.depends('document_id')
    def _compute_spreadsheet_url(self):
        for rec in self:
            if rec.document_id and rec.document_id.mimetype == 'application/o-spreadsheet':
                rec.spreadsheet_url = f'/odoo/documents/spreadsheet/{rec.document_id.id}'
            else:
                rec.spreadsheet_url = False

    def action_open_spreadsheet(self):
        self.ensure_one()
        if not self.spreadsheet_url:
            raise UserError("No related spreadsheet found.")
        return {
            'type': 'ir.actions.act_url',
            'url': self.spreadsheet_url,
            'target': 'new',  # یا 'self' اگر می‌خواهی در همان تب باز شود
        }



   
    
    def compute_expired_ean(self):

        all_records=self
        if not self:
            all_records = self.search([])
        today = date.today()
        for record in all_records:
                record.is_expired = bool(record.end_date and record.end_date < today)

    @api.model
    def cron_nightly_recompute(self):
        """
        Nightly batch: run every SBS-wide recomputation in one pass so all
        derived data stays fresh without manual action. Scheduled by the
        ir.cron record 'cron_sbs_nightly_recompute'.

        Order matters:
          1-2. resolve product/supplier links first (later steps read them)
          3.   flag expired rows (the offer-list sync filters on is_expired)
          4.   recompute converted/selling prices with today's FX rates
          5.   re-rank on the FRESH prices (raw SQL -> needs an explicit flush)
          6.   rebuild the offer-list summaries from the final values

        sudo() is required: supplier_unit_price and supplier_name are
        group-restricted, and the cron user may not hold those groups - without
        sudo they read as 0/False and compute_selling_prices would wipe every
        selling price. Each step is guarded so one failure doesn't stop the rest.
        """
        self = self.sudo()
        records = self.search([])

        steps = [
            ('update_products_from_ean',   lambda: self.update_products_from_ean()),
            ('update_suppliers_from_code', lambda: self.update_suppliers_from_code()),
            ('compute_expired_ean',        lambda: records.compute_expired_ean()),
            ('compute_selling_prices',     lambda: records.compute_selling_prices()),
            ('action_rank_products',       lambda: self._nightly_rank()),
            ('sync_offer_lists',           lambda: records._sync_offer_lists()),
        ]
        for name, fn in steps:
            try:
                fn()
                _logger.info("[SBS nightly] %s done (%s records).", name, len(records))
            except Exception as e:
                _logger.exception("[SBS nightly] %s failed: %s", name, e)
        return True

    def _nightly_rank(self):
        """action_rank_products runs raw SQL against sbs_data. Flush the pending
        ORM writes first, otherwise it ranks yesterday's converted_price, and
        invalidate afterwards so the cache doesn't keep the stale rank."""
        self.env.flush_all()
        self.action_rank_products()
        self.env.invalidate_all()
        return True

    @api.model
    def _link_by_code(self, records, code_field, target_model, target_field,
                      link_field, force=False, label=''):
        """
        Shared engine for the two nightly linking steps: match a text code on
        sbs.data against a field on another model and store the resulting id.

        Both callers used to loop row by row, issuing one search plus one write
        per record - tens of thousands of queries on a full price list. Here the
        whole mapping is read in a few queries and the writes are grouped by
        target id.

        force=False only fills EMPTY links. See the callers for why that matters.
        """
        if not force:
            records = records.filtered(lambda r: not r[link_field])
        codes = sorted({(r[code_field] or '').strip()
                        for r in records if (r[code_field] or '').strip()})
        if not codes:
            return 0

        Target = self.env[target_model].sudo()
        mapping, duplicates = {}, set()
        CHUNK = 2000
        for i in range(0, len(codes), CHUNK):
            chunk = codes[i:i + CHUNK]
            # order by id so a code shared by several targets always resolves to
            # the same one. The old code used search(limit=1) with the model's
            # default order, which is usually by NAME - so simply renaming a
            # product could silently move every row onto a different one.
            for row in Target.search_read([(target_field, 'in', chunk)],
                                          [target_field], order='id'):
                key = (row[target_field] or '').strip()
                if key in mapping:
                    duplicates.add(key)
                    continue
                mapping[key] = row['id']
        if duplicates:
            _logger.warning(
                "[SBS %s] %s code(s) match more than one %s; the lowest id wins. "
                "First few: %s", label, len(duplicates), target_model,
                sorted(duplicates)[:5])

        grouped = defaultdict(list)
        for rec in records:
            target_id = mapping.get((rec[code_field] or '').strip())
            if target_id and rec[link_field].id != target_id:
                grouped[target_id].append(rec.id)

        updated = 0
        for target_id, ids in grouped.items():
            self.browse(ids).write({link_field: target_id})
            updated += len(ids)
        _logger.info("[SBS %s] linked %s row(s) via %s unique code(s).",
                     label, updated, len(codes))
        return updated

    @api.model
    def update_products_from_ean(self, force=False):
        """
        Fill product_id from the row's barcode.

        Only rows with an EMPTY product_id are touched. The guard used to be
        commented out, so every night re-resolved and rewrote the link on EVERY
        row: any manual correction was silently reverted the following night,
        and the work was repeated on rows that were already linked. Pass
        force=True for a deliberate one-off re-link of the whole table.
        """
        records = self if self else self.search([('ean', '!=', False)])
        return self._link_by_code(records, 'ean', 'product.template', 'barcode',
                                  'product_id', force=force, label='Product')

    @api.model
    def update_suppliers_from_code(self, force=False):
        """Fill supplier_id from the row's supplier_code. Empty links only,
        unless force=True."""
        records = self if self else self.search([('supplier_code', '!=', False)])
        return self._link_by_code(records, 'supplier_code', 'res.partner',
                                  'partner_code', 'supplier_id', force=force,
                                  label='Supplier')

    def compute_selling_prices(self):

        import math
        # Cache configuration values
        ICP = self.env['ir.config_parameter'].sudo()
        margin = float(ICP.get_param('oe_sbs.default_profit_margin', '8')) / 100
        min_margin = float(ICP.get_param('oe_sbs.min_profit_margin', '7')) / 100

        # Cache base USD currency
        usd_currency = self.env.ref('base.USD')

        # Determine records
        if self:
            records = self
        elif self.env.context.get('active_ids'):
            records = self.browse(self.env.context['active_ids'])
        else:
            records = self.search([])


        today = fields.Date.today()
        for record in records:
            if record.currency_id == usd_currency:
                converted_price = record.supplier_unit_price
                converted_rate=1
            else:
                cur=record.currency_id
                converted_price = cur._convert(record.supplier_unit_price, usd_currency,  self.env['res.company'].browse(1), today)
                converted_rate= cur._get_conversion_rate(cur, usd_currency,  self.env['res.company'].browse(1) , date.today())



            # Pre-calculate all values
            record_vals = {
                'converted_price': converted_price,
                'selling_price': converted_price * (1 + margin),
                'selling_price_2': record.supplier_unit_price * (1 + margin),
                'min_sell': record.supplier_unit_price * (1 + min_margin),
                'converted_rate':converted_rate
            }

            # NEW: AED / EUR / GBP from the Original-Currency selling price
            record_vals.update(
                self._convert_selling_prices(record.currency_id, record_vals['selling_price_2'], today)
            )

            # MOV is margin-driven too: recompute it from its stored raw value
            # (mov_base) using the SAME margin, so selling prices and MOV always
            # move together when default_profit_margin changes. Rows without a
            # mov_base (e.g. MOQ-only offers) are left untouched.
            if record.mov_base:
                record_vals['mov'] = int(
                    math.ceil((1 + margin) * record.mov_base / 1000.0) * 1000)

            # Use write to avoid triggering field recomputes for each assignment
            record.write(record_vals)

        return True


  
    
    def action_rank_products(self):
        """Rank products with standard competition ranking (1223 style) within each EAN group"""

        query = """
            WITH RankedData AS (
                SELECT id,
                    DENSE_RANK() OVER (PARTITION BY ean ORDER BY converted_price ASC) as new_rank,
                    COUNT(id) OVER (PARTITION BY ean) as ean_count
                FROM sbs_data
            )
            UPDATE sbs_data
            SET rank = RankedData.new_rank,
                no_of_ranks = RankedData.ean_count
            FROM RankedData
            WHERE sbs_data.id = RankedData.id;
        """
        
        self.env.cr.execute(query)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Products ranked with competition ranking (1223 style)'),
                'sticky': False,
            }
        }

    
    
    def action_rank_products__(self):
        """Rank products with standard competition ranking (1223 style) within each EAN group"""

        self.env.cr.execute("""
            SELECT id, ean, converted_price
            FROM sbs_data
            ORDER BY ean, converted_price ASC
        """)
        
        batch_size = 1000
        current_ean = None
        current_price = None
        rank = 0
        records_to_update = []
        
        for row in self.env.cr.fetchall():
            record_id, ean, price = row
            
            if ean != current_ean:
                current_ean = ean
                current_price = price
                rank = 1
                records_to_update.append((record_id, rank))
            elif price == current_price:
                records_to_update.append((record_id, rank))
            else:
                current_price = price
                rank += 1
                records_to_update.append((record_id, rank))
            
            if len(records_to_update) >= batch_size:
                self._update_ranks_in_bulk(records_to_update)
                records_to_update = []
        
        if records_to_update:
            self._update_ranks_in_bulk(records_to_update)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Products ranked with competition ranking (1223 style)'),
                'sticky': False,
            }
        }

    def _update_ranks_in_bulk(self, id_rank_pairs):
        """Bulk update ranks and counts for EAN groups"""
        if not id_rank_pairs:
            return
        
        record_ids = [id for id, _ in id_rank_pairs]
        self.env.cr.execute("""
            SELECT s1.id, COUNT(s2.id) as count
            FROM sbs_data s1
            JOIN sbs_data s2 ON s1.ean = s2.ean
            WHERE s1.id IN %s
            GROUP BY s1.id
        """, (tuple(record_ids),))
        
        ean_counts = {id: count for id, count in self.env.cr.fetchall()}
        
        cases_rank = []
        cases_count = []
        for id, rank in id_rank_pairs:
            cases_rank.append(f"WHEN {id} THEN {rank}")
            cases_count.append(f"WHEN {id} THEN {ean_counts.get(id, 0)}")
        
        query = f"""
            UPDATE sbs_data
            SET 
                rank = CASE id {' '.join(cases_rank)} END,
                no_of_ranks = CASE id {' '.join(cases_count)} END
            WHERE id IN ({','.join(str(id) for id in record_ids)})
        """
        
        self.env.cr.execute(query)




    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        new_domain = []
        import_number_exact = None
        ean_search = None

        for cond in domain:
            if cond in ('&', '|', '!'):
                new_domain.append(cond)
                continue

            if (
                isinstance(cond, (list, tuple))
                and cond[0] == 'import_number'
                and cond[1] == 'ilike'
                and isinstance(cond[2], str)
            ):
                import_number_exact = cond[2]
                continue

            elif (
                isinstance(cond, (list, tuple))
                and cond[0] == 'ean'
                and cond[1] == 'ilike'
                and isinstance(cond[2], str)
            ):
                ean_search = cond[2].strip()
                continue

            elif (
                isinstance(cond, (list, tuple))
                and cond[1] == 'ilike'
                and isinstance(cond[2], str)
            ):
                new_domain.append(cond)

            else:
                new_domain.append(cond)

        if import_number_exact is not None:
            import_number_exact = str(import_number_exact).zfill(5)
            new_domain.append(('import_number', '=', import_number_exact))

        if ean_search:
            terms = [t.strip() for t in ean_search.split() if t.strip()]
            if len(terms) > 1:
                new_domain.append(('ean', 'in', terms))
            else:
                new_domain.append(('ean', 'ilike', ean_search))

        return super(SBS, self)._search(new_domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)


    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super(SBS, self).fields_get(allfields, attributes=attributes)

        fields_to_hide = ['selling_price','converted_price'] #Fields to Hide
        for field in fields_to_hide:
            if self.env.user.has_group('oe_sbs.group_sbs_sales'):  
                res[field]['exportable'] = False
        return res


    def export_data(self, fields_to_export):
        user = self.env.user
        if user.has_group("oe_sbs.group_sbs_sales"):
            exportable_records = self.filtered(lambda r: not r.is_expired)
        else:
            exportable_records = self

        return super(SBS, exportable_records).export_data(fields_to_export)


    def unlink(self):
        
        if not self.env.su and ( self.env.user.has_group('oe_sbs.group_sbs_purchase') or self.env.user.has_group('oe_sbs.group_sbs_sales')) :
            raise AccessError("You dont have access to delete")
        
        return super().unlink()

    def open_import_from_document_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import from Document',
            'res_model': 'sbs.import.document.wizard',
            'view_mode': 'form',
            'target': 'new',
        }



    @api.model
    def action_cleanup_old_lists(self, new_import_number, new_import_date):
        """حذف خودکار لیست‌های قدیمی با تطابق بالا"""
        new_records = self.search([('import_number', '=', new_import_number)])
        
        if not new_records:
            return {
                'error': 'No records found for import number',
                'deleted_lists': 0,
                'total_records_deleted': 0,
                'logs_created': 0
            }
        
        supplier = new_records[0].supplier_name
        new_eans = set(new_records.mapped('ean'))
        
        summary = {
            'deleted_lists': 0,
            'total_records_deleted': 0,
            'supplier_name': supplier,
            'logs_created': 0
        }

        # --- Protect split siblings -------------------------------------
        protected_import_numbers = set()
        new_docs = new_records.mapped('document_id')
        if new_docs:
            family_roots = set()
            for d in new_docs:
                family_roots.add(d.sbs_origin_id.id if d.sbs_origin_id else d.id)
            if family_roots:
                Doc = self.env['documents.document']
                family_docs = Doc.search([
                    '|',
                    ('id', 'in', list(family_roots)),
                    ('sbs_origin_id', 'in', list(family_roots)),
                ])
                protected_import_numbers = {
                    n for n in family_docs.mapped('import_number') if n
                }

        old_import_numbers = self.search([
            ('supplier_name', '=', supplier),
            ('import_number', '!=', new_import_number),
            ('import_date', '<', new_import_date)
        ]).mapped('import_number')
        
        old_import_numbers = list(set(old_import_numbers))
        old_import_numbers = [n for n in old_import_numbers
                              if n not in protected_import_numbers]
        
        for old_import_number in old_import_numbers:
            old_records = self.search([
                ('import_number', '=', old_import_number)
            ])
            
            if not old_records:
                continue
            
            old_eans = set(old_records.mapped('ean'))
            
            common_eans = new_eans & old_eans
            base_size = len(old_eans)
            
            if base_size == 0:
                continue
            
            overlap_pct = (len(common_eans) / base_size) * 100
            
            threshold = self._get_overlap_threshold(base_size)
            
            if overlap_pct >= threshold:
                self.env['sbs.cleanup.log'].create({
                    'cleanup_date': fields.Datetime.now(),
                    'deleted_import_number': old_import_number,
                    'new_import_number': new_import_number,
                    'supplier_name': supplier,
                    'deleted_count': len(old_records),
                    'overlap_percentage': overlap_pct,
                    'threshold_used': threshold,
                    'deletion_reason': f'{overlap_pct:.1f}% overlap with new list (threshold: {threshold:.1f}%)'
                })
                
                old_doc = old_records[0]
                if old_doc:
                    old_doc.document_id.state='auto_deleted'
                    old_doc.document_id.old_import_number= old_doc.document_id.import_number
                    old_doc.document_id.import_number=False


                deleted_count = len(old_records)
                old_records.unlink()
                
                summary['deleted_lists'] += 1
                summary['total_records_deleted'] += deleted_count
                summary['logs_created'] += 1
        
        return summary

    @api.model
    def _get_overlap_threshold(self, base_size):
        """محاسبه آستانه بر اساس اندازه لیست"""
        ICP = self.env['ir.config_parameter'].sudo()
        
        if base_size >= 100:
            return float(ICP.get_param('oe_sbs.overlap_threshold_large', '50.0'))
        elif base_size >= 50:
            return float(ICP.get_param('oe_sbs.overlap_threshold_medium', '45.0'))
        elif base_size >= 20:
            return float(ICP.get_param('oe_sbs.overlap_threshold_small', '40.0'))
        else:
            return float(ICP.get_param('oe_sbs.overlap_threshold_tiny', '35.0'))
        


    def _sync_offer_lists(self):
        """
        Rebuild the sbs.offer.list summaries for the import numbers covered by
        this recordset. An empty recordset means "the whole table".

        This is only a dispatcher: the actual per-offer work lives in
        sbs.offer.list._sync_for_import_number, which is the single
        implementation shared by the import wizard, the supplier button, the
        server action and the nightly cron. Three separate copies of this logic
        used to exist and they disagreed with each other - one of them wrote
        create_date into import_date while another wrote import_date, and one
        deleted every summary before recreating it.
        """
        records = self if self else self.search([])
        OfferList = self.env['sbs.offer.list']
        import_numbers = sorted({n for n in records.mapped('import_number') if n})
        for import_number in import_numbers:
            OfferList._sync_for_import_number(import_number)
        _logger.info("[SBS] offer lists synced for %s import number(s).",
                     len(import_numbers))
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        return records

    #def write(self, vals):
    #    result = super().write(vals)
    #    if any(field in vals for field in ['import_number', 'supplier_id', 'end_date', 'moq', 'mov', 'incoterms', 't1_t2', 'payment_term', 'lead_time', 'document_id']):
    #    return result

    @api.model
    def _convert_selling_prices(self, src_currency, amount_oc, conv_date=None):
        """Convert an Original-Currency selling price into AED / EUR / GBP.
        Returns {field_name: value}. Shared by the import wizard and compute_selling_prices.
        Defensive: a missing/inactive currency or rate yields 0.0 instead of breaking import."""
        #company = self.env.company
        company = self.env['res.company'].browse(1)
        conv_date = conv_date or fields.Date.today()
        targets = {
            'selling_price_aed': self.env.ref('base.AED', raise_if_not_found=False),
            'selling_price_eur': self.env.ref('base.EUR', raise_if_not_found=False),
            'selling_price_gbp': self.env.ref('base.GBP', raise_if_not_found=False),
        }
        vals = {}
        for field_name, target in targets.items():
            value = 0.0
            if src_currency and target and amount_oc:
                try:
                    value = src_currency._convert(amount_oc, target, company, conv_date)
                except Exception:
                    value = 0.0
            vals[field_name] = value
        return vals
