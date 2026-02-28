from odoo import _, api, models, fields


class Tags(models.Model):
    _inherit = "documents.tag"

    
    DOCUMENT_STATE = [
        ('draft', "Draft"),
        ('approve', "Approve"),
        ('sent_to_sbs', "Sent To SBS"),
        ('deleted_from_sbs', "Deleted From SBS"),
        ('auto_deleted', "Auto Deleted From SBS"),
        ('reject', "Reject"),
       
    ]

    
    state = fields.Selection(
        selection=DOCUMENT_STATE,
        string="Status",
        readonly=False, copy=False, index=True,
        tracking=True,
        default='draft')
