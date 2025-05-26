/** @odoo-module **/
// File: pos_kiosk_cash_credit/static/src/js/confirmation_page_patch.js

import { patch } from "@web/core/utils/patch";
import { ConfirmationPage } from "@pos_self_order/app/pages/confirmation_page/confirmation_page";

patch(ConfirmationPage.prototype, {
    
    async submitOrder() {
        // Get the payment method from the order
        const paymentMethod = this.selfOrder.currentOrder?.payment_method || window.selectedPaymentMethod;
        
        console.log('Payment method selected:', paymentMethod);
        
        if (paymentMethod === 'cash') {
            await this.handleCashOrder();
        } else {
            // For card payments, use the standard flow
            await super.submitOrder();
        }
    },

    async handleCashOrder() {
        try {
            console.log('Processing cash order...');
            
            // Prepare order data
            const orderData = this.prepareOrderData();
            
            // Submit cash order to backend
            const response = await this.rpc('/pos_self_order/process_cash_order', {
                order_data: orderData,
                access_token: this.selfOrder.access_token,
            });

            if (response && response.success) {
                console.log('Cash order created:', response);
                
                // Print cash slip
                await this.printCashSlip(response);
                
                // Show success message
                this.showCashOrderSuccess(response);
                
                // Reset to home after delay
                setTimeout(() => {
                    this.resetToHome();
                }, 8000);
            } else {
                throw new Error(response?.error || 'Failed to create cash order');
            }
        } catch (error) {
            console.error('Error processing cash order:', error);
            this.showError('Unable to process order. Please try again.');
        }
    },

    prepareOrderData() {
        // Prepare order data similar to the standard flow
        const currentOrder = this.selfOrder.currentOrder;
        const orderLines = [];
        
        // Convert order lines
        if (currentOrder.lines) {
            for (const line of currentOrder.lines) {
                orderLines.push({
                    product_id: line.product_id,
                    qty: line.qty || 1,
                    price_unit: line.price_unit || 0,
                    price_subtotal: line.price_subtotal || 0,
                    price_subtotal_incl: line.price_subtotal_incl || 0,
                });
            }
        }
        
        return {
            partner_id: currentOrder.partner_id || null,
            eating_location: currentOrder.eating_location || 'takeaway',
            lines: orderLines,
            amount_total: currentOrder.amount_total || 0,
            amount_tax: currentOrder.amount_tax || 0,
            is_cash: true,
            is_kiosk: true,
        };
    },

    async printCashSlip(orderResponse) {
        try {
            console.log('Printing cash slip for order:', orderResponse.order_number);
            
            // Get slip content from backend
            const slipResponse = await this.rpc('/pos_self_order/print_cash_slip', {
                order_id: orderResponse.id
            });
            
            if (slipResponse && slipResponse.success) {
                // Create print window and print
                this.performPrint(slipResponse.slip_content);
            } else {
                // Fallback to basic slip
                this.printBasicSlip(orderResponse.order_number);
            }
        } catch (error) {
            console.error('Error printing cash slip:', error);
            // Fallback to basic slip
            this.printBasicSlip(orderResponse.order_number);
        }
    },

    printBasicSlip(orderNumber) {
        const printContent = `
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Cash Payment Slip</title>
                <style>
                    @media print {
                        @page { 
                            margin: 0; 
                            size: 58mm auto;
                        }
                        body { margin: 0; padding: 0; }
                    }
                    body {
                        width: 58mm;
                        font-family: 'Courier New', monospace;
                        font-size: 12px;
                        line-height: 1.3;
                        margin: 0;
                        padding: 2mm;
                        text-align: center;
                    }
                    .header {
                        font-size: 14px;
                        font-weight: bold;
                        margin-bottom: 8px;
                    }
                    .order-number {
                        font-size: 18px;
                        font-weight: bold;
                        margin: 15px 0;
                        padding: 8px;
                        border: 2px solid #000;
                    }
                    .message {
                        font-size: 11px;
                        margin: 12px 0;
                        line-height: 1.4;
                    }
                    .separator {
                        border-bottom: 1px dashed #000;
                        margin: 8px 0;
                    }
                </style>
            </head>
            <body>
                <div class="header">TICKET DE COMMANDE</div>
                <div class="separator"></div>
                
                <div class="order-number">${orderNumber}</div>
                
                <div class="separator"></div>
                
                <div class="message">
                    <strong>Veuillez vous rendre en caisse accompagné du ticket pour payer votre commande.</strong>
                </div>
                
                <div class="message">
                    <em>Please go to the cashier with this ticket to pay for your order.</em>
                </div>
                
                <div class="separator"></div>
                <div class="timestamp">
                    ${new Date().toLocaleString('fr-FR')}
                </div>
            </body>
            </html>
        `;
        
        this.performPrint(printContent);
    },

    performPrint(htmlContent) {
        // Create print window
        const printWindow = window.open('', '', 'width=300,height=500');
        
        if (printWindow) {
            printWindow.document.open();
            printWindow.document.write(htmlContent);
            printWindow.document.close();
            
            // Wait for content to load, then print
            printWindow.onload = function() {
                setTimeout(() => {
                    printWindow.print();
                    setTimeout(() => {
                        printWindow.close();
                    }, 1000);
                }, 500);
            };
        } else {
            console.error('Could not open print window');
        }
    },

    showCashOrderSuccess(orderResponse) {
        // Remove any existing success modal
        const existingModal = document.querySelector('.cash-success-modal');
        if (existingModal) {
            existingModal.remove();
        }

        // Create success modal
        const successModal = document.createElement('div');
        successModal.className = 'cash-success-modal';
        successModal.innerHTML = `
            <div class="success-overlay">
                <div class="success-content">
                    <div class="success-icon">✅</div>
                    <h2>Order Received!</h2>
                    <h3>Commande reçue!</h3>
                    <div class="order-info">
                        <div class="order-number">${orderResponse.order_number}</div>
                        <p><strong>Please go to the cashier to pay</strong></p>
                        <p><em>Veuillez vous rendre en caisse pour payer</em></p>
                    </div>
                    <div class="countdown">
                        Returning to main screen in <span id="countdown">8</span> seconds...
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(successModal);

        // Start countdown
        this.startCountdown(successModal);
    },

    startCountdown(modal) {
        let count = 8;
        const countdownEl = modal.querySelector('#countdown');
        
        const interval = setInterval(() => {
            count--;
            if (countdownEl) {
                countdownEl.textContent = count;
            }
            
            if (count <= 0) {
                clearInterval(interval);
                if (modal.parentNode) {
                    modal.remove();
                }
                this.resetToHome();
            }
        }, 1000);
    },

    resetToHome() {
        // Clear order data
        if (this.selfOrder.currentOrder) {
            this.selfOrder.currentOrder = null;
        }
        
        // Clear payment method
        window.selectedPaymentMethod = null;
        
        // Navigate to home
        if (this.router) {
            this.router.navigate('default');
        } else {
            // Fallback - reload page
            window.location.reload();
        }
    },

    showError(message) {
        // Create error modal
        const errorModal = document.createElement('div');
        errorModal.className = 'error-modal';
        errorModal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 20000;
        `;
        
        errorModal.innerHTML = `
            <div style="
                background: white;
                padding: 30px;
                border-radius: 15px;
                text-align: center;
                max-width: 400px;
                margin: 20px;
            ">
                <div style="font-size: 3rem; color: #e74c3c; margin-bottom: 15px;">❌</div>
                <h2 style="color: #e74c3c; margin-bottom: 15px;">Error</h2>
                <p style="margin-bottom: 20px; font-size: 1.1rem;">${message}</p>
                <button onclick="this.closest('.error-modal').remove()" style="
                    background: #e74c3c;
                    color: white;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 5px;
                    font-size: 1rem;
                    cursor: pointer;
                ">OK</button>
            </div>
        `;
        
        document.body.appendChild(errorModal);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (errorModal.parentNode) {
                errorModal.remove();
            }
        }, 5000);
    }
});