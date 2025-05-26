/** @odoo-module **/
// File: pos_kiosk_cash_credit/static/src/js/eating_location_page_patch.js

import { patch } from "@web/core/utils/patch";
import { EatingLocationPage } from "@pos_self_order/app/pages/eating_location_page/eating_location_page";

patch(EatingLocationPage.prototype, {
    
    selectLocation(location) {
        // Store the selected eating location
        this.selfOrder.currentOrder.eating_location = location;
        
        console.log('Eating location selected:', location);
        
        // Show payment method selection
        this.showPaymentMethodSelection();
    },

    showPaymentMethodSelection() {
        // Remove any existing modal
        this.removeExistingModal();

        // Create payment method selection modal
        const paymentModal = this.createPaymentModal();
        
        // Add event listeners
        this.attachModalEventListeners(paymentModal);
        
        // Add to DOM
        document.body.appendChild(paymentModal);
        
        // Add animation
        setTimeout(() => {
            paymentModal.classList.add('show');
        }, 10);
    },

    removeExistingModal() {
        const existingModal = document.querySelector('.payment-method-modal');
        if (existingModal) {
            existingModal.remove();
        }
    },

    createPaymentModal() {
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
        
        return paymentModal;
    },

    attachModalEventListeners(modal) {
        const cashBtn = modal.querySelector('[data-method="cash"]');
        const cardBtn = modal.querySelector('[data-method="card"]');
        const backBtn = modal.querySelector('.btn-back');
        const overlay = modal.querySelector('.payment-method-overlay');

        // Cash payment selection
        cashBtn.addEventListener('click', (e) => {
            e.preventDefault();
            this.selectPaymentMethod('cash');
        });

        // Card payment selection
        cardBtn.addEventListener('click', (e) => {
            e.preventDefault();
            this.selectPaymentMethod('card');
        });

        // Back button
        backBtn.addEventListener('click', (e) => {
            e.preventDefault();
            this.closeModal(modal);
        });

        // Click outside to close (optional)
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                this.closeModal(modal);
            }
        });

        // Escape key to close
        const escapeHandler = (e) => {
            if (e.key === 'Escape') {
                this.closeModal(modal);
                document.removeEventListener('keydown', escapeHandler);
            }
        };
        document.addEventListener('keydown', escapeHandler);
    },

    closeModal(modal) {
        if (modal && modal.parentNode) {
            modal.classList.add('closing');
            setTimeout(() => {
                if (modal.parentNode) {
                    modal.remove();
                }
            }, 300);
        }
    },

    selectPaymentMethod(method) {
        console.log('Payment method selected:', method);
        
        // Remove modal with animation
        const modal = document.querySelector('.payment-method-modal');
        if (modal) {
            this.closeModal(modal);
        }

        // Store payment method globally and in order
        window.selectedPaymentMethod = method;
        
        if (this.selfOrder.currentOrder) {
            this.selfOrder.currentOrder.payment_method = method;
            this.selfOrder.currentOrder.is_cash = (method === 'cash');
            this.selfOrder.currentOrder.is_kiosk = true;
        }
        
        // Continue to the next step based on the standard flow
        // In pos_self_order, after eating location usually comes the confirmation
        // or product list, depending on the configuration
        
        if (method === 'cash') {
            // For cash, we can go directly to confirmation
            // since we'll handle payment differently
            this.proceedToConfirmation();
        } else {
            // For card, continue with normal flow
            this.proceedToNextStep();
        }
    },

    proceedToConfirmation() {
        // Navigate directly to confirmation for cash orders
        if (this.router) {
            this.router.navigate('confirmation');
        }
    },

    proceedToNextStep() {
        // Continue with the normal flow for card payments
        // This depends on your pos_self_order configuration
        if (this.router) {
            // Check if there are more products to add or go to confirmation
            const hasProducts = this.selfOrder.currentOrder?.lines?.length > 0;
            
            if (hasProducts) {
                this.router.navigate('confirmation');
            } else {
                this.router.navigate('product_list');
            }
        }
    },

    // Override the default navigation if needed
    async nextPage() {
        // If payment method is not selected, show selection
        const paymentMethod = this.selfOrder.currentOrder?.payment_method || window.selectedPaymentMethod;
        
        if (!paymentMethod) {
            // Payment method not selected yet, show selection modal
            this.showPaymentMethodSelection();
        } else {
            // Payment method already selected, proceed normally
            await super.nextPage();
        }
    }
});