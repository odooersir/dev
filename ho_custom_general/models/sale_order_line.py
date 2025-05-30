from odoo import fields, models, _



class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"





    def _timesheet_create_task_prepare_values(self, project):

        res = super()._timesheet_create_task_prepare_values(project)

        res.update({'agent_id': self.order_id.agent_id.id})

        print ("ressssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss")
        print (res)

        return res
    
    

