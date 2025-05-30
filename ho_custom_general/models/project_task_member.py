from odoo import fields, models,api


class ProjectTaskMember(models.Model):
    _name= "project.task.member"
    _description = "Project Task Member"

      # === Parent fields === #
    task_id = fields.Many2one(
        comodel_name='project.task',
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
    #share_type=fields.Char(string="Share Type") 

    share_type = fields.Many2one('share.type', string='Share Type', ondelete='restrict')




