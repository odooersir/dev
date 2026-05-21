from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date
from odoo.exceptions import AccessError



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
    coo = fields.Char(string='CoO', help='Country of Origin')
    supplier_unit_price = fields.Float(string='Sup.U.P', help='Supplier Unit Price', digits=(16, 2), index=True, groups="oe_sbs.group_sbs_purchase,oe_sbs.group_sbs_admin")
    currency_id = fields.Many2one('res.currency', string='Currency')
    supplier_name = fields.Char(string='Supplier Name', index=True, groups="oe_sbs.group_sbs_purchase,oe_sbs.group_sbs_admin")

    # New fields
    excel_filename = fields.Char(string='Excel File Name', readonly=True, index=True, groups="oe_sbs.group_sbs_purchase,oe_sbs.group_sbs_admin")
    end_date = fields.Date(string='Offer Validity', index=True)

    converted_price = fields.Float( string='Converted Supplier Price (USD)', digits=(16, 2))
    selling_price = fields.Float(string='S.P($)', help='Selling Price (USD)', digits=(16, 2))
    selling_price_2 = fields.Float(string='S.P(OC)', help='Selling Price (Original Currency)', digits=(16, 2))

    min_sell = fields.Float(string='Min Sell(OC)', help='Min Sell(Original Currency)', digits=(16, 2))

    rank = fields.Integer(string='Rank', readonly=True, index=True)
    no_of_ranks = fields.Integer(string='No of Ranks')
    import_number = fields.Char(string='IN', help='Import Number', readonly=True, index=True)

    supplier_code = fields.Char(string='Supplier Code', help='Supplier Code')

    is_expired = fields.Boolean(index=True)

    lead_time = fields.Char(string='Lead Time')
    moq = fields.Char(string='MOQ')
    mov = fields.Char(string='MOV')
    availabale_qty = fields.Char(string='Available Units')
    incoterms = fields.Char(string='Incoterms')
    t1_t2 = fields.Char(string='T1/T2')
    payment_term = fields.Char(string='Payment Term')

    document_id = fields.Many2one('documents.document', string='Document', ondelete='restrict', index=True)

    supplier_id = fields.Many2one('res.partner', ondelete='restrict', string='Supplier', index=True)
    product_id = fields.Many2one('product.template', ondelete='restrict', string='Product', index=True)

    brand_id = fields.Many2one('product.brand', string='Brand', ondelete='restrict', related='product_id.brand_id')

    spreadsheet_url = fields.Char(string='Spreadsheet URL', compute='_compute_spreadsheet_url', store=False)

    converted_rate = fields.Float(string='Converted Rate', digits=(16, 2))

    uom_id = fields.Many2one('uom.uom', string='Unit of Measure',  help='Unit of measure derived from case_size', readonly=True, )


    unit_per_layer = fields.Integer(string='Unit/Layer')
    unit_per_pallet = fields.Integer(string='Unit/Pallet')
    hs_code = fields.Char(string='HS Code(Tariff)')

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
    def update_products_from_ean(self):
        """بروزرسانی product_id بر اساس فیلد ean فقط اگر خالی باشد"""
        records = self.search([])
        for rec in records:
            #if rec.ean and not rec.product_id:
            if rec.ean:
                product = self.env['product.template'].search([('barcode', '=', rec.ean)], limit=1)
                if product:
                    rec.product_id = product.id
        return True

    @api.model
    def update_suppliers_from_code(self):
        """بروزرسانی supplier_id بر اساس فیلد supplier_code فقط اگر خالی باشد"""
        records = self.search([])
        for rec in records:
            if rec.supplier_code and not rec.supplier_id:
                partner = self.env['res.partner'].search([('partner_code', '=', rec.supplier_code)], limit=1)
                if partner:
                    rec.supplier_id = partner.id
        return True

    
    
    
    @api.model
    def compute_selling_prices(self):

        # Cache configuration values
        ICP = self.env['ir.config_parameter'].sudo()
        margin = float(ICP.get_param('oe_sbs.default_profit_margin', '8')) / 100
        min_margin = float(ICP.get_param('oe_sbs.min_profit_margin', '7')) / 100

        # Cache base USD currency
        usd_currency = self.env.ref('base.USD')

        # Determine records
        records = self if self else self.search([])

        today = fields.Date.today()
        for record in records:
            if record.currency_id == usd_currency:
                converted_price = record.supplier_unit_price
                converted_rate=1
            else:
                #converted_price = usd_currency._convert(
                #    record.supplier_unit_price,
                #    record.currency_id,
                #    self.env.company,
                #    today
                #)
                cur=record.currency_id
                converted_price = cur._convert(record.supplier_unit_price, usd_currency, self.env.company, today)
                converted_rate= cur._get_conversion_rate(cur, usd_currency, self.env.company, date.today())

                #converted_amount = from_currency._convert(amount, to_currency, company, date)



            # Pre-calculate all values
            record_vals = {
                'converted_price': converted_price,
                'selling_price': converted_price * (1 + margin),
                'selling_price_2': record.supplier_unit_price * (1 + margin),
                'min_sell': record.supplier_unit_price * (1 + min_margin),
                'converted_rate':converted_rate
            }

            # Use write to avoid triggering field recomputes for each assignment
            record.write(record_vals)

        return True


  
    
    def action_rank_products(self):
        """Rank products with standard competition ranking (1223 style) within each EAN group"""

        # Using a single SQL query with Window Functions (CTE)
        # DENSE_RANK() exactly matches your 1-2-2-3 Python logic
        # COUNT() OVER() calculates the exact total for that EAN
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

        # Get all products ordered by EAN and price
        self.env.cr.execute("""
            SELECT id, ean, converted_price
            FROM sbs_data
            ORDER BY ean, converted_price ASC
        """)
        
        # Process ranking in batches
        batch_size = 1000
        current_ean = None
        current_price = None
        rank = 0
        records_to_update = []
        
        for row in self.env.cr.fetchall():
            record_id, ean, price = row
            
            if ean != current_ean:
                # New EAN group - reset all counters
                current_ean = ean
                current_price = price
                rank = 1
                records_to_update.append((record_id, rank))
            elif price == current_price:
                # Same EAN and price - same rank as previous
                records_to_update.append((record_id, rank))
            else:
                # Same EAN but new price - increment rank
                current_price = price
                rank += 1
                records_to_update.append((record_id, rank))
            
            # Process in batches to reduce memory usage
            if len(records_to_update) >= batch_size:
                self._update_ranks_in_bulk(records_to_update)
                records_to_update = []
        
        # Update any remaining records
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
        
        # Get EAN counts for all records in this batch
        record_ids = [id for id, _ in id_rank_pairs]
        self.env.cr.execute("""
            SELECT s1.id, COUNT(s2.id) as count
            FROM sbs_data s1
            JOIN sbs_data s2 ON s1.ean = s2.ean
            WHERE s1.id IN %s
            GROUP BY s1.id
        """, (tuple(record_ids),))
        
        ean_counts = {id: count for id, count in self.env.cr.fetchall()}
        
        # Build combined update query
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
        # کپی ایمن از دامین اولیه برای حفظ ساختار
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
               # res[field]['selectable'] = False  # مخفی کردن از فیلتر
               # res[field]['sortable'] = False    # مخفی کردن از گروه‌بندی
        return res


    def export_data(self, fields_to_export):
        # بررسی گروه کاربر جاری
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
        """
        حذف خودکار لیست‌های قدیمی با تطابق بالا
        
        Args:
            new_import_number: شماره ایمپورت جدید
            new_import_date: تاریخ ایمپورت جدید
            
        Returns:
            dict: خلاصه عملیات انجام شده
        """
        # جمع‌آوری رکوردهای جدید
        new_records = self.search([('import_number', '=', new_import_number)])
        
        if not new_records:
            return {
                'error': 'No records found for import number',
                'deleted_lists': 0,
                'total_records_deleted': 0,
                'logs_created': 0
            }
        
        # تامین‌کننده (فقط یکی)
        supplier = new_records[0].supplier_name
        new_eans = set(new_records.mapped('ean'))
        
        summary = {
            'deleted_lists': 0,
            'total_records_deleted': 0,
            'supplier_name': supplier,
            'logs_created': 0
        }
        
        # پیدا کردن لیست‌های قدیمی همین تامین‌کننده
        old_import_numbers = self.search([
            ('supplier_name', '=', supplier),
            ('import_number', '!=', new_import_number),
            ('import_date', '<', new_import_date)
        ]).mapped('import_number')
        
        # حذف تکراری
        old_import_numbers = list(set(old_import_numbers))
        
        # بررسی هر لیست قدیمی
        for old_import_number in old_import_numbers:
            old_records = self.search([
                ('import_number', '=', old_import_number)
            ])
            
            if not old_records:
                continue
            
            old_eans = set(old_records.mapped('ean'))
            
            # محاسبه تطابق
            common_eans = new_eans & old_eans
            #base_size = min(len(old_eans), len(new_eans))
            base_size = len(old_eans)
            
            if base_size == 0:
                continue
            
            overlap_pct = (len(common_eans) / base_size) * 100
            
            # تعیین آستانه
            threshold = self._get_overlap_threshold(base_size)
            
            # تصمیم حذف
            if overlap_pct >= threshold:
                # ثبت لاگ قبل از حذف
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
                
                # حذف رکوردها

                #for doc in old_records:
                old_doc = old_records[0]
                if old_doc:
                    old_doc.document_id.state='auto_deleted'
                    old_doc.document_id.old_import_number= old_doc.document_id.import_number
                    old_doc.document_id.import_number=False


                deleted_count = len(old_records)
                old_records.unlink()
                
                # به‌روزرسانی خلاصه
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
        


    '''
    def _sync_offer_lists(self):
        """Auto-sync sbs.offer.list when sbs.data changes"""
        suppliers = self.mapped('supplier_id').filtered(lambda p: p.supplier_rank > 0)
        
        for supplier in suppliers:
            sbs_records = self.env['sbs.data'].search([('supplier_id', '=', supplier.id)])
            import_numbers = list(set(sbs_records.mapped('import_number')))
            import_numbers = [x for x in import_numbers if x]
            
            existing_lists = self.env['sbs.offer.list'].search([('supplier_id', '=', supplier.id)])
            existing_imports = existing_lists.mapped('import_number')
            
            # Create missing
            for import_num in import_numbers:
                if import_num not in existing_imports:
                    items = sbs_records.filtered(lambda r: r.import_number == import_num)
                    first_item = items[0] if items else False
                    
                    if first_item:
                        self.env['sbs.offer.list'].create({
                            'import_number': import_num,
                            'supplier_id': supplier.id,
                            'import_date': first_item.create_date,
                            'end_date': first_item.end_date,
                            'document_id': first_item.document_id.id if first_item.document_id else False,
                            'moq': first_item.moq,
                            'mov': first_item.mov,
                            'incoterms': first_item.incoterms,
                            't1_t2': first_item.t1_t2,
                            'payment_term': first_item.payment_term,
                            'lead_time': first_item.lead_time,
                        })
            
            # Update existing
            for offer_list in existing_lists:
                items = sbs_records.filtered(lambda r: r.import_number == offer_list.import_number)
                if items:
                    first_item = items[0]
                    offer_list.write({
                        'end_date': first_item.end_date,
                        'document_id': first_item.document_id.id if first_item.document_id else False,
                        'moq': first_item.moq,
                        'mov': first_item.mov,
                        'incoterms': first_item.incoterms,
                        't1_t2': first_item.t1_t2,
                        'payment_term': first_item.payment_term,
                        'lead_time': first_item.lead_time,
                    })
            
            # Delete orphaned
            orphaned = existing_lists.filtered(lambda ol: ol.import_number not in import_numbers)
            orphaned.unlink()
    '''
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        return records

    #def write(self, vals):
    #    result = super().write(vals)
    #    if any(field in vals for field in ['import_number', 'supplier_id', 'end_date', 'moq', 'mov', 'incoterms', 't1_t2', 'payment_term', 'lead_time', 'document_id']):
    #    return result
