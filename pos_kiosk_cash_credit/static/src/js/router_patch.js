/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { SelfOrderRouter } from "@pos_self_order/app/self_order_router_service";
import { PaymentMethodScreen } from "./payment_method_screen";

patch(SelfOrderRouter.prototype, {
    
    setup() {
        super.setup();
        // Register our custom route
        this.addRoute("payment_method", PaymentMethodScreen);
    }
});