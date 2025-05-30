from odoo import fields, models,api


class ResPartnerMember(models.Model):
    _name= "res.partner.member"
    _description = "Res Partner Member"

      # === Parent fields === #
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        required=True,
        readonly=True,
     
    )
    company_member_id = fields.Many2one(comodel_name='res.partner',string='Company Member', ondelete='restrict', )

    #position = fields.Char(string='Position') 
    position_id=fields.Many2one('member.position', string='Member Position', ondelete='restrict')

    is_board_member = fields.Boolean(string='Is Board Member', default=False)
    is_inspector=fields.Boolean(string='Is Inspector', default=False)


    share_number=fields.Integer(string="Share Number")
    share_value=fields.Char(string="Share Value")
    share_type=fields.Char(string="Share Type") 

    share_type = fields.Many2one('share.type', string='Share Type', ondelete='restrict')



class ShareType(models.Model):
    _name = "share.type"
    _description = "Share Type"
    _order = "name"

    name = fields.Char('Name', translate=True)
    active = fields.Boolean('Active', default=True)
