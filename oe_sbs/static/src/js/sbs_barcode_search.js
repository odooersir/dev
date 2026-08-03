/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

/**
 * SbsBarcodeSearch
 * ----------------
 * Renders a barcode as a link. Clicking it opens a NEW BROWSER TAB listing every
 * SBS row carrying that barcode, with the barcode already sitting as a facet in
 * the search box - so the user can widen or narrow it from there instead of
 * getting a dead-end filtered list.
 *
 * How the new tab keeps the filter
 * --------------------------------
 * Odoo 19's URL router only understands action / resId / active_id / model
 * (see PATH_KEYS in web/core/browser/router.js), so a `search_default_*` cannot
 * travel in a URL - which is why other widgets in this module fall back to the
 * same tab. The action service does support it though: doAction(action,
 * {newWindow: true}) writes the whole action, context included, into
 * sessionStorage and opens the tab, and sessionStorage is copied into the new
 * browsing context by the HTML spec. That is the supported path and the one
 * used here.
 *
 * `search_default_ean` matches the <field name="ean"/> of the sbs.data search
 * view and produces a real search facet, not a hidden domain.
 *
 * Field `options` (from the arch):
 *   - name: title for the opened action (default 'Barcode')
 */
export class SbsBarcodeSearch extends Component {
    static template = xml`
        <t>
            <a t-if="barcode"
               class="o_sbs_barcode_search"
               t-att-title="titleText"
               style="text-decoration: underline; cursor: pointer; color: var(--primary, #714B67);"
               t-on-click.stop.prevent="onBarcodeClick">
                <t t-esc="barcode"/>
            </a>
            <span t-else="" class="text-muted"/>
        </t>`;
    static props = {
        ...standardFieldProps,
        searchOptions: { type: Object, optional: true },
    };

    setup() {
        this.action = useService("action");
    }

    get barcode() {
        const val = this.props.record.data[this.props.name];
        return val ? String(val).trim() : "";
    }

    get titleText() {
        return _t("Search this barcode in a new tab");
    }

    async onBarcodeClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();

        const barcode = this.barcode;
        if (!barcode) {
            return;
        }
        const opts = this.props.searchOptions || {};

        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: `${opts.name || _t("Barcode")}: ${barcode}`,
                res_model: this.props.record.resModel,
                views: [
                    [false, "list"],
                    [false, "form"],
                ],
                target: "current",
                // a facet in the search box, not a buried domain
                context: { search_default_ean: barcode },
            },
            { newWindow: true }
        );
    }
}

export const sbsBarcodeSearch = {
    component: SbsBarcodeSearch,
    displayName: _t("Barcode Search Link"),
    supportedTypes: ["char"],
    extractProps: ({ options }) => ({ searchOptions: options || {} }),
};
registry.category("fields").add("sbs_barcode_search", sbsBarcodeSearch);
