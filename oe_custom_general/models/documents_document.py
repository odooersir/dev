from odoo import models, api , fields

class Document(models.Model):
    _inherit = 'documents.document'


    tag_ids = fields.Many2many('documents.tag', 'document_tag_rel', string="Tags", tracking=True)

    DOCUMENT_STATE = [
        ('draft', "Draft"),
        ('approve', "Approve"),
        ('sent_to_sbs', "Sent To SBS")
        ('reject', "Reject"),
       
    ]

    state = fields.Selection(
        selection=DOCUMENT_STATE,
        string="Status",
        readonly=True, copy=False, index=True,
        tracking=3,
        default='draft')

    import_number = fields.Char(string='IN',help='Import Number',  default=False)
    


       #            <field name="state" widget="statusbar" statusbar_visible="draft,approve,reject"/>


    