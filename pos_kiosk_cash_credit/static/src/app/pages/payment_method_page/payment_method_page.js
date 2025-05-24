/** @odoo-module **/

import { registry } from "@web/core/registry";  // <-- THIS WAS MISSING
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class PaymentMethodPage extends Component {
    static template = "pos_kiosk_cash_credit.PaymentMethodPage";
    
    setup() {
        this.router = useService("router");
        this.selfOrder = useService("self_order");
    }

    selectPaymentMethod(method) {
        this.selfOrder.currentOrder.payment_method = method;
        this.router.navigate("product_list");
    }
}

// Register the component
registry.category("pos_self_order.screens").add("PaymentMethodPage", PaymentMethodPage);