/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { EatingLocationPage } from "@pos_self_order/app/pages/eating_location_page/eating_location_page";

patch(EatingLocationPage.prototype, {
    setup() {
        super.setup();
        this.selfOrderRouter = useService("self_order_router");
        this.selfOrder = useService("self_order");
    },

    selectLocation(location) {
        super.selectLocation(location);
        if (this.selfOrder.config?.self_ordering_mode === "kiosk") {
            this.selfOrderRouter.navigate("payment_method");
        }
    }
});