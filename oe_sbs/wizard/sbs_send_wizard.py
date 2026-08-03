# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class SbsSendWizard(models.TransientModel):
    _name = 'sbs.send.wizard'
    _description = 'Send to SBS - choose the import mapping'

    document_id = fields.Many2one('documents.document', string='Document',
                                  required=True, readonly=True)
    supplier_name = fields.Char(string='Supplier', readonly=True)
    template_id = fields.Many2one('sbs.import.template', string='Mapping',
                                  required=True)
    # The picker only ever offers mappings that already matched the file, so the
    # domain is a fixed id list rather than a live search: re-deriving it here
    # would be a second set of matching rules that could disagree with the one
    # the import actually uses.
    allowed_template_ids = fields.Many2many('sbs.import.template',
                                            string='Matching Mappings',
                                            readonly=True)
    candidate_summary = fields.Text(string='Matches', readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        doc_id = vals.get('document_id') or self.env.context.get('default_document_id')
        if not doc_id:
            return vals
        document = self.env['documents.document'].browse(doc_id)
        candidates, reason = document._sbs_template_candidates()
        vals['allowed_template_ids'] = [(6, 0, [t.id for t, _s in candidates])]
        if candidates:
            vals.setdefault('template_id', candidates[0][0].id)
        supplier = document._sbs_supplier_from_folder()
        vals['supplier_name'] = supplier.display_name if supplier else ''
        # Show the score so the user can see WHY one mapping is proposed first;
        # a bare list of names gives them nothing to choose on.
        vals['candidate_summary'] = "\n".join(
            "%s  -  %s matching column%s" % (t.display_name, score,
                                             '' if score == 1 else 's')
            for t, score in candidates) or reason
        return vals

    def action_send(self):
        """Send the document using the chosen mapping."""
        self.ensure_one()
        result = self.document_id._sbs_send_one(
            forced_template_id=self.template_id.id)
        if result.get('status') == 'ok':
            message = _("Imported %(count)s rows. Reference: %(ref)s") % {
                'count': result.get('total_imported'),
                'ref': result.get('import_number'),
            }
            msg_type = 'success'
        else:
            message = result.get('result_error') or _("Import failed.")
            msg_type = 'danger'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Send to SBS"),
                'message': message,
                'type': msg_type,
                'sticky': msg_type != 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
