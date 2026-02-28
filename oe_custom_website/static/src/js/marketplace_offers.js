/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.MarketplaceOffers = publicWidget.Widget.extend({
    selector: '#marketplace-offers',

    events: {
        'click .mp-qty-minus':   '_onMinus',
        'click .mp-qty-plus':    '_onPlus',
        'change .mp-qty-input':  '_onQtyChange',
        'click .mp-add-to-cart': '_onAddToCart',
    },

    // ─── Widget lifecycle ─────────────────────────────────────────

    start() {
        this._super(...arguments);
        this._refreshAllProgress();
    },

    // ─── Quantity helpers ─────────────────────────────────────────

    _getRow(ev) {
        return $(ev.currentTarget).closest('.mp-offer-row');
    },

    _onMinus(ev) {
        const $input = this._getRow(ev).find('.mp-qty-input');
        const val = parseInt($input.val(), 10) || 1;
        if (val > 1) $input.val(val - 1);
    },

    _onPlus(ev) {
        const $input = this._getRow(ev).find('.mp-qty-input');
        const val = parseInt($input.val(), 10) || 1;
        $input.val(val + 1);
    },

    _onQtyChange(ev) {
        const $input = $(ev.currentTarget);
        const val = parseInt($input.val(), 10);
        if (!val || val < 1) $input.val(1);
    },

    // ─── Add to Cart ──────────────────────────────────────────────

    async _onAddToCart(ev) {
        const $btn       = $(ev.currentTarget);
        const $row       = $btn.closest('.mp-offer-row');
        const offerId    = parseInt($row.data('offer-id'),            10);
        const productId  = parseInt($row.data('product-id'),          10);
        const templateId = parseInt($row.data('product-template-id'), 10);
        const qty        = parseInt($row.find('.mp-qty-input').val(), 10) || 1;

        if (!offerId || !productId) {
            console.error('MP: missing offer/product id', { offerId, productId });
            return;
        }

        $btn.prop('disabled', true)
            .html('<i class="fa fa-spinner fa-spin me-1"/>Adding…');

        try {
            await rpc('/shop/cart/add', {
                product_id:           productId,
                product_template_id:  templateId,
                quantity:             qty,
                marketplace_offer_id: offerId,
            });

            $btn.removeClass('btn-primary')
                .addClass('btn-success')
                .html('<i class="fa fa-check me-1"/>Added!');

            $(document.body).trigger('cart_update');

            await this._refreshAllProgress();

            setTimeout(() => {
                $btn.prop('disabled', false)
                    .removeClass('btn-success')
                    .addClass('btn-primary')
                    .html('<i class="fa fa-cart-plus me-1"/>Add to Cart');
            }, 1800);

        } catch (err) {
            console.error('MP: add to cart failed', err);
            $btn.prop('disabled', false)
                .removeClass('btn-primary btn-success')
                .addClass('btn-danger')
                .html('<i class="fa fa-times me-1"/>Error');

            setTimeout(() => {
                $btn.removeClass('btn-danger')
                    .addClass('btn-primary')
                    .html('<i class="fa fa-cart-plus me-1"/>Add to Cart');
            }, 2000);
        }
    },

    // ─── Progress Bar + "X in cart" ───────────────────────────────

    async _refreshAllProgress() {
        const importNumbers = [];
        this.$('.mp-offer-row').each(function () {
            const imp = String($(this).data('import-number') || '');
            if (imp && !importNumbers.includes(imp)) {
                importNumbers.push(imp);
            }
        });

        if (!importNumbers.length) return;

        try {
            const totals = await rpc('/marketplace/cart/basket_totals', {
                import_numbers: importNumbers,
            });
            this._updateAllProgressBars(totals);
        } catch (err) {
            console.warn('MP: basket_totals fetch failed', err);
        }
    },

    _updateAllProgressBars(totals) {
        this.$('.mp-offer-row').each(function () {
            const $row      = $(this);
            const impNum    = String($row.data('import-number') || '');
            const targetMov = parseFloat($row.data('target-mov') || 0);
            const targetMoq = parseInt($row.data('target-moq')  || 0, 10);

            const basket    = totals[impNum] || { total_value: 0, total_qty: 0 };
            const cartValue = parseFloat(basket.total_value || 0);
            const cartQty   = parseInt(basket.total_qty    || 0, 10);

            // ── "X in cart" badge ─────────────────────────────────
            const $badge = $row.find('.mp-in-cart-badge');
            if (cartQty > 0) {
                $badge.text(cartQty + ' in cart').show();
            } else {
                $badge.text('').hide();
            }

            // ── MOV progress bar ──────────────────────────────────
            if (targetMov > 0) {
                const movPct = Math.min((cartValue / targetMov) * 100, 100);
                const $bar   = $row.find('.mov-progress-bar-fill');
                const $label = $row.find('.mov-progress-label');

                $bar.css('width', movPct.toFixed(1) + '%')
                    .removeClass('bg-danger bg-warning bg-success')
                    .addClass(
                        movPct >= 100 ? 'bg-success' :
                        movPct >= 50  ? 'bg-warning'  : 'bg-danger'
                    );

                if (movPct >= 100) {
                    $label.html(
                        '<span class="text-success fw-semibold">'
                        + '<i class="fa fa-check me-1"/>MOV met</span>'
                    );
                } else {
                    const remaining = (targetMov - cartValue).toFixed(2);
                    $label.html(
                        `<span class="text-muted">`
                        + `$${cartValue.toFixed(2)} / $${targetMov.toFixed(2)}`
                        + ` &nbsp;<small>($${remaining} more needed)</small></span>`
                    );
                }
            }

            // ── MOQ status ────────────────────────────────────────
            if (targetMoq > 0) {
                const $moqLabel = $row.find('.moq-status-label');
                if (cartQty >= targetMoq) {
                    $moqLabel.html(
                        `<span class="text-success fw-semibold">`
                        + `<i class="fa fa-check me-1"/>MOQ met `
                        + `(${cartQty}/${targetMoq})</span>`
                    );
                } else {
                    const need = targetMoq - cartQty;
                    $moqLabel.html(
                        `<span class="text-warning">`
                        + `${cartQty}/${targetMoq} `
                        + `<small class="text-muted">(${need} more needed)</small></span>`
                    );
                }
            }
        });
    },
});

export default publicWidget.registry.MarketplaceOffers;
