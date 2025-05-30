from odoo import fields, models
class Project(models.Model):
    _inherit = "project.project"


    project_type =  fields.Selection([
            ('establishment', 'Announcement Of Establishment'),
            ('registration', 'Announcement Of Registration '),
            
        ],string='Project Type')
