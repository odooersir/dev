# -*- coding: utf-8 -*-
import base64
import datetime
import io

from odoo import models, fields, api, _


class SbsDataExport(models.Model):
    _inherit = 'sbs.data'

    # --- styling ---
    _XLSX_FONT = 'Calibri'
    _XLSX_HEADER_BG = '#800020'      # burgundy
    _XLSX_FILL_A = '#F2F2F2'         # banded light grey
    _XLSX_FILL_B = '#FFFFFF'         # white
    _XLSX_ROW_BORDER = '#D9D9D9'
    _XLSX_DATE_FMT = 'dd/mm/yyyy'
    _XLSX_DATETIME_FMT = 'dd/mm/yyyy hh:mm'
    _XLSX_LOGO_W = 150
    _XLSX_LOGO_H = 40

    # Offer-level fields: pulled OUT of the per-row table into the top block
    # (they are identical for a single import). Left column then right column.
    _OFFER_LEVEL_LEFT = ['import_number', 'lead_time', 'mov', 'end_date']
    # t1_t2 was split into three independent fields; the single Char no longer
    # exists on sbs.data, so leaving it here would raise on every export.
    _OFFER_LEVEL_RIGHT = ['incoterms', 'payment_term', 'currency_id',
                          't1', 't2', 'euro1']
    # Per-unit price used for the "Order Value" formula.
    # Order Value references the visible price COLUMN so it always matches what
    # the customer sees. Priority when several are shown: selling_price_2 wins;
    # otherwise whichever of these is present.
    _OFFER_PRICE_FIELDS = ['selling_price_2', 'min_sell']
    _OFFER_PRICE_FIELD = 'selling_price_2'   # preferred / fallback
    # Table columns rendered left-aligned + single line (everything else centered).
    _XLSX_LEFT_HEADERS = {'Product', 'Product Name', 'Note', 'Description'}
    _XLSX_WIDE_HEADERS = {'Product', 'Product Name', 'Note', 'Description'}

    def _offer_level_fields(self):
        return set(self._OFFER_LEVEL_LEFT + self._OFFER_LEVEL_RIGHT)

    def _sbs_exportable(self):
        """Records the current user is allowed to export. Admin / purchase /
        superuser get everything; a pure sales user cannot export expired
        offers. Single source of truth so export_data (rows) and the export
        controller (records) stay perfectly aligned."""
        user = self.env.user
        if (self.env.su
                or user.has_group('oe_sbs.group_sbs_admin')
                or user.has_group('oe_sbs.group_sbs_purchase')):
            return self
        if user.has_group('oe_sbs.group_sbs_sales'):
            return self.filtered(lambda r: not r.is_expired)
        return self

    def _currency_numfmt(self, currency):
        sym = (currency.symbol or '').replace('"', '') if currency else ''
        if currency and currency.position == 'after' and sym:
            return '#,##0.##"%s"' % sym
        if sym:
            return '"%s"#,##0.##' % sym
        return '#,##0.##'

    def _monetary_currency_fields(self, field_names):
        """{field_name: currency_field_name} for the Monetary fields among the
        given columns, so price cells can be rendered with their own currency
        (selling_price_2 -> currency_id, selling_price -> usd_currency_id, ...)."""
        res = {}
        for fn in field_names:
            f = self._fields.get(fn)
            if f is not None and getattr(f, 'type', None) == 'monetary':
                res[fn] = getattr(f, 'currency_field', None) or 'currency_id'
        return res

    def _company_address_oneline(self, company):
        parts = [company.street, company.street2, company.city,
                 company.state_id.name if company.state_id else '',
                 company.zip, company.country_id.name if company.country_id else '']
        return ' '.join(p for p in parts if p)

    def _xw_write_company_block(self, wb, ws, company):
        """Logo at A1 + company name/email/website/address down column A.
        Shared by the offer document and the flat export."""
        F = self._XLSX_FONT
        name_fmt = wb.add_format({'bold': True, 'font_size': 13, 'font_name': F})
        info_fmt = wb.add_format({'font_size': 11, 'font_name': F})
        addr_fmt = wb.add_format({'font_size': 11, 'font_name': F, 'text_wrap': True, 'valign': 'top'})
        ws.write_string(2, 0, company.name or '', name_fmt)          # A3
        ws.write_string(3, 0, company.email or '', info_fmt)         # A4
        ws.write_string(4, 0, company.website or '', info_fmt)       # A5
        ws.merge_range(5, 0, 6, 2, self._company_address_oneline(company), addr_fmt)  # A6:C7
        if company.logo:
            try:
                from PIL import Image as PILImage  # noqa: PLC0415
                raw = base64.b64decode(company.logo)
                pil = PILImage.open(io.BytesIO(raw))
                if pil.mode not in ('RGB', 'RGBA'):
                    pil = pil.convert('RGBA')
                nw, nh = pil.size
                png = io.BytesIO()
                pil.save(png, format='PNG')
                png.seek(0)
                ws.insert_image(0, 0, 'logo.png', {
                    'image_data': png,
                    'x_scale': self._XLSX_LOGO_W / float(nw) if nw else 1.0,
                    'y_scale': self._XLSX_LOGO_H / float(nh) if nh else 1.0,
                    'x_offset': 2, 'y_offset': 2})
            except Exception:
                pass

    # ==================================================================
    # SALES OFFER document  (company block + offer-level block + table)
    # ==================================================================
    def _build_offer_document_xlsx(self, field_names, columns_headers, rows, records):
        import xlsxwriter  # noqa: PLC0415
        from xlsxwriter.utility import xl_col_to_name

        company = self.env.company
        F = self._XLSX_FONT
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('Offer')

        # ---- shared formats ----
        label_fmt = wb.add_format({'bold': True, 'font_color': '#FFFFFF',
                                   'bg_color': self._XLSX_HEADER_BG, 'font_name': F, 'font_size': 11,
                                   'align': 'center', 'valign': 'vcenter',
                                   'border': 1, 'border_color': '#FFFFFF'})
        value_props = {'font_name': F, 'font_size': 11, 'align': 'center', 'valign': 'vcenter',
                       'bg_color': self._XLSX_FILL_A, 'border': 1, 'border_color': self._XLSX_ROW_BORDER}
        value_fmt = wb.add_format(value_props)
        vcache = {}

        def value_numfmt(nf):
            if nf not in vcache:
                vcache[nf] = wb.add_format(dict(value_props, num_format=nf))
            return vcache[nf]

        header_fmt = wb.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': self._XLSX_HEADER_BG,
                                    'font_name': F, 'font_size': 11, 'align': 'center', 'valign': 'vcenter',
                                    'bottom': 1, 'bottom_color': '#FFFFFF'})
        header_left_fmt = wb.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': self._XLSX_HEADER_BG,
                                         'font_name': F, 'font_size': 11, 'align': 'left', 'valign': 'vcenter',
                                         'bottom': 1, 'bottom_color': '#FFFFFF'})
        cell_props = {'font_name': F, 'font_size': 11, 'align': 'center', 'valign': 'vcenter',
                      'bottom': 1, 'bottom_color': self._XLSX_ROW_BORDER}
        ccache = {}

        def cell_fmt(is_a, left=False, num_format=None):
            key = (is_a, left, num_format)
            if key not in ccache:
                p = dict(cell_props, align=('left' if left else 'center'),
                         bg_color=(self._XLSX_FILL_A if is_a else self._XLSX_FILL_B))
                if num_format:
                    p['num_format'] = num_format
                ccache[key] = wb.add_format(p)
            return ccache[key]

        # ---- company block: logo A1, details below in column A ----
        self._xw_write_company_block(wb, ws, company)

        # ---- offer-level block (label/value pairs, rows 2-5) ----
        offer_set = self._offer_level_fields()
        idx_by_field = {}
        for c, fn in enumerate(field_names):
            idx_by_field.setdefault(fn, c)
        first = records[:1]
        base_currency = first.currency_id if first else False

        def offer_first_value(fname):
            for r in records:
                v = r[fname]
                if v:
                    return v
            return records[0][fname] if records else False

        def write_offer_pair(row0, label_col, val0, val1, fname):
            col = idx_by_field.get(fname)
            label = columns_headers[col] if col is not None else fname
            ws.write_string(row0, label_col, label, label_fmt)
            val = offer_first_value(fname)
            if fname == 'currency_id':
                ws.merge_range(row0, val0, row0, val1, (val.name if val else ''), value_fmt)
            elif isinstance(val, datetime.datetime):
                ws.merge_range(row0, val0, row0, val1, '', value_numfmt(self._XLSX_DATETIME_FMT))
                ws.write_datetime(row0, val0, val, value_numfmt(self._XLSX_DATETIME_FMT))
            elif isinstance(val, datetime.date):
                dt = datetime.datetime(val.year, val.month, val.day)
                ws.merge_range(row0, val0, row0, val1, '', value_numfmt(self._XLSX_DATE_FMT))
                ws.write_datetime(row0, val0, dt, value_numfmt(self._XLSX_DATE_FMT))
            elif isinstance(val, (int, float)) and not isinstance(val, bool):
                # numeric MOV -> currency; any other numeric -> plain number
                fmt = value_numfmt(self._currency_numfmt(base_currency)) if fname == 'mov' else value_fmt
                ws.merge_range(row0, val0, row0, val1, '', fmt)
                ws.write_number(row0, val0, float(val), fmt)
            else:
                # strings (incl. raw text like '£3k'), empty, or anything else
                ws.merge_range(row0, val0, row0, val1, (val if isinstance(val, str) else (val or '')), value_fmt)

        left = [fn for fn in self._OFFER_LEVEL_LEFT if fn in offer_set and fn in idx_by_field]
        right = [fn for fn in self._OFFER_LEVEL_RIGHT if fn in offer_set and fn in idx_by_field]
        for i, fn in enumerate(left):
            write_offer_pair(1 + i, 3, 4, 5, fn)      # label D, value E:F
        for i, fn in enumerate(right):
            write_offer_pair(1 + i, 6, 7, 8, fn)      # label G, value H:I

        # ---- table: remaining columns + Order (unit) + Order Value ----
        table_idx = [c for c, fn in enumerate(field_names) if fn not in offer_set]
        table_headers = [columns_headers[c] for c in table_idx]
        order_unit_col = len(table_headers)
        order_val_col = order_unit_col + 1
        table_headers += ['Order (unit)', 'Order Value']

        # Order Value uses the price the customer actually sees: selling_price_2
        # when both price columns are present, otherwise whichever of the two is
        # shown. The formula references that column so it always matches the
        # displayed price; if neither is shown, fall back to a baked literal.
        table_field_names = [field_names[c] for c in table_idx]
        present_prices = [f for f in self._OFFER_PRICE_FIELDS if f in table_field_names]
        order_price_field = present_prices[0] if present_prices else self._OFFER_PRICE_FIELD
        price_col = None
        for cc, src_c in enumerate(table_idx):
            if field_names[src_c] == order_price_field:
                price_col = cc
                break
        pf = self._fields.get(order_price_field)
        price_ccy_field = (getattr(pf, 'currency_field', None) or 'currency_id') if pf is not None else 'currency_id'

        HR = 8   # header row (Excel row 9)
        for c, label in enumerate(table_headers):
            is_left = label in self._XLSX_LEFT_HEADERS
            ws.write_string(HR, c, label, header_left_fmt if is_left else header_fmt)
            ws.set_column(c, c, 46 if label in self._XLSX_WIDE_HEADERS else 15)
        ws.set_row(HR, 22)

        unit_letter = xl_col_to_name(order_unit_col)
        price_letter = xl_col_to_name(price_col) if price_col is not None else None
        mono = self._monetary_currency_fields([field_names[c] for c in table_idx])
        for i, row in enumerate(rows):
            r0 = HR + 1 + i
            is_a = (i % 2 == 0)
            rec = records[i] if i < len(records) else (records[-1] if records else False)
            for cc, src_c in enumerate(table_idx):
                fname = field_names[src_c]
                label = table_headers[cc]
                is_left = label in self._XLSX_LEFT_HEADERS
                val = row[src_c]
                if rec and fname in mono and isinstance(val, (int, float)) and not isinstance(val, bool):
                    cur = rec[mono[fname]]
                    ws.write_number(r0, cc, float(val),
                                    cell_fmt(is_a, num_format=self._currency_numfmt(cur)))
                else:
                    self._xw_write_value(ws, r0, cc, val, is_a, is_left, cell_fmt)
            # Order (unit): blank input
            ws.write_blank(r0, order_unit_col, None, cell_fmt(is_a))
            # Order Value = Order(unit) x the displayed price (reference the
            # price column so it always equals what the customer sees).
            cur = rec[price_ccy_field] if rec else False
            if price_letter is not None:
                ws.write_formula(r0, order_val_col,
                                 '=%s%d*%s%d' % (price_letter, r0 + 1, unit_letter, r0 + 1),
                                 cell_fmt(is_a, num_format=self._currency_numfmt(cur)))
            else:
                price = (rec[order_price_field] or 0.0) if rec else 0.0
                if price:
                    ws.write_formula(r0, order_val_col, '=%s%d*%s' % (unit_letter, r0 + 1, price),
                                     cell_fmt(is_a, num_format=self._currency_numfmt(cur)))
                else:
                    ws.write_blank(r0, order_val_col, None, cell_fmt(is_a))

        ws.set_column(0, 0, 18.0)  # column A holds barcode + logo

        # ---- totals row: sum of Order (unit) and Order Value ----
        if rows:
            tr = HR + 1 + len(rows)
            first_x = HR + 2                    # first data row (Excel, 1-indexed)
            last_x = HR + 1 + len(rows)         # last data row (Excel, 1-indexed)
            common = {'bold': True, 'font_name': F, 'font_size': 11, 'valign': 'vcenter',
                      'top': 2, 'top_color': self._XLSX_HEADER_BG, 'bg_color': self._XLSX_FILL_A}
            label_total_fmt = wb.add_format(dict(common, align='right'))
            qty_total_fmt = wb.add_format(dict(common, align='center', num_format='#,##0'))
            val_total_fmt = wb.add_format(dict(common, align='center',
                                               num_format=self._currency_numfmt(base_currency)))
            if order_unit_col > 0:
                ws.merge_range(tr, 0, tr, order_unit_col - 1, 'Total', label_total_fmt)
            u_l = xl_col_to_name(order_unit_col)
            v_l = xl_col_to_name(order_val_col)
            ws.write_formula(tr, order_unit_col, '=SUM(%s%d:%s%d)' % (u_l, first_x, u_l, last_x), qty_total_fmt)
            ws.write_formula(tr, order_val_col, '=SUM(%s%d:%s%d)' % (v_l, first_x, v_l, last_x), val_total_fmt)

        wb.close()
        return output.getvalue()

    def _xw_write_value(self, ws, r0, c, val, is_a, is_left, cell_fmt):
        if val is None or val is False:
            ws.write_blank(r0, c, None, cell_fmt(is_a, left=is_left))
        elif isinstance(val, datetime.datetime):
            ws.write_datetime(r0, c, val, cell_fmt(is_a, left=is_left, num_format=self._XLSX_DATETIME_FMT))
        elif isinstance(val, datetime.date):
            dt = datetime.datetime(val.year, val.month, val.day)
            ws.write_datetime(r0, c, dt, cell_fmt(is_a, left=is_left, num_format=self._XLSX_DATE_FMT))
        elif isinstance(val, bytes):
            ws.write_string(r0, c, val.decode(errors='ignore'), cell_fmt(is_a, left=is_left))
        elif isinstance(val, str):
            ws.write_string(r0, c, val, cell_fmt(is_a, left=is_left))
        else:
            ws.write(r0, c, val, cell_fmt(is_a, left=is_left))

    # ==================================================================
    # FLAT branded export  (admin / purchase - no offer block, no order cols)
    # ==================================================================
    def _build_flat_xlsx(self, field_names, columns_headers, rows, records):
        import xlsxwriter  # noqa: PLC0415
        company = self.env.company
        F = self._XLSX_FONT
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('Data')

        header_fmt = wb.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': self._XLSX_HEADER_BG,
                                    'font_name': F, 'font_size': 11, 'align': 'center', 'valign': 'vcenter',
                                    'bottom': 1, 'bottom_color': '#FFFFFF'})
        cell_props = {'font_name': F, 'font_size': 11, 'align': 'center', 'valign': 'vcenter',
                      'bottom': 1, 'bottom_color': self._XLSX_ROW_BORDER}
        ccache = {}

        def cell_fmt(is_a, left=False, num_format=None):
            key = (is_a, left, num_format)
            if key not in ccache:
                p = dict(cell_props, align=('left' if left else 'center'),
                         bg_color=(self._XLSX_FILL_A if is_a else self._XLSX_FILL_B))
                if num_format:
                    p['num_format'] = num_format
                ccache[key] = wb.add_format(p)
            return ccache[key]

        self._xw_write_company_block(wb, ws, company)
        HR = 8
        for c, label in enumerate(columns_headers):
            ws.write_string(HR, c, label, header_fmt)
            ws.set_column(c, c, 46 if label in self._XLSX_WIDE_HEADERS else 15)
        ws.set_row(HR, 22)
        ws.set_column(0, 0, 18.0)  # column A holds logo/company

        mono = self._monetary_currency_fields(field_names)
        for i, row in enumerate(rows):
            r0 = HR + 1 + i
            is_a = (i % 2 == 0)
            rec = records[i] if i < len(records) else (records[-1] if records else False)
            for c, val in enumerate(row):
                fname = field_names[c] if c < len(field_names) else None
                is_left = columns_headers[c] in self._XLSX_LEFT_HEADERS if c < len(columns_headers) else False
                if rec and fname in mono and isinstance(val, (int, float)) and not isinstance(val, bool):
                    cur = rec[mono[fname]]
                    ws.write_number(r0, c, float(val), cell_fmt(is_a, num_format=self._currency_numfmt(cur)))
                else:
                    self._xw_write_value(ws, r0, c, val, is_a, is_left, cell_fmt)
        wb.close()
        return output.getvalue()

    # ==================================================================
    # Cron helper: build the sales offer for a fixed field set (future email)
    # ==================================================================
    def _build_offer_xlsx_for_records(self, records, field_names):
        Model = records.with_context(import_compat=False)
        rows = Model.export_data(field_names).get('datas', [])
        headers = []
        for fn in field_names:
            base = fn.split('/')[0].split(':')[0]
            headers.append(Model._fields[base].string if base in Model._fields else fn)
        base_names = [fn.split('/')[0].split(':')[0] for fn in field_names]
        return self._build_offer_document_xlsx(base_names, headers, rows, records)
