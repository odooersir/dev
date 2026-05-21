# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProjectTask(models.Model):
    _inherit = 'project.task'

    
    
    
    state = fields.Selection(
        selection_add=[
            ('manager_approved', 'Manager Approved'),
        ],
        ondelete={
            'manager_approved': 'set default',  # یا 'cascade' یا 'set null' بسته به نیاز
        },
    )
   
    
    
    
    is_user_limited_access = fields.Boolean(
        string='User Has Limited Access',
        compute='_compute_is_user_limited_access'
    )

    is_readonly = fields.Boolean(
        string='User Dont write Task',
        compute='_compute_is_readonly'
    )
    is_invisible= fields.Boolean(
        string='User Dont See Other task',
        compute='_compute_is_invisible'
    )

    
    @api.depends('user_ids')
    def _compute_is_readonly(self):
        """
        محاسبه اینکه آیا کاربر فعلی در گروه محدود است و تسک به او تخصیص داده نشده
        """
        for task in self:
            # بررسی اینکه کاربر در گروه محدود هست یا نه
            user_in_limited_group = self.env.user.has_group('oe_custom_general.group_task_limited')
            
            # بررسی اینکه آیا تسک به کاربر تخصیص داده شده یا نه  
            task_assigned_to_user = self.env.user.id in task.user_ids.ids
            
            # اگر کاربر در گروه محدود باشد و تسک به او تخصیص داده نشده باشد
            task.is_readonly = user_in_limited_group and  task_assigned_to_user


    @api.depends('user_ids')
    def _compute_is_invisible(self):
        """
        محاسبه اینکه آیا کاربر فعلی در گروه محدود است و تسک به او تخصیص داده نشده
        """
        for task in self:
            # بررسی اینکه کاربر در گروه محدود هست یا نه
            user_in_limited_group = self.env.user.has_group('oe_custom_general.group_task_limited')
            
            # بررسی اینکه آیا تسک به کاربر تخصیص داده شده یا نه  
            task_assigned_to_user = self.env.user.id in task.user_ids.ids
            
            # اگر کاربر در گروه محدود باشد و تسک به او تخصیص داده نشده باشد
            task.is_invisible = user_in_limited_group and not task_assigned_to_user
    
    
    
    
    @api.depends('user_ids')
    def _compute_is_user_limited_access(self):
        """
        محاسبه اینکه آیا کاربر فعلی در گروه محدود است و تسک به او تخصیص داده نشده
        """
        for task in self:
            # بررسی اینکه کاربر در گروه محدود هست یا نه
            user_in_limited_group = self.env.user.has_group('oe_custom_general.group_task_limited')
            
          
            
            # اگر کاربر در گروه محدود باشد و تسک به او تخصیص داده نشده باشد
            task.is_user_limited_access = user_in_limited_group


    
    def write(self, vals):

      
        result =False

        for task in self:

        
            if task.is_user_limited_access:
                
                
                
                task_assigned_to_user = task.env.user.id in task.user_ids.ids
                
                if 'state' in vals and  task_assigned_to_user and task.state=='manager_approved':
                    return result
                
                if 'state' in vals and   vals['state'] in ['1_done'] and task_assigned_to_user:
                    result = super().write({'state':vals['state']})
                    return result
                
                if 'state' in vals and   vals['state'] in ['01_in_progress'] and task_assigned_to_user and task.state=='1_done':
                    result = super().write({'state':vals['state']})
                    return result


            else: 
                result = super().write(vals)

        return result


