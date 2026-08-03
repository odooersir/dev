import json

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import re
import logging

import base64
import io
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from markupsafe import Markup, escape
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SbsMovTerm(models.Model):
    _name = 'sbs.mov.term'
    _description = 'MOV Terms'

    name = fields.Char(string='Name', required=True)

class SbsImportTemplate(models.Model):
    _name = 'sbs.import.template'
    _description = 'SBS Import Template'

    #name = fields.Char(string='Template Name', required=True)
    name = fields.Char(string='Template Name', required=True, copy=False,
                   readonly=True, default=lambda self: _('New'))


    supplier_id = fields.Many2one('res.partner', string='Supplier')
    # The document this template was created from (via 'Create Template' on a
    # document). Shown read-only so it's clear which file the mapping came from.
    document_id = fields.Many2one('documents.document', string='Source Document',
                                  readonly=True,
                                  help='The document this template was created from.')
    active = fields.Boolean(default=True)
    # User flips this ON only after reviewing the auto-mapping. Turning it on
    # asks whether to push the headers into the synonym dictionary; if the user
    # declines, the template is left inactive (active=False) and nothing is
    # learned. Editing a confirmed template later re-learns automatically.
    confirm = fields.Boolean(
        string='Confirmed', default=False,
        help='Turn on once the column mapping is final. You will be asked '
             'whether to save the headers to the auto-map dictionary.')

    sheet_name = fields.Char(string="Sheet Name", help="If left empty, the first sheet will be used.")


    header_row = fields.Integer(string='Header Row', default=1, help='Row number where headers are located')

   
    #signature_cell = fields.Char(string='Signature Cell', required=True, default='A1', help='e.g., A1')
    #signature_text = fields.Char(string='Signature Text', required=True)

    # NOTE: both AI assist AND the metadata scan mode are controlled globally in
    # Settings now (Enable AI Assist / AI for Metadata Extraction / Metadata Scan
    # Mode), not per template.

    # 4. فیلدهای Lead Time و Offer Validity
    WEEK_SELECTION = [
        ('1', '1 Week'),
        ('2', '2 Weeks'),
        ('3', '3 Weeks'),
        ('4', '4 Weeks'),
        ('5', '5 Weeks'),
        ('6', '6 Weeks'),
        ('7', '7 Weeks'),
        ('8', '8 Weeks'),
    ]


    # EAN
    ean_col = fields.Char(string='EAN Cell', required=True, help='e.g., A3')
    ean_header = fields.Char(string='EAN Header', help='Expected column name in Excel file, e.g., "EAN"')
    ean_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='EAN Type', default='text', help='Expected data type for validation')

    # Product Name
    product_name_col = fields.Char(string='Product Name Cell')
    product_name_header = fields.Char(string='Product Name Header', help='Expected column name in Excel file')
    product_name_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Product Name Type', default='text', help='Expected data type for validation')

    # Price
    price_col = fields.Char(string='Price Cell')
    price_header = fields.Char(string='Unit Price Header', help='Expected column name in Excel file, e.g., "Price"')
    price_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Price Type', default='float', help='Expected data type for validation')

    # Case Price: some suppliers quote the price PER CASE, not per unit. When
    # this column is mapped (and a unit price column isn't), the unit price is
    # computed at import time as case_price / Unit-per-Case. Not stored on
    # sbs.data - only the resulting unit price is.
    case_price_col = fields.Char(string='Case Price Cell')
    case_price_header = fields.Char(string='Case Price Header', help='Expected column name in Excel file, e.g., "Case Price"')

    @api.constrains('price_col', 'case_price_col')
    def _check_price_or_case_price(self):
        for rec in self:
            if not rec.price_col and not rec.case_price_col:
                raise ValidationError(_(
                    "Map at least one of 'Price' (unit price) or "
                    "'Case Price'. The unit price is taken from Price, or "
                    "computed from Case Price / Unit-per-Case."))

    # Supplier Code
    supplier_code_col = fields.Char(string='Supplier Code Cell')
    supplier_code_header = fields.Char(string='Supplier Code Header', help='Expected column name in Excel file')
    supplier_code_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Supplier Code Type', default='text', help='Expected data type for validation')

    # Brand
    brand_col = fields.Char(string='Brand Cell')
    brand_header = fields.Char(string='Brand Header', help='Expected column name in Excel file')
    brand_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Brand Type', default='text', help='Expected data type for validation')

    # Size
    size_col = fields.Char(string='Size Cell')
    size_header = fields.Char(string='Size Header', help='Expected column name in Excel file')
    size_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Size Type', default='text', help='Expected data type for validation')

    # Case Size
    case_size_col = fields.Char(string='Case Size Cell')
    case_size_header = fields.Char(string='Case Size Header', help='Expected column name in Excel file')
    case_size_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Case Size Type', default='integer', help='Expected data type for validation')

    # Layer
    layer_col = fields.Char(string='Layer Cell')
    layer_header = fields.Char(string='Layer Header', help='Expected column name in Excel file')
    layer_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Layer Type', default='integer', help='Expected data type for validation')

    # Pallet
    pallet_col = fields.Char(string='Pallet Cell')
    pallet_header = fields.Char(string='Pallet Header', help='Expected column name in Excel file')
    pallet_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Pallet Type', default='integer', help='Expected data type for validation')

    unit_per_layer_col = fields.Char(string='Unit/Layer Cell')
    unit_per_layer_header = fields.Char(string='Unit/Layer Header')

    unit_per_pallet_col = fields.Char(string='Unit/Pallet Cell')
    unit_per_pallet_header = fields.Char(string='Unit/Pallet Header')

    hs_code_col = fields.Char(string='HS Code Cell')
    hs_code_header = fields.Char(string='HS Code Header')
    # Cover Language
    cover_language_col = fields.Char(string='Language Cell')
    cover_language_header = fields.Char(string='Language Header')
    # MOQ
    moq_col = fields.Char(string='MOQ Cell')
    moq_header = fields.Char(string='MOQ Header', help='Expected column name in Excel file, e.g., "MOQ"')
    moq_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='MOQ Type', default='integer', help='Expected data type for validation')
    moq_fixed = fields.Char(string='Fixed MOQ')

    # MOV
    mov_col = fields.Char(string='MOV Cell')
    mov_header = fields.Char(string='MOV Header', help='Expected column name in Excel file, e.g., "MOV"')
    mov_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='MOV Type', default='float', help='Expected data type for validation')
    #mov_fixed = fields.Char(string='Fixed MOV')
    mov_fixed = fields.Many2one('sbs.mov.term', string="Fixed MOV")

    # Available Qty
    available_qty_col = fields.Char(string='Available Qty Cell')
    available_qty_header = fields.Char(string='Available Qty Header', help='Expected column name in Excel file')
    available_qty_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Available Qty Type', default='integer', help='Expected data type for validation')

    # Available stock expressed per CASE or per PALLET instead of per unit. When
    # mapped (and Available Qty in units isn't), the unit quantity is computed at
    # import time: Available Unit = Available Case x Unit/Case, or
    # Available Unit = Available Pallet x Unit/Pallet. Not stored on sbs.data -
    # only the resulting Available Unit is.
    available_case_col = fields.Char(string='Available Case Cell')
    available_case_header = fields.Char(string='Available Case Header', help='Expected column name in Excel file')
    available_pallet_col = fields.Char(string='Available Pallet Cell')
    available_pallet_header = fields.Char(string='Available Pallet Header', help='Expected column name in Excel file')

    # Currency
    currency_col = fields.Char(string='Currency Cell')
    currency_header = fields.Char(string='Currency Header', help='Expected column name in Excel file')
    currency_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Currency Type', default='text', help='Expected data type for validation')
    currency_fixed_id = fields.Many2one('res.currency', string='Fixed Currency')

    # Offer Validity
    offer_validity_col = fields.Char(string='Offer Validity Cell')
    offer_validity_header = fields.Char(string='Offer Validity Header', help='Expected column name in Excel file')
    offer_validity_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Offer Validity Type', default='date', help='Expected data type for validation')
    #offer_validity_fixed = fields.Date(string='Fixed Offer Validity')
    offer_validity_fixed = fields.Selection(WEEK_SELECTION, string="Fixed Validity")

    # Product Expiry Date column (the expiry printed on the product itself),
    # mapped like any other column so users can point it at the right cell.
    product_expiry_col = fields.Char(string='Product Expiry Cell')
    product_expiry_header = fields.Char(string='Product Expiry Header', help='Expected column name in Excel file')
    product_expiry_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Product Expiry Type', default='date', help='Expected data type for validation')

    # COO
    coo_col = fields.Char(string='COO Cell')
    coo_header = fields.Char(string='COO Header', help='Expected column name in Excel file')
    coo_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='COO Type', default='text', help='Expected data type for validation')
    #coo_fixed = fields.Char(string='Fixed COO')
    coo_fixed = fields.Many2one('res.country', string="Fixed COO")

    

    
    # Lead Time
    lead_time_col = fields.Char(string='Lead Time Cell')
    lead_time_header = fields.Char(string='Lead Time Header', help='Expected column name in Excel file')
    lead_time_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Lead Time Type', default='text', help='Expected data type for validation')
    #lead_time_fixed = fields.Char(string='Fixed Lead Time')
    lead_time_fixed = fields.Selection(WEEK_SELECTION, string="Fixed Lead Time")

    # Payment Terms
    payment_terms_col = fields.Char(string='Payment Terms Cell')
    payment_terms_header = fields.Char(string='Payment Terms Header', help='Expected column name in Excel file')
    payment_terms_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Payment Terms Type', default='text', help='Expected data type for validation')
    payment_terms_fixed = fields.Char(string='Fixed Payment Terms')

    # متد برای دکمه پر کردن خودکار شرایط پرداخت
    def action_set_default_payment_term(self):
        for rec in self:
            rec.payment_terms_fixed = "30% Deposite, Balance before shipping"


    # Incoterms
    incoterms_col = fields.Char(string='Incoterms Cell')
    incoterms_header = fields.Char(string='Incoterms Header', help='Expected column name in Excel file')
    incoterms_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Incoterms Type', default='text', help='Expected data type for validation')
    #incoterms_fixed = fields.Char(string='Fixed Incoterms')

    incoterm_id = fields.Many2one('account.incoterms', string="Fixed Incoterm")
    incoterm_country_id = fields.Many2one('res.country', string="Incoterm Country")
    incoterm_city = fields.Char(string="Incoterm City")

    # T1/T2
    batch_code_col = fields.Char(string='Batch Code Cell')
    batch_code_header = fields.Char(string='Batch Code Header', help='Expected column name in Excel file')
    batch_code_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='T1/T2 Type', default='text', help='Expected data type for validation')
    # Customs status is stated once per OFFER, never per product row - in
    # every supplier file seen so far it is a sentence beside or under the
    # table. So these are fixed-value fallbacks only, with no column mapping.
    t1_fixed = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Fixed T1')
    t2_fixed = fields.Selection([('yes', 'Yes'), ('no', 'No'),
                                 ('available', 'Available')], string='Fixed T2 (EU Clean)')
    euro1_fixed = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Fixed EUR.1')

    # Note
    note_col = fields.Char(string='Note Cell')
    note_header = fields.Char(string='Note Header', help='Expected column name in Excel file')
    note_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Note Type', default='text', help='Expected data type for validation')
    note_fixed = fields.Char(string='Fixed Note')
    

    # NOTE: size_col / size_header are declared once, above, next to the other
    # column mappings. A second declaration used to sit here and silently
    # overrode the first, dropping its help text, its size_type companion and
    # its place in the mapping table.
    
    preview_file = fields.Binary(string="Preview File")




    def _sbs_next_template_name(self, supplier):
        """Serial template name = supplier's partner_code + zero-padded counter,
        numbered per supplier (each supplier starts at 001)."""
        code = (supplier.partner_code or '').strip() if supplier else ''
        if not code:
            code = ((supplier.name or 'SUP').strip() if supplier else 'SUP')
        code = code.replace(' ', '')[:20] or 'SUP'

        seq_code = 'sbs.import.template.%s' % (supplier.id if supplier else 0)
        Seq = self.env['ir.sequence'].sudo()
        seq = Seq.search([('code', '=', seq_code)], limit=1)
        if not seq:
            seq = Seq.create({
                'name': 'SBS Template - %s' % (supplier.display_name if supplier else 'No Supplier'),
                'code': seq_code,
                'prefix': code,
                'padding': 3,
                'number_increment': 1,
                'number_next': 1,
            })
        elif seq.prefix != code:
            seq.prefix = code  # keep prefix in sync if partner_code changed
        return seq.next_by_code(seq_code) or _('New')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            supplier = self.env['res.partner'].browse(vals['supplier_id']) \
                if vals.get('supplier_id') else self.env['res.partner']
            vals['name'] = self._sbs_next_template_name(supplier)
        templates = super().create(vals_list)
        # NOTE: synonym learning is NOT done automatically here. It only happens
        # when the user confirms the template (confirm=True) or edits an already
        # confirmed one. Machine-created templates never silently learn.
        return templates

    def write(self, vals):
        # Detect a confirm ON->OFF transition (the toggle = unconfirm).
        # Turning ON via the toggle is blocked by _onchange_confirm_block_manual_on,
        # so confirming only ever happens through action_confirm (sbs_no_learn).
        turning_off = []
        if 'confirm' in vals and not vals.get('confirm'):
            turning_off = self.filtered(lambda t: t.confirm)

        res = super().write(vals)

        if self.env.context.get('sbs_no_learn'):
            return res

        Syn = self.env['sbs.field.synonym']

        # --- Toggle turned OFF (unconfirm): detach from dictionary + prune ---
        for tmpl in turning_off:
            tmpl._sbs_unlink_from_synonyms()

        # --- Mapping edited on an already-confirmed template (plain Save) ---
        mapping_field_names = set()
        for col_f, head_f, _syns in self._SBS_AUTOMAP:
            mapping_field_names.add(col_f)
            mapping_field_names.add(head_f)
        mapping_changed = bool(mapping_field_names & set(vals.keys()))
        if mapping_changed and 'confirm' not in vals:
            for tmpl in self:
                if not tmpl.confirm:
                    continue
                # last-wins: remove any synonym carrying one of our headers but
                # on a different field, so the header moves to the new field.
                for field_key, header_text in tmpl._sbs_mapping_pairs():
                    norm = Syn.normalize_synonym(header_text)
                    Syn.sudo().search([
                        ('synonym', '=', norm),
                        ('field_key', '!=', field_key),
                    ]).unlink()
                # detach old links of this template, then relearn current pairs
                tmpl._sbs_unlink_from_synonyms()
                tmpl._sbs_learn_mapped_headers()
        return res

    def action_confirm(self):
        """
        Button on the template form. Confirms the mapping and pushes headers to
        the dictionary. If a header conflicts with a different field, open the
        conflict wizard; otherwise learn immediately and set confirm=True.
        An act_window (wizard) can only be returned from an action like this -
        never from write() - which is why confirming is a button, not a toggle.
        """
        self.ensure_one()
        pairs = self._sbs_mapping_pairs()
        if not pairs:
            raise UserError(_("Map at least one column (cell + header) first."))
        conflicts = self.env['sbs.field.synonym'].detect_conflicts(pairs, template_id=self.id)
        if conflicts:
            return self._sbs_open_conflict_wizard(conflicts, after='confirm')
        # No conflict: re-sync this template's links from scratch so headers it
        # no longer maps (e.g. a column moved from case_size to ean) are dropped,
        # then learn the current pairs. Finally reload so the button updates.
        self._sbs_unlink_from_synonyms()
        self.with_context(sbs_no_learn=True).write({'confirm': True})
        self._sbs_learn_mapped_headers()
        return self._sbs_reload()

    def action_reject(self):
        """
        Reject (unconfirm) the template: turn confirm off AND detach it from the
        dictionary - remove it from every synonym's mapping_ids and prune any
        synonym left orphaned. Reloads the form so the buttons update at once.
        """
        self.ensure_one()
        self._sbs_unlink_from_synonyms()
        self.with_context(sbs_no_learn=True).write({'confirm': False})
        return self._sbs_reload()

    def action_export_mapping_json(self):
        """
        Download the selected mappings as JSON.

        The point is to capture what the mapping ACTUALLY is in production,
        rather than reconstructing it by guesswork when a supplier file has to
        be reproduced or investigated. The same file parses completely
        differently under two mappings, so the mapping is half the evidence
        whenever an import goes wrong - and it is the half that never travels
        with the .xlsx.

        Only fields that carry a value are written out, so the result stays
        readable instead of being a wall of nulls.
        """
        if not self:
            raise UserError(_("Select at least one mapping to export."))

        # 'name'/'supplier_id'/'active'/'confirm' are written explicitly above,
        # so they are skipped here to avoid listing each one twice.
        SKIP = {'id', 'display_name', 'create_uid', 'create_date',
                'write_uid', 'write_date', '__last_update',
                'name', 'supplier_id', 'active', 'confirm'}
        payload = {}
        for template in self:
            data = {
                'name': template.name,
                'supplier': template.supplier_id.display_name or '',
                'active': template.active,
                'confirmed': bool(template.confirm),
            }
            columns, headers, fixed, other = {}, {}, {}, {}
            for fname, field in sorted(template._fields.items()):
                if fname in SKIP or field.type in ('one2many', 'many2many'):
                    continue
                value = template[fname]
                # Careful: `False in (0, 0.0)` is True in Python, so a plain
                # falsy test let every unset Boolean and empty Char through as
                # `false` and buried the real mapping in noise. Only genuine
                # numbers are allowed to be zero.
                if value is False or value is None or value == '':
                    if not (field.type in ('integer', 'float')
                            and isinstance(value, (int, float))
                            and not isinstance(value, bool)):
                        continue
                if field.type == 'many2one':
                    value = value.display_name
                elif field.type not in ('char', 'text', 'boolean', 'integer',
                                        'float', 'selection'):
                    value = str(value)

                if fname.endswith('_col'):
                    columns[fname[:-4]] = value
                elif fname.endswith('_header'):
                    headers[fname[:-7]] = value
                elif fname.endswith('_fixed'):
                    fixed[fname[:-6]] = value
                elif fname not in data:
                    other[fname] = value

            data['columns'] = columns
            data['headers'] = headers
            data['fixed_values'] = fixed
            data['settings'] = other
            payload[template.display_name] = data

        content = json.dumps(payload, indent=2, ensure_ascii=False,
                             default=str, sort_keys=True)
        filename = ('sbs_mapping_%s.json' % (self[0].name or 'export')
                    if len(self) == 1 else 'sbs_mappings.json')
        filename = re.sub(r'[^\w.\-]+', '_', filename)
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content.encode('utf-8')),
            'mimetype': 'application/json',
            'res_model': self._name,
            'res_id': self[0].id if len(self) == 1 else False,
        })
        _logger.info("[SBS] exported %s mapping(s) to %s", len(self), filename)
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    # backward-compatible alias
    def action_unconfirm(self):
        return self.action_reject()

    def _sbs_reload(self):
        """Reload the current form view (refreshes button/field state)."""
        return {
            'type': 'ir.actions.client',
            'tag': 'soft_reload',
        }

    def unlink(self):
        # Detach from synonyms and prune orphans before the templates vanish.
        self._sbs_unlink_from_synonyms()
        return super().unlink()

    def action_confirm_and_learn(self):
        """Wizard 'Yes': confirm the template and learn its headers."""
        self.ensure_one()
        self.with_context(sbs_no_learn=True).write({'confirm': True})
        learned = self._sbs_learn_mapped_headers()
        return self._sbs_notify(_('Template confirmed. %s header(s) saved.') % learned)

    def action_confirm_without_learn(self):
        """Wizard 'No': leave the template inactive and learn nothing."""
        self.ensure_one()
        self.with_context(sbs_no_learn=True).write({'confirm': False, 'active': False})
        return self._sbs_notify(
            _('Template left inactive; headers were not saved.'),
            title=_('Not Confirmed'))

    def _sbs_mapping_pairs(self):
        """Current [(field_key, header_text), ...] for this template (set ones)."""
        self.ensure_one()
        pairs = []
        for col_f, head_f, _syns in self._SBS_AUTOMAP:
            header_text = getattr(self, head_f, False)
            col_letter = getattr(self, col_f, False)
            if col_letter and header_text:
                pairs.append((col_f, header_text))
        return pairs

    def _sbs_learn_mapped_headers(self):
        """
        Feed every final (field, header) pair of this template to the synonym
        learner, linking each to THIS template (mapping_ids). Before learning a
        pair, detach this template from any synonym that carries the SAME header
        on a DIFFERENT field (last-wins for this supplier): so re-mapping 'X'
        from field Y to field Z actually moves it, instead of leaving a stale
        'X -> Y' the auto-mapper could still pick. Returns the count learned.
        """
        self.ensure_one()
        Syn = self.env['sbs.field.synonym']
        count = 0
        for col_f, header_text in self._sbs_mapping_pairs():
            norm = Syn.normalize_synonym(header_text)
            # detach this template from same-header / other-field synonyms
            stale = Syn.sudo().search([
                ('synonym', '=', norm),
                ('field_key', '!=', col_f),
                ('mapping_ids', 'in', self.ids),
            ])
            if stale:
                for s in stale:
                    s.mapping_ids = [(3, self.id)]
                Syn.prune_orphans(synonym_ids=stale.ids)
            try:
                Syn.learn_synonym(col_f, header_text, template_id=self.id)
                count += 1
            except Exception:
                _logger.exception("[SBS] learn_synonym failed for %s=%s",
                                  col_f, header_text)
        return count

    def _sbs_unlink_from_synonyms(self):
        """
        Remove this template from every synonym's mapping_ids, then prune any
        synonym left with no mapping (shared knowledge is preserved; only truly
        orphaned learned synonyms are deleted).
        """
        Syn = self.env['sbs.field.synonym']
        linked = Syn.sudo().search([('mapping_ids', 'in', self.ids)])
        if not linked:
            return
        touched_ids = linked.ids
        for syn in linked:
            syn.mapping_ids = [(3, tid) for tid in self.ids]   # unlink these templates
        Syn.prune_orphans(synonym_ids=touched_ids)

    def action_learn_headers(self):
        """
        Explicit synonym learning (button next to auto-map). If turning headers
        into the dictionary would put a header on a different field than before,
        warn the user first via a conflict wizard; otherwise learn immediately.
        """
        self.ensure_one()
        Syn = self.env['sbs.field.synonym']
        pairs = self._sbs_mapping_pairs()
        conflicts = Syn.detect_conflicts(pairs, template_id=self.id)
        if conflicts:
            return self._sbs_open_conflict_wizard(conflicts, after='learn')
        learned = self._sbs_learn_mapped_headers()
        return self._sbs_notify(_('%s header(s) saved to the dictionary.') % learned)

    def _sbs_notify(self, message, title=None):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title or _('Auto-Map Dictionary'),
                'message': message,
                'sticky': False,
                'type': 'success',
            },
        }

    def _sbs_open_conflict_wizard(self, conflicts, after='learn'):
        """Open the conflict-resolution wizard, passing the conflict list."""
        labels = dict(self.env['sbs.field.synonym']._fields['field_key'].selection)
        lines = []
        for c in conflicts:
            lines.append(_("Header '%(h)s' is already used for '%(old)s', "
                           "but you are mapping it to '%(new)s'.") % {
                'h': c['header'],
                'old': labels.get(c['existing_field'], c['existing_field']),
                'new': labels.get(c['new_field'], c['new_field']),
            })
        wizard = self.env['sbs.synonym.conflict.wizard'].create({
            'template_id': self.id,
            'after_action': after,
            'message': "\n".join(lines),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Mapping Conflict'),
            'res_model': 'sbs.synonym.conflict.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    # Shared synonym map: (col field, header field, [synonyms])
    _SBS_AUTOMAP = [
        ('ean_col', 'ean_header', ['barcode', 'ean', 'gtin', 'ean13', 'bar code']),
        ('hs_code_col', 'hs_code_header', ['hs code', 'hs', 'tariff', 'hscode', 'commodity code']),
        ('cover_language_col', 'cover_language_header', ['language', 'languages', 'cover language', 'pack language', 'lang', 'languages on pack']),
        ('product_name_col', 'product_name_header', ['description', 'product name', 'item name', 'article', 'desc', 'product', 'name']),
        ('case_price_col', 'case_price_header', ['case price', 'price/case', 'case cost', 'cost/case', 'price per case', 'carton price', 'price/carton', 'box price', 'ctn price']),
        ('price_col', 'price_header', ['price', 'unit price', 'cost', 'net price', 'ppu']),
        ('supplier_code_col', 'supplier_code_header', ['supplier code', 'vendor code', 'sku', 'item code', 'ref', 'reference', 'article code']),
        ('brand_col', 'brand_header', ['brand']),
        ('case_size_col', 'case_size_header', ['case pack', 'case size', 'carton', 'units per case', 'ctn', 'case', 'pcspercarton', 'pcs per carton', 'pieces per carton', 'units per carton', 'pcs/carton', 'unit/case', 'units/case', 'unit per case', 'u/case', 'pcs/case', 'qty/case']),
        ('size_col', 'size_header', ['size', 'volume', 'content', 'ml']),
        ('unit_per_layer_col', 'unit_per_layer_header', ['unit/layer', 'units per layer', 'unit per layer', 'u/layer', 'units/layer', 'pcs/layer', 'pcs per layer', 'pieces per layer', 'qty/layer']),
        ('unit_per_pallet_col', 'unit_per_pallet_header', ['unit/pallet', 'units per pallet', 'unit per pallet', 'u/pallet', 'units/pallet', 'pcs/pallet', 'pcs per pallet', 'pieces per pallet', 'qty/pallet', 'pcs/pll', 'pcs/plt', 'pcs per pll', 'u/pll', 'units/pll', 'unit/pll', 'pcs/pal', 'pcs per pal', 'u/pal', 'units/pal']),
        ('layer_col', 'layer_header', ['layer', 'ti', 'case/layer', 'cases/layer', 'case per layer', 'cases per layer', 'ctn/layer', 'carton/layer', 'cartons per layer']),
        ('pallet_col', 'pallet_header', ['pallet', 'hi', 'ctnperpallet', 'ctn per pallet', 'cartons per pallet', 'cases per pallet', 'cases/pallet', 'ctn/pallet', 'case/pallet', 'case per pallet', 'carton/pallet', 'case/pll', 'cases/pll', 'ctn/pll', 'case/plt', 'cases/plt', 'case/pal', 'cases/pal']),
        ('available_case_col', 'available_case_header', ['available case', 'available cases', 'stock case', 'stock cases', 'cases available', 'case stock', 'avail case', 'avail cases', 'qty case', 'case qty']),
        ('available_pallet_col', 'available_pallet_header', ['available pallet', 'available pallets', 'stock pallet', 'stock pallets', 'pallets available', 'pallet stock', 'avail pallet', 'avail pallets', 'qty pallet', 'pallet qty', 'available pll', 'stock pll']),
        ('available_qty_col', 'available_qty_header', ['stock', 'qty', 'quantity', 'available', 'availability']),
        ('moq_col', 'moq_header', ['moq', 'minimum order quantity', 'min order qty', 'min order']),
        ('mov_col', 'mov_header', ['mov', 'minimum order value', 'min order value']),
        ('payment_terms_col', 'payment_terms_header', ['payment terms', 'payment', 'terms']),
        ('incoterms_col', 'incoterms_header', ['incoterms', 'incoterm', 'delivery terms']),
        ('batch_code_col', 'batch_code_header', ['batch', 'batch code', 'batch no', 'lot', 'lot code']),
        ('coo_col', 'coo_header', ['country of origin', 'coo', 'origin', 'made in']),
        ('lead_time_col', 'lead_time_header', ['lead time', 'leadtime', 'delivery time']),
        ('product_expiry_col', 'product_expiry_header', ['product expiry', 'expiry date', 'expiration date', 'best before', 'exp date', 'shelf life', 'bbd', 'best before date']),
        ('note_col', 'note_header', ['note', 'notes', 'remarks', 'remark', 'comment']),
    ]

    # A real column header is short. Anything longer than this is treated as a
    # sentence/note (e.g. "Our Moq is €.3500.-. Leadtime: one week...") and is
    # never matched as a header, so stray words like 'stock' inside it don't map.
    _MAX_HEADER_LEN = 40

    @staticmethod
    def _norm_header(s):
        s = re.sub(r'\s+', ' ', str(s or '').strip().lower())
        s = re.sub(r'\s*/\s*', '/', s)        # "case/ layer" -> "case/layer"
        if len(s) > SbsImportTemplate._MAX_HEADER_LEN:
            return ''                          # too long to be a header
        return s

    @staticmethod
    def _syn_match(norm, syn):
        # Whole-word match avoids false positives (e.g. 't1' inside 'netherlands')
        if not norm:
            return False
        # tighten slash spacing on both sides so 'case/ layer' matches 'case/layer'
        norm = re.sub(r'\s*/\s*', '/', norm)
        syn = re.sub(r'\s*/\s*', '/', syn)
        if norm == syn:
            return True
        return re.search(r'(^|[^a-z0-9])' + re.escape(syn) + r'([^a-z0-9]|$)', norm) is not None

    def _auto_map_vals_from_xlsx(self, file_bytes, sheet_name=None, max_scan_rows=15):
        """Read an xlsx and return template field values (header_row + *_col /
        *_header) by matching header text to known synonyms. The header row is
        detected as the scanned row with the most synonym matches.

        Synonyms come from the sbs.field.synonym model (approved only), so the
        dictionary can grow over time. Falls back to the built-in _SBS_AUTOMAP
        list if the model is empty (e.g. before seed data is loaded)."""
        from openpyxl import load_workbook
        from openpyxl.utils import get_column_letter
        import io

        # Synonyms come from the DB dict (so it can grow), but the ORDER is taken
        # from _SBS_AUTOMAP. Order matters: more-specific fields (unit_per_layer)
        # must be tried before generic ones (layer) or 'Unit/Layer' would be
        # grabbed by the 'layer' synonym. The DB dict's own order is not
        # controlled, so we never iterate it directly for matching.
        # Scope to this template's supplier so its own synonyms win over generic
        # ones; falls back to all synonyms when the supplier isn't set yet.
        supplier_id = self.supplier_id.id if self.supplier_id else False
        syn_dict = self.env['sbs.field.synonym'].get_automap_dict(supplier_id=supplier_id)
        automap = []
        for col_f, head_f, builtin_syns in self._SBS_AUTOMAP:
            syns = syn_dict.get(col_f) or builtin_syns
            automap.append((col_f, head_f, syns))
        # include any DB-only fields not present in _SBS_AUTOMAP, appended last
        known = {c for c, _h, _s in self._SBS_AUTOMAP}
        for col, syns in (syn_dict or {}).items():
            if col not in known:
                automap.append((col, col.replace('_col', '_header'), syns))

        wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
        ws = wb[sheet_name] if (sheet_name and sheet_name in wb.sheetnames) else wb.active
        rows = [list(r) for r in ws.iter_rows(max_row=max_scan_rows, values_only=True)]

        # 1) Detect header row
        best_idx, best_score = 0, -1
        for idx, row in enumerate(rows):
            score = 0
            for cell in row:
                norm = self._norm_header(cell)
                if norm and any(any(self._syn_match(norm, s) for s in syns)
                                for _c, _h, syns in automap):
                    score += 1
            if score > best_score:
                best_score, best_idx = score, idx

        vals = {'header_row': best_idx + 1}

        # 2) Map columns of the detected header row
        used = set()
        for c_idx, cell in enumerate(rows[best_idx] if rows else []):
            norm = self._norm_header(cell)
            if not norm:
                continue
            for col_f, head_f, syns in automap:
                if col_f in used:
                    continue
                if any(self._syn_match(norm, s) for s in syns):
                    vals[col_f] = get_column_letter(c_idx + 1)
                    vals[head_f] = str(cell)
                    used.add(col_f)
                    break
        return vals
        
    
    def action_auto_map(self):
        """Re-read preview_file and (re)fill the column mapping from its headers."""
        self.ensure_one()
        if not self.preview_file:
            raise UserError(_("Please upload a file first."))
        data = base64.b64decode(self.preview_file)
        vals = self._auto_map_vals_from_xlsx(data, sheet_name=self.sheet_name or None)
        self.write(vals)
        return True
        
    
    
    '''
    # Import Date
    import_date_col = fields.Char(string='Import Date Cell', help='e.g., A3')
    import_date_header = fields.Char(string='Import Date Header', help='Expected column name in Excel file')
    import_date_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Import Date Type', default='date', help='Expected data type for validation')

    # End Date
    end_date_col = fields.Char(string='End Date / Validity Cell', help='e.g., G3')
    end_date_header = fields.Char(string='End Date Header', help='Expected column name in Excel file')
    end_date_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='End Date Type', default='date', help='Expected data type for validation')
    '''