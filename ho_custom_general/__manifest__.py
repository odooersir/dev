# -*- coding: utf-8 -*-
{
    'name': "General Customization",
    'summary': "Customize models according to specific requirements",
    'description': """
        This module allows customization models in Odoo to meet specific needs and requirements.
    """,
    'author': "Hooshadoo",
    'website': "https://www.hooshadoo.com/",
    'category': 'Customizations',
    'version': '0.1',
    'depends': ['base','contacts','project','sale','sale_project'],
    'data': [
        'views/res_partner_view.xml',
        'views/res_company_view.xml',
        'security/ir.model.access.csv',
        'views/project_project_view.xml',
        'views/project_task_view.xml',
        'views/sale_view.xml'
    ],
}

