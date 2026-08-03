/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * SbsOpenLink
 * -----------
 * Renders a field's value as a clickable link inside a list cell. Clicking it
 * opens a related record's form (or a filtered list) WITHOUT opening the row.
 * The template is defined inline (via owl's `xml`) so it can't fail to load.
 *
 * Field `options` (from the field definition / arch):
 *   - res_model, id_field, domain_field, domain_op, name, new_tab
 */
export class SbsOpenLink extends Component {
    static template = xml`
        <t>
            <a t-if="hasValue"
               class="o_sbs_open_link"
               style="text-decoration: underline; cursor: pointer; color: var(--primary, #714B67);"
               t-on-click.stop.prevent="onLinkClick">
                <t t-esc="displayValue"/>
            </a>
            <span t-else="" class="text-muted"/>
        </t>`;
    static props = {
        ...standardFieldProps,
        linkOptions: { type: Object, optional: true },
    };

    setup() {
        this.action = useService("action");
    }

    get options() {
        // options are parsed from the arch and passed in via extractProps
        return this.props.linkOptions || {};
    }

    _idOf(v) {
        // pull a record id out of a many2one value in any shape
        if (v == null || v === false) {
            return false;
        }
        if (Array.isArray(v)) {
            return v[0];
        }
        if (typeof v === "object") {
            return v.id || v.resId || false;
        }
        return v;                                   // scalar (char/int)
    }

    get rawValue() {
        return this.props.record.data[this.props.name];
    }

    get displayValue() {
        const val = this.rawValue;
        if (val == null || val === false) {
            return "";
        }
        if (Array.isArray(val)) {
            return val[1] || "";                    // [id, name]
        }
        if (typeof val === "object") {
            // many2one in newer list views: {id, display_name} / {resId, ...}
            return val.display_name || val.displayName || val.name || "";
        }
        return String(val);
    }

    get hasValue() {
        const val = this.rawValue;
        if (val == null || val === false) {
            return false;
        }
        if (Array.isArray(val)) {
            return !!val[0];
        }
        if (typeof val === "object") {
            return !!(val.id || val.resId || val.display_name);
        }
        return true;
    }

    async onLinkClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();

        const opts = this.options;
        if (!opts.res_model) {
            return;
        }
        const newTab = !!opts.new_tab;

        if (opts.domain_field) {
            const fv = this.props.record.data[opts.domain_field];
            const value = this._idOf(fv);
            if (value === false || value == null) {
                return;
            }
            const op = opts.domain_op || "=";
            const domain = [[opts.domain_field, op, value]];
            // A filtered LIST always opens via doAction (same tab). Odoo 19
            // dropped the legacy /web# hash router, so a domain can't be carried
            // to a fresh browser tab reliably - new_tab is honored only for the
            // single-record form case below.
            await this.action.doAction({
                type: "ir.actions.act_window",
                name: opts.name || "Records",
                res_model: opts.res_model,
                domain: domain,
                view_mode: "list,form",
                views: [[false, "list"], [false, "form"]],
                target: "current",
            });
            return;
        }

        const idField = opts.id_field || this.props.name;
        const resId = this._idOf(this.props.record.data[idField]);
        if (!resId) {
            return;
        }

        if (newTab) {
            const url = `/odoo/${encodeURIComponent(opts.res_model)}/${resId}`;
            window.open(url, "_blank");
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: opts.name || "Open",
            res_model: opts.res_model,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

export const sbsOpenLink = {
    component: SbsOpenLink,
    supportedTypes: ["char", "many2one", "integer"],
    extractProps: ({ options }) => ({ linkOptions: options || {} }),
};
registry.category("fields").add("sbs_open_link", sbsOpenLink);