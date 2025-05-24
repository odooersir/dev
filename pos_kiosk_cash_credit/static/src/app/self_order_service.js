/** @odoo-module **/

import { registry } from "@web/core/registry";
import { PaymentMethodPage } from "./pages/payment_method_page/payment_method_page";

// 1. Get original services
const coreServices = registry.category("services");
const originalSelfOrder = coreServices.get("self_order") || {};

// 2. Create enhanced service
const enhancedSelfOrder = {
    ...originalSelfOrder,
    dependencies: [...(originalSelfOrder.dependencies || []), "self_order_router"],
    
    async start(env, services) {
        // Start original service
        const originalResult = originalSelfOrder.start 
            ? await originalSelfOrder.start(env, services)
            : {};
        
        // SAFE ROUTE REGISTRATION
        if (services.self_order_router) {
            services.self_order_router.addRoute("payment_method", PaymentMethodPage);
            console.log("✅ Payment route registered with self_order_router");
        } else {
            console.error("self_order_router service not available");
        }
        
        return originalResult;
    }
};

// 3. Register services
coreServices.add("self_order", enhancedSelfOrder, { force: true });