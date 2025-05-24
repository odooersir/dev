/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { SelfOrder } from "@pos_self_order/app/self_order_service";

patch(SelfOrder.prototype, {
    
    async _createOrder(orderData) {
        // Add kiosk and payment method flags
        orderData.is_kiosk = true;
        
        if (this.paymentMethod === 'cash') {
            orderData.is_cash = true;
        } else {
            orderData.is_cash = false;
        }
        
        // Call parent method
        const result = await super._createOrder(orderData);
        
        // Handle cash payment flow
        if (this.paymentMethod === 'cash') {
            this._handleCashPayment(result);
        }
        
        return result;
    },

    _handleCashPayment(order) {
        // Print cash slip
        this._printCashSlip(order);
        
        // Reset kiosk to main screen
        setTimeout(() => {
            this.router.navigate('eating_location');
        }, 3000);
    },

    _printCashSlip(order) {
        const slipContent = `
            <div class="cash-slip">
                <div class="slip-header">
                    <h2>Order Number</h2>
                    <h1>${order.pos_reference || order.name}</h1>
                </div>
                <div class="slip-message">
                    <p>Veuillez vous rendre en caisse accompagné du ticket pour payer votre commande.</p>
                </div>
            </div>
        `;
        
        // Trigger print
        window.print();
    },

    setPaymentMethod(method) {
        this.paymentMethod = method;
    }
});