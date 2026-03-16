/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.MarketplaceOffers = publicWidget.Widget.extend({
    selector: '#marketplace-offers',

    events: {
        'click  .mp-qty-minus':        '_onMinus',
        'click  .mp-qty-plus':         '_onPlus',
        'input  .mp-qty-input':        '_onQtyInput',
        'change .mp-qty-input':        '_onQtyChange',
        'click  .mp-add-to-cart':      '_onAddToCart',
        'click  .mp-whatsapp-contact': '_onWhatsAppContact',  // <-- جدید
    },

    // ─────────────────────────────────────────────────────────────────
    // Lifecycle
    // ─────────────────────────────────────────────────────────────────

    start() {
        this._super(...arguments);
        this.$('.mp-offer-row').each((_, row) => {
            // فقط برای offer های active total رو محاسبه کن
            if ($(row).data('is-expired') !== '1') {
                this._updateTotal($(row));
            }
        });
        this._refreshAllProgress();
    },

    // ─────────────────────────────────────────────────────────────────
    // Helpers
    // ─────────────────────────────────────────────────────────────────

    _getRow(ev) {
        return $(ev.currentTarget).closest('.mp-offer-row');
    },

    _getCaseSize($row) {
        return Math.max(parseInt($row.data('case-size') || 1, 10), 1);
    },

    _updateTotal($row) {
        const $input      = $row.find('.mp-qty-input');
        const $btn        = $row.find('.mp-add-to-cart');
        const bundlePrice = parseFloat($btn.data('bundle-price') || 0);
        const qty         = parseInt($input.val(), 10) || 1;
        const total       = (qty * bundlePrice).toFixed(2);
        $row.find('.mp-total-value').text(`$${total}`);
    },

    // ─────────────────────────────────────────────────────────────────
    // WhatsApp Contact  <-- جدید
    // ─────────────────────────────────────────────────────────────────

     _onWhatsAppContact(ev) {
        ev.preventDefault();
        ev.stopPropagation();

        const $btn = $(ev.currentTarget);

        // ── خواندن داده‌ها ─────────────────────────────────────────
        const importNumber = String($btn.data('import-number') || '').trim();
        const productName  = String($btn.data('product-name')  || '').trim();

        // ── شماره رو مستقیم از data attribute بخون و پاکسازی کن ──
        const rawNumber      = String(this.$el.data('whatsapp') || '').trim();
        const whatsappNumber = rawNumber.replace(/[^0-9]/g, ''); // فقط عدد

        // ── Debug ─────────────────────────────────────────────────
        console.log('[WA Debug] rawNumber:',      rawNumber);
        console.log('[WA Debug] cleanNumber:',    whatsappNumber);
        console.log('[WA Debug] importNumber:',   importNumber);
        console.log('[WA Debug] productName:',    productName);

        if (!whatsappNumber) {
            alert('WhatsApp number is not configured.');
            return;
        }

        // ── ساخت متن ─────────────────────────────────────────────
        const text = 
            `Hello, I am interested in an expired offer.\n` +
            `Product: ${productName}\n` +
            `Price List: #${importNumber}\n` +
            `Please let me know about current availability and pricing.`;

        // ── ساخت URL — بدون هیچ encode اضافی روی شماره ──────────
        const waUrl = 'https://wa.me/' + whatsappNumber + '?text=' + encodeURIComponent(text);

        console.log('[WA Debug] Final URL:', waUrl);

        // ── باز کردن ─────────────────────────────────────────────
        window.open(waUrl, '_blank');
    },


    // ─────────────────────────────────────────────────────────────────
    // Qty Buttons
    // ─────────────────────────────────────────────────────────────────

    _onMinus(ev) {
        const $row   = this._getRow(ev);
        const $input = $row.find('.mp-qty-input');
        const val    = parseInt($input.val(), 10) || 1;
        if (val > 1) {
            $input.val(val - 1);
            this._updateTotal($row);
        }
    },

    _onPlus(ev) {
        const $row   = this._getRow(ev);
        const $input = $row.find('.mp-qty-input');
        const val    = parseInt($input.val(), 10) || 1;
        $input.val(val + 1);
        this._updateTotal($row);
    },

    _onQtyInput(ev) {
        this._updateTotal($(ev.currentTarget).closest('.mp-offer-row'));
    },

    _onQtyChange(ev) {
        const $input = $(ev.currentTarget);
        const val    = parseInt($input.val(), 10);
        if (!val || val < 1) $input.val(1);
        this._updateTotal($input.closest('.mp-offer-row'));
    },

    // ─────────────────────────────────────────────────────────────────
    // Add to Cart
    // ─────────────────────────────────────────────────────────────────

    async _onAddToCart(ev) {
        const $btn       = $(ev.currentTarget);
        const $row       = $btn.closest('.mp-offer-row');
        const offerId    = parseInt($row.data('offer-id'),            10);
        const productId  = parseInt($row.data('product-id'),          10);
        const templateId = parseInt($row.data('product-template-id'), 10);
        const uomId      = parseInt($btn.data('uom-id') || 0, 10);
        const qtyBundles = parseInt($row.find('.mp-qty-input').val(), 10) || 1;

        if (!offerId || !productId) {
            console.error('MP: missing offer/product id', { offerId, productId });
            return;
        }

        $btn.prop('disabled', true)
            .html('<i class="fa fa-spinner fa-spin me-1"/>Adding...');

        try {
            await rpc('/shop/cart/add', {
                product_id:           productId,
                product_template_id:  templateId,
                quantity:             qtyBundles,
                uom_id:               uomId || false,
                marketplace_offer_id: offerId,
            });

            $btn.removeClass('btn-primary')
                .addClass('btn-success')
                .html('<i class="fa fa-check me-1"/>Added!');

            $(document.body).trigger('cart_update');

            $row.find('.mp-qty-input').val(1);
            this._updateTotal($row);

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
                .html('<i class="fa fa-times me-1"/>Error')
                .removeClass('btn-primary btn-success')
                .addClass('btn-danger');

            setTimeout(() => {
                $btn.removeClass('btn-danger')
                    .addClass('btn-primary')
                    .html('<i class="fa fa-cart-plus me-1"/>Add to Cart');
            }, 2000);
        }
    },

    // ─────────────────────────────────────────────────────────────────
    // Progress Bars (MOV / MOQ)
    // ─────────────────────────────────────────────────────────────────

    async _refreshAllProgress() {
        const importNumbers = [];
        // فقط offer های active رو برای progress bar در نظر بگیر
        this.$('.mp-offer-row[data-is-expired="0"]').each(function () {
            const imp = String($(this).data('import-number') || '');
            if (imp && !importNumbers.includes(imp)) importNumbers.push(imp);
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
        // فقط ردیف‌های active رو آپدیت کن
        this.$('.mp-offer-row[data-is-expired="0"]').each(function () {
            const $row      = $(this);
            const impNum    = String($row.data('import-number') || '');
            const targetMov = parseFloat($row.data('target-mov') || 0);
            const targetMoq = parseInt($row.data('target-moq')   || 0, 10);
            const caseSize  = Math.max(parseInt($row.data('case-size') || 1, 10), 1);

            const basket      = totals[impNum] || { total_value: 0.0, total_qty: 0 };
            const cartValue   = parseFloat(basket.total_value || 0);
            const cartBundles = parseInt(basket.total_qty || 0, 10);
            const cartUnits   = cartBundles * caseSize;

            // ── Badge ──────────────────────────────────────────────────
            const $badge      = $row.find('.mp-in-cart-badge');
            const $unitsLabel = $row.find('.mp-in-cart-units');

            if (cartBundles > 0) {
                $badge.text(
                    caseSize > 1
                        ? `${cartBundles} pack${cartBundles !== 1 ? 's' : ''} in cart`
                        : `${cartBundles} in cart`
                ).show();
                if (caseSize > 1) {
                    $unitsLabel.text(`(${cartUnits} units total)`).show();
                } else {
                    $unitsLabel.hide();
                }
            } else {
                $badge.hide();
                $unitsLabel.hide();
            }

            // ── Total Preview ──────────────────────────────────────────
            const $totalValue = $row.find('.mp-total-value');
            const $qtyInput   = $row.find('.mp-qty-input');
            const bundlePrice = parseFloat($row.find('.mp-add-to-cart').data('bundle-price') || 0);
            const currentQty  = parseInt($qtyInput.val(), 10) || 1;

            if (cartBundles > 0) {
                $totalValue.text(`$${cartValue.toFixed(2)}`);
            } else {
                const previewTotal = (currentQty * bundlePrice).toFixed(2);
                $totalValue.text(`$${previewTotal}`);
            }

            // ── MOV ────────────────────────────────────────────────────
            if (targetMov > 0) {
                const movPct = Math.min((cartValue / targetMov) * 100, 100);
                const $bar   = $row.find('.mov-progress-bar-fill');
                const $label = $row.find('.mov-progress-label');

                $bar.css('width', movPct.toFixed(1) + '%')
                    .removeClass('bg-danger bg-warning bg-success')
                    .addClass(
                        movPct >= 100 ? 'bg-success' :
                        movPct >= 50  ? 'bg-warning'  :
                                        'bg-danger'
                    );

                if (movPct >= 100) {
                    $label.html(
                        '<span class="text-success fw-semibold">'
                        + '<i class="fa fa-check me-1"/>MOV met</span>'
                    );
                } else {
                    const rem = (targetMov - cartValue).toFixed(2);
                    $label.html(
                        `<span class="text-muted">`
                        + `$${cartValue.toFixed(2)} / $${targetMov.toFixed(2)}`
                        + ` &nbsp;<small>($${rem} more)</small>`
                        + `</span>`
                    );
                }
            }

            // ── MOQ ────────────────────────────────────────────────────
            if (targetMoq > 0) {
                const $moqLabel = $row.find('.moq-status-label');

                if (cartUnits >= targetMoq) {
                    $moqLabel.html(
                        `<span class="text-success fw-semibold">`
                        + `<i class="fa fa-check me-1"/>MOQ met`
                        + ` (${cartUnits}/${targetMoq})`
                        + `</span>`
                    );
                } else {
                    const need = targetMoq - cartUnits;
                    $moqLabel.html(
                        `<span class="text-warning">`
                        + `${cartUnits}/${targetMoq} `
                        + `<small class="text-muted">(${need} more needed)</small>`
                        + `</span>`
                    );
                }
            }
        });
    },
});

export default publicWidget.registry.MarketplaceOffers;
