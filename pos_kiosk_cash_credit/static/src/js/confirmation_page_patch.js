/** @odoo-module **/
// File: pos_kiosk_cash_credit/static/src/js/confirmation_page_patch.js

import { patch } from "@web/core/utils/patch";
import { ConfirmationPage } from "@pos_self_order/app/pages/confirmation_page/confirmation_page";

patch(ConfirmationPage.prototype, {
    
    async submitOrder() {
        // Get the payment method from the order or global variable
        const paymentMethod = this.selfOrder.currentOrder?.payment_method || window.selectedPaymentMethod;
        
        if (paymentMethod === 'cash') {
            // Handle cash order
            await this.handleCashOrder();
        } else {
            // Handle normal card payment
            await super.submitOrder();
        }
    },

    async handleCashOrder() {
        try {
            // Create the order with cash payment flag
            const orderData = this.selfOrder._prepareOrderData();
            orderData.is_cash = true;
            orderData.is_kiosk = true;
            
            // Submit the order to backend without payment
            const response = await this.rpc('/pos_self_order/process_order', {
                order: orderData,
                access_token: this.selfOrder.access_token,
            });

            if (response && response.id) {
                // Print cash slip
                this.printCashSlip(response);
                
                // Show success message
                this.showCashOrderSuccess(response);
                
                // Reset after delay
                setTimeout(() => {
                    this.router.navigate('default');
                }, 8000);
            }
        } catch (error) {
            console.error('Error processing cash order:', error);
            // Show error message
            this.showError('Unable to process order. Please try again.');
        }
    },

    printCashSlip(order) {
        const orderRef = order.pos_reference || order.name || 'ORD-' + Date.now();
        
        // Create print content
        const printContent = `
            <!DOCTYPE html>
            <html>
            <head>
                <title>Cash Payment Slip</title>
                <style>
                    @media print {
                        @page { 
                            margin: 0; 
                            size: 58mm auto;
                        }
                        body { margin: 0; }
                    }
                    body {
                        width: 58mm;
                        font-family: 'Courier New', monospace;
                        font-size: 12px;
                        line-height: 1.4;
                        margin: 0;
                        padding: 5mm;
                    }
                    .center { text-align: center; }
                    .bold { font-weight: bold; }
                    .large { font-size: 16px; }
                    .separator {
                        border-bottom: 1px dashed #000;
                        margin: 10px 0;
                        padding-bottom: 5px;
                    }
                    .order-number {
                        font-size: 20px;
                        font-weight: bold;
                        margin: 15px 0;
                        padding: 10px;
                        border: 2px solid #000;
                    }
                </style>
            </head>
            <body>
                <div class="center">
                    <div class="large bold">ORDER SLIP</div>
                    <div class="separator"></div>
                    
                    <div class="order-number center">
                        ${orderRef}
                    </div>
                    
                    <div class="separator"></div>
                    
                    <p><strong>Veuillez vous rendre en caisse accompagné du ticket pour payer votre commande.</strong></p>
                    
                    <br>
                    
                    <p><em>Please go to the cashier with this ticket to pay for your order.</em></p>
                    
                    <div class="separator"></div>
                    <div class="center small">
                        ${new Date().toLocaleString()}
                    </div>
                </div>
            </body>
            </html>
        `;

        // Create and print
        const printWindow = window.open('', '', 'width=300,height=400');
        if (printWindow) {
            printWindow.document.write(printContent);
            printWindow.document.close();
            
            // Auto print
            setTimeout(() => {
                printWindow.print();
                setTimeout(() => printWindow.close(), 1000);
            }, 500);
        }
    },

    showCashOrderSuccess(order) {
        // Show success overlay
        const successModal = document.createElement('div');
        successModal.className = 'cash-success-modal';
        successModal.innerHTML = `
            <div class="success-overlay">
                <div class="success-content">
                    <div class="success-icon">✅</div>
                    <h2>Order Received!</h2>
                    <h3>Commande reçue!</h3>
                    <div class="order-info">
                        <div class="order-number">${order.pos_reference || order.name}</div>
                        <p>Please go to the cashier to pay</p>
                        <p><em>Veuillez vous rendre en caisse pour payer</em></p>
                    </div>
                    <div class="countdown">Returning to main screen in <span id="countdown">8</span> seconds...</div>
                </div>
            </div>
        `;

        document.body.appendChild(successModal);

        // Countdown
        let count = 8;
        const countdownEl = successModal.querySelector('#countdown');
        const interval = setInterval(() => {
            count--;
            if (countdownEl) countdownEl.textContent = count;
            if (count <= 0) {
                clearInterval(interval);
                if (successModal.parentNode) {
                    successModal.remove();
                }
            }
        }, 1000);
    },

    showError(message) {
        // Simple error display
        alert(message);
    }
});