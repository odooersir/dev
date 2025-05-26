{
    "name": "POS Kiosk Cash Payment",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Add cash payment option to POS Kiosk",
    "description": "Enable cash payments in self-service kiosk mode with proper order handling",
    "author": "Custom Development",
    "depends": ["pos_self_order", "point_of_sale"],
    "data": [
        "views/pos_order_views.xml",
    ],
    "assets": {
        "pos_self_order.assets": [
            "pos_kiosk_cash_credit/static/src/js/eating_location_page_patch.js",
            "pos_kiosk_cash_credit/static/src/js/confirmation_page_patch.js",
            "pos_kiosk_cash_credit/static/src/css/payment_method.css",
        ]
    },
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3"
}