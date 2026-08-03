# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SBSSynonymConflictWizard(models.TransientModel):
    _name = 'sbs.synonym.conflict.wizard'
    _description = 'SBS Synonym Mapping Conflict'

    template_id = fields.Many2one('sbs.import.template', string='Template',
                                  required=True, ondelete='cascade')
    message = fields.Text(string='Conflict', readonly=True)
    after_action = fields.Selection([
        ('learn', 'Learn only'),
        ('confirm', 'Confirm and learn'),
    ], string='After', default='learn')

    def action_remove_existing(self):
        """
        'Remove the previous one': drop the conflicting existing synonyms (so the
        header moves to the new field), re-sync this template's links from
        scratch, then learn the current pairs.
        """
        self.ensure_one()
        tmpl = self.template_id
        Syn = self.env['sbs.field.synonym']
        # delete every synonym whose header matches one of ours but on a
        # different field (the user chose the new mapping)
        for field_key, header_text in tmpl._sbs_mapping_pairs():
            norm = Syn.normalize_synonym(header_text)
            Syn.sudo().search([
                ('synonym', '=', norm),
                ('field_key', '!=', field_key),
            ]).unlink()
        # detach old links of THIS template (headers it no longer maps), then
        # relearn only the current pairs
        tmpl._sbs_unlink_from_synonyms()
        learned = tmpl._sbs_learn_mapped_headers()
        if self.after_action == 'confirm':
            tmpl.with_context(sbs_no_learn=True).write({'confirm': True})
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def action_skip_conflicting(self):
        """
        'Do not import the current one': learn only the non-conflicting headers,
        leaving existing mappings untouched.
        """
        self.ensure_one()
        tmpl = self.template_id
        Syn = self.env['sbs.field.synonym']
        learned = 0
        for field_key, header_text in tmpl._sbs_mapping_pairs():
            norm = Syn.normalize_synonym(header_text)
            clash = Syn.sudo().search([
                ('synonym', '=', norm),
                ('field_key', '!=', field_key),
            ], limit=1)
            if clash:
                continue   # skip the conflicting header
            Syn.learn_synonym(field_key, header_text, template_id=tmpl.id)
            learned += 1
        if self.after_action == 'confirm':
            tmpl.with_context(sbs_no_learn=True).write({'confirm': True})
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def action_cancel(self):
        """
        'Cancel': abort. If this was a confirm flow, leave the template inactive.
        """
        self.ensure_one()
        tmpl = self.template_id
        if self.after_action == 'confirm':
            tmpl.with_context(sbs_no_learn=True).write({'confirm': False, 'active': False})
        return {'type': 'ir.actions.act_window_close'}
