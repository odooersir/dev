# -*- coding: utf-8 -*-
import json
import logging
from datetime import date

from odoo import _
from odoo.exceptions import UserError
from odoo.http import request
from odoo.addons.web.controllers.export import ExcelExport

_logger = logging.getLogger(__name__)


class SbsExcelExport(ExcelExport):
    """sbs.data XLSX export.

    - Sales offer export (action sets context {'sbs_offer_export': 1}):
      renders the branded OFFER document -- company block + offer-level block
      (IN/Lead Time/MOV/Offer Validity/Incoterms/Payment Term/Currency/T1-T2
      lifted out of the table into a top grid) + per-row table + Order columns.
      Requires a single Import Number.
    - Any other sbs.data export: branded flat table.
    - Other models: native exporter, unchanged.

    Both the flat path (from_data) and the grouped path (from_group_data) are
    handled; grouped exports are flattened.
    """

    def base(self, data):
        try:
            self._sbs_params = json.loads(data)
        except Exception:
            self._sbs_params = {}
        return super().base(data)

    def filename(self, base):
        # Meaningful default download name (without extension). The user can
        # still rename/relocate it in the browser's "Save As" dialog.
        if base == 'sbs.data':
            try:
                params = getattr(self, '_sbs_params', {}) or {}
                context = params.get('context') or {}
                stamp = date.today().strftime('%Y%m%d')
                if context.get('sbs_offer_export'):
                    Model = request.env['sbs.data'].with_context(**self._sbs_clean_context(params))
                    records = self._sbs_records(Model, params)._sbs_exportable()
                    ins = sorted({n for n in records.mapped('import_number') if n})
                    return 'Offer_%s_%s' % (ins[0], stamp) if ins else 'Offer_%s' % stamp
                return 'SBS_Data_%s' % stamp
            except Exception:
                pass
        return super().filename(base)

    # ------------------------------------------------------------------
    def _sbs_clean_context(self, params):
        ctx = params.get('context') or {}
        # Carry allowed_company_ids so self.env.company is the selected company.
        return {k: v for k, v in ctx.items() if isinstance(k, str) and k.isidentifier()}

    def _sbs_records(self, Model, params):
        ids = params.get('ids')
        domain = params.get('domain') or []
        return Model.browse(ids) if ids else Model.search(domain)

    def _sbs_check_single_import(self, records):
        imports = {n for n in records.mapped('import_number') if n}
        if len(imports) > 1:
            raise UserError(_(
                "Please export from a single Import Number (IN). Your selection "
                "spans %(n)d different offers: %(list)s"
            ) % {'n': len(imports), 'list': ', '.join(sorted(imports))})

    @staticmethod
    def _sbs_base_names(field_dicts_or_names):
        out = []
        for f in field_dicts_or_names:
            name = f['name'] if isinstance(f, dict) else f
            out.append(name.split('/')[0].split(':')[0])
        return out

    # ------------------------------------------------------------------
    def from_data(self, fields, columns_headers, rows):
        params = getattr(self, '_sbs_params', {}) or {}
        if params.get('model') != 'sbs.data':
            return super().from_data(fields, columns_headers, rows)

        context = params.get('context') or {}
        Model = request.env['sbs.data'].with_context(**self._sbs_clean_context(params))
        records = self._sbs_records(Model, params)._sbs_exportable()
        field_names = self._sbs_base_names(fields)

        if context.get('sbs_offer_export'):
            self._sbs_check_single_import(records)
            return Model._build_offer_document_xlsx(field_names, columns_headers, rows, records)

        return Model._build_flat_xlsx(field_names, columns_headers, rows, records)

    def from_group_data(self, fields, columns_headers, groups):
        params = getattr(self, '_sbs_params', {}) or {}
        if params.get('model') != 'sbs.data':
            return super().from_group_data(fields, columns_headers, groups)

        # Flatten grouped selection back into plain rows (natural order).
        context = params.get('context') or {}
        Model = request.env['sbs.data'].with_context(**self._sbs_clean_context(params))
        records = self._sbs_records(Model, params)._sbs_exportable()
        full_names = [f['name'] for f in fields]
        rows = records.export_data(full_names).get('datas', [])

        if context.get('sbs_offer_export'):
            self._sbs_check_single_import(records)
            field_names = self._sbs_base_names(fields)
            return Model._build_offer_document_xlsx(field_names, columns_headers, rows, records)

        field_names = self._sbs_base_names(fields)
        return Model._build_flat_xlsx(field_names, columns_headers, rows, records)
