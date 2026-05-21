{
    'name': 'Smart Business System (SBS)',
    'version': '19.0.1.0.0',
    'summary': 'System for comparing supplier prices and ranking products by best price',
    'description': """
        Smart Business System helps import supplier price lists, automatically converts currencies,
        ranks products by best price, and calculates selling prices with configurable margins.
        Key Features:
        - Excel import with validation
        - Automatic currency conversion using Odoo's rates
        - Product ranking by EAN and price
        - Configurable profit margins (8% default + customizable)
        - Complete import history tracking
    """,
    'author': 'Odooers IR',
    'website': 'https://odooers.ir',
    'category': 'Purchasing',
    'depends': [
        'base',
        'account',
        'oe_custom_general',
        'uom'

    ],
    'external_dependencies': {
        'python': ['openpyxl'],
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/ir_cron_data.xml',
        'data/res_config_settings_data.xml',
        'data/sbs_import_template_data.xml',

        'views/res_config_settings_views.xml',
        'wizard/import_wizard_views.xml',
        'views/sbs_views.xml',
        'views/res_partner_views.xml',
        'views/sbs_offer_list_views.xml',
        'views/documents_document_views.xml',
        'views/documents_tag_views.xml',
        'views/sbs_cleanup_log_views.xml',
        'views/sbs_import_template_views.xml',
        'views/menus.xml',


    ],
    'assets': {
      
        'web.assets_backend': [
              'oe_sbs/static/src/css/*',
              'oe_sbs/static/src/js/blank_dashboard.js',
              'oe_sbs/static/src/views/documents_list_controller_patch.js',
              'oe_sbs/static/src/views/documents_list_model_patch.js',
              'oe_sbs/static/src/views/document_service_patch.js',
              
    ],

    },


    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}