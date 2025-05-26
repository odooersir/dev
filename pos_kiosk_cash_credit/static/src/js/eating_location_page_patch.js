/** @odoo-module **/
// File: pos_kiosk_cash_credit/static/src/js/eating_location_page_patch.js

import { patch } from "@web/core/utils/patch";
import { EatingLocationPage } from "@pos_self_order/app/pages/eating_location_page/eating_location_page";

patch(EatingLocationPage.prototype, {
    
    selectLocation(location) {
        // Store the selected location first
        this.selfOrder.currentOrder.eating_location = location;
        
        // Show payment method selection directly
        this.showPaymentMethodSelection();
    },

    showPaymentMethodSelection() {
        // Remove any existing payment modal
        const existingModal = document.querySelector('.payment-method-modal');
        if (existingModal) {
            existingModal.remove();
        }

        // Create a simple modal for payment method selection
        const paymentModal = document.createElement('div');
        paymentModal.className = 'payment-method-modal';
        paymentModal.innerHTML = `
            <div class="payment-method-overlay">
                <div class="payment-method-screen">
                    <div class="screen-header">
                        <h1>Choose Payment Method</h1>
                        <h2>Choisissez votre mode de paiement</h2>
                    </div>
                    
                    <div class="payment-options">
                        <button class="payment-option cash-option" data-method="cash">
                            <div class="option-icon">💰</div>
                            <div class="option-text">
                                <h3>Cash</h3>
                                <p>Pay at cashier</p>
                                <small>Payer en caisse</small>
                            </div>
                        </button>
                        
                        <button class="payment-option card-option" data-method="card">
                            <div class="option-icon">💳</div>
                            <div class="option-text">
                                <h3>Credit Card</h3>
                                <p>Pay now</p>
                                <small>Payer maintenant</small>
                            </div>
                        </button>
                    </div>
                    
                    <div class="screen-footer">
                        <button class="btn-back">
                            ← Back / Retour
                        </button>
                    </div>
                </div>
            </div>
        `;

        // Add event listeners
        const cashBtn = paymentModal.querySelector('[data-method="cash"]');
        const cardBtn = paymentModal.querySelector('[data-method="card"]');
        const backBtn = paymentModal.querySelector('.btn-back');

        cashBtn.addEventListener('click', () => {
            this.selectPaymentMethod('cash');
        });

        cardBtn.addEventListener('click', () => {
            this.selectPaymentMethod('card');
        });

        backBtn.addEventListener('click', () => {
            paymentModal.remove();
        });

        // Add to DOM
        document.body.appendChild(paymentModal);
    },

    selectPaymentMethod(method) {
        // Remove the modal
        const modal = document.querySelector('.payment-method-modal');
        if (modal) {
            modal.remove();
        }

        // Store payment method in a simple way
        window.selectedPaymentMethod = method;
        
        // Add a flag to the current order
        if (this.selfOrder.currentOrder) {
            this.selfOrder.currentOrder.payment_method = method;
            this.selfOrder.currentOrder.is_cash = (method === 'cash');
            this.selfOrder.currentOrder.is_kiosk = true;
        }
        
        // Continue to product list
        this.router.navigate('product_list');
    }
});