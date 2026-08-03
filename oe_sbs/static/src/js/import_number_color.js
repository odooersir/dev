/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, xml } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Colour the Import Number so each import block is visually separated in the
 * list: consecutive import numbers always get different colours.
 *
 * The colour index is derived from the NUMBER itself (not a hash), so
 * 00041 -> 00042 -> 00043 walk through the palette one step at a time and can
 * never collide with their neighbour. The colour is also stable: the same
 * import number always renders in the same colour, in every list and after a
 * reload.
 *
 * The template is declared INLINE (owl `xml`) on purpose - a separate XML
 * asset can silently fail to load and leave the field rendering as a bare
 * span with no colour.
 */
const PALETTE_SIZE = 8;

export class ImportNumberColorField extends Component {
    static template = xml`
        <span t-att-class="'o_sbs_in o_sbs_in_' + colorIndex"
              t-att-title="props.record.data[props.name]"
              t-esc="value"/>`;
    static props = { ...standardFieldProps };

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get colorIndex() {
        const raw = String(this.value);
        const digits = raw.replace(/\D/g, "");
        if (digits) {
            // last 6 digits is plenty and keeps us inside a safe integer
            return parseInt(digits.slice(-6), 10) % PALETTE_SIZE;
        }
        // non-numeric import numbers: fall back to a stable string hash
        let h = 0;
        for (let i = 0; i < raw.length; i++) {
            h = (h * 31 + raw.charCodeAt(i)) >>> 0;
        }
        return h % PALETTE_SIZE;
    }
}

export const importNumberColorField = {
    component: ImportNumberColorField,
    supportedTypes: ["char"],
};
registry.category("fields").add("import_number_color", importNumberColorField);
