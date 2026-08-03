# -*- coding: utf-8 -*-
{
    'name': "General Customization",
    'summary': "Customize models according to specific requirements",
    'description': """
        This module allows customization models in Odoo to meet specific needs and requirements.
    """,
    'author': "Odooers IR",
    'website': "https://www.odooers.ir",
    'category': 'Customizations',
    'version': '19.0.1.0.0',
    'depends': ['web','product','account','project','sale_management','website_sale'],
    'data': [
        
        'data/ir_sequence_data.xml',
        'security/project_task_security.xml',
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/project_task_view.xml',
        'views/crm_lead_view.xml',
        'views/sale_order_view.xml',
        'wizard/so_to_po_views.xml',
        'views/stock_picking_view.xml',
        'views/res_partner_view.xml',
        'views/product_brand_view.xml',
        'views/crm_lead.xml',
        'views/res_country_views.xml',

    ],

    'assets': {
        'web.assets_backend': [
            'oe_custom_general/static/src/views/project_task_kanban_model_inherit.js',
            'oe_custom_general/static/src/views/unfold_all.js',
            'oe_custom_general/static/src/views/subtask_kanban_list.js',
            'oe_custom_general/static/src/views/project_task_state_selection_patch.js',
        ],
    },

    'post_init_hook': '_post_init_assign_partner_codes',


}

