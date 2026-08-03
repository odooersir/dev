{
    'name': 'Smart Business System (SBS)',
    'version': '19.0.1.2.0',
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
        # Optional readers, imported lazily and tolerated if missing:
        #   xlrd   -> legacy .xls
        #   pyxlsb -> binary .xlsb
        # Install them on the server to enable those formats:
        #   pip install xlrd pyxlsb
        # AI assist (optional, off by default): the 'anthropic' SDK talks to a
        # local Ollama server or a cloud endpoint. NOT listed as required so the
        # module loads fine without it; AI just stays disabled until installed:
        #   pip install anthropic
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/ir_cron_data.xml',
        'data/sbs_cron.xml',
        'data/sbs_mail_alias.xml',
        'data/res_config_settings_data.xml',
        'data/sbs_import_template_data.xml',
        'data/sbs_field_synonym_data.xml',

        'views/res_config_settings_views.xml',
        'wizard/import_wizard_views.xml',
        'wizard/sbs_send_wizard_views.xml',
        'views/sbs_views.xml',
        'views/res_partner_views.xml',
        'views/sbs_offer_list_views.xml',
        'views/documents_document_views.xml',
        'views/documents_tag_views.xml',
        'views/sbs_cleanup_log_views.xml',
        'views/sbs_import_template_views.xml',
        'views/menus.xml',
        'views/sbs_field_synonym_views.xml',
        'wizard/sbs_synonym_conflict_wizard_views.xml',


    ],
    'assets': {
      
        'web.assets_backend': [
            'oe_sbs/static/src/css/*',
            'oe_sbs/static/src/js/blank_dashboard.js',
            'oe_sbs/static/src/views/documents_list_controller_patch.js',
            'oe_sbs/static/src/views/documents_list_model_patch.js',
            'oe_sbs/static/src/views/document_service_patch.js',
            'oe_sbs/static/lib/sheetjs/xlsx.full.min.js',
           # 'oe_sbs/static/src/css/excel_preview.css',
            'oe_sbs/static/src/js/excel_grid.js',
            'oe_sbs/static/src/js/excel_preview.js',
            'oe_sbs/static/src/xml/excel_preview.xml',
            'oe_sbs/static/src/js/excel_viewer.js',
            'oe_sbs/static/src/xml/excel_viewer.xml',
            'oe_sbs/static/src/js/sbs_open_link.js',
            'oe_sbs/static/src/js/sbs_barcode_search.js',
            'oe_sbs/static/src/js/import_number_color.js',
    ],

    },


    'demo': [],
    'installable': True,
    'application': True,
    'post_init_hook': '_sbs_post_init_set_start_date',
    'auto_install': False,
    'license': 'LGPL-3',
}