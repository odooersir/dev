/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { EatingLocationPage } from "@pos_self_order/app/pages/eating_location_page/eating_location_page";

patch(EatingLocationPage.prototype, {
    
    selectLocation(location) {
        // Store the selected location first
        this.selfOrder.currentOrder.eating_location = location;
        
        // Check if we're in kiosk mode
        if (this.selfOrder.config?.self_ordering_mode === "kiosk") {
            // Navigate to payment method selection instead of product list
            this.router.navigate("payment_method");
        } else {
            // For non-kiosk mode, use the original behavior
            super.selectLocation(location);
        }
    }
});