{
    "name": "POS Kiosk Cash Payment",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Add cash payment option to POS Kiosk",
    "description": "Enable cash payments in self-service kiosk mode",
    "author": "odooers.ir",
    "depends": ["pos_self_order"],
       "assets": {
        "pos_self_order.assets": [
            "pos_kiosk_cash_credit/static/src/app/self_order_service.js",
            "pos_kiosk_cash_credit/static/src/app/overrides/eating_location_page.js",
            "pos_kiosk_cash_credit/static/src/app/pages/payment_method_page/payment_method_page.js"
        ],
        "web.assets_qweb": [
            "pos_kiosk_cash_credit/static/src/app/pages/payment_method_page/payment_method_page.xml"
        ]
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3"
}