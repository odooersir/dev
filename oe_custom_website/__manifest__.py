# -*- coding: utf-8 -*-
{
    'name': "Website Customization",
    'summary': "Customize models according to specific requirements",
    'description': """
        This module allows customization models in Odoo to meet specific needs and requirements.
    """,
    'author': "Odooers IR",
    'website': "https://www.odooers.ir",
    'category': 'Customizations',
    'version': '19.0.1.0.0',
    'depends': ['website_sale','oe_sbs'],
    'data': [
        
        'views/templates.xml',
        'views/product_details_templates.xml',
        'views/cliimax_homepage.xml',
        'views/cliimax_footer.xml',
        'views/cliimax_footer.xml',
        'views/brand_templates.xml'

    ],

    'assets': {
        'web.assets_frontend': [
            'oe_custom_website/static/src/js/marketplace_offers.js',
            'oe_custom_website/static/src/css/style.css',
            'oe_custom_website/static/src/css/cliimax_homepage.css',
            'oe_custom_website/static/src/css/brands.css'
        ],
}

  



}

