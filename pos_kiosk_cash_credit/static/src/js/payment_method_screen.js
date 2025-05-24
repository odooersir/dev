/** @odoo-module **/

import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

export class PaymentMethodScreen extends Component {
    static template = "pos_kiosk_cash_credit.PaymentMethodScreen";
    
    setup() {
        this.selfOrder = useService("self_order");
        this.router = useService("self_order_router");
        this.selectedMethod = null;
    }

    selectPaymentMethod(method) {
        this.selectedMethod = method;
        this.selfOrder.setPaymentMethod(method);
        
        if (method === 'cash') {
            // For cash, go to product list to continue ordering
            this.router.navigate('product_list');
        } else {
            // For card, go to product list (payment happens after order completion)
            this.router.navigate('product_list');
        }
    }
}

// Register the screen component
registry.category("self_order_screens").add("payment_method", PaymentMethodScreen);
