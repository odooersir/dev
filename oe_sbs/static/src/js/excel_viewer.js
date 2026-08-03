/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useRef, onMounted, onPatched, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { buildGridHtml, escapeHtml } from "./excel_grid";

/**
 * Read-only Excel viewer.
 *
 * Same SheetJS engine as the import-template mapper, minus the mapping: it
 * just renders the workbook (all sheets, merges, number formatting) so a
 * document can be inspected without downloading it.
 *
 * The bytes are fetched through the ORM (`sbs_get_file_b64`) rather than a
 * /web/content URL, because a documents.document may keep its content on the
 * attachment, on `raw`, or on `datas` - the server helper handles all three.
 */
export class ExcelViewerField extends Component {
    static template = "oe_sbs.ExcelViewerField";
    static props = {
        ...standardFieldProps,
        maxRows: { type: Number, optional: true },
    };

    setup() {
        this.gridRef = useRef("grid");
        this.orm = useService("orm");
        this.state = useState({
            error: null,
            loading: true,
            sheets: [],
            active: 0,
            sheetCounts: [],
            fullscreen: false,
            showAll: false,
            totalRows: 0,
            shownRows: 0,
        });
        this.wb = null;
        onMounted(() => this._load());
        onPatched(() => this._paint());
    }

    get maxRows() {
        if (this.state.showAll) return 0;           // 0 = no cap
        return this.props.maxRows || 300;
    }

    get hasMore() {
        return this.state.totalRows > this.state.shownRows;
    }

    async _load() {
        const rec = this.props.record;
        if (!rec.resId) {
            this.state.loading = false;
            this.state.error = "Save the record first.";
            return;
        }
        try {
            const res = await this.orm.call(
                rec.resModel, "sbs_get_file_b64", [[rec.resId]]
            );
            if (!res || res.error) {
                this.state.error = (res && res.error) || "No file content.";
                return;
            }
            this._parse(this._b64ToArrayBuffer(res.data));
        } catch (e) {
            this.state.error = String(e.message || e);
        } finally {
            this.state.loading = false;
        }
    }

    _parse(buffer) {
        const XLSX = window.XLSX;
        if (!XLSX) {
            this.state.error = "SheetJS library not loaded.";
            return;
        }
        try {
            this.wb = XLSX.read(new Uint8Array(buffer), { type: "array" });
        } catch (e) {
            this.state.error = String(e.message || e);
            return;
        }
        this._lastSig = null;
        this.state.sheets = this.wb.SheetNames;
        this.state.active = 0;
    }

    toggleFullscreen() {
        this.state.fullscreen = !this.state.fullscreen;
    }

    loadAllRows() {
        this.state.showAll = true;
        this._lastSig = null;
    }

    _paint() {
        if (!this.wb || !this.gridRef.el) return;
        const sig = `${this.maxRows}#${this.wb.SheetNames.join("|")}`;
        if (this._lastSig === sig) return;
        this._lastSig = sig;

        // Render EVERY sheet, stacked, so a multi-sheet workbook is visible in
        // one pass. The tab bar above just scrolls to a section - nothing is
        // hidden behind it.
        const parts = [];
        const counts = [];
        let total = 0;
        let shown = 0;

        this.wb.SheetNames.forEach((name, i) => {
            const ws = this.wb.Sheets[name];
            const { html, totalRows, shownRows } = buildGridHtml(window.XLSX, ws, {
                maxRows: this.maxRows,
                clickable: false,
            });
            total += totalRows;
            shown += shownRows;
            counts.push(totalRows);
            const more = totalRows > shownRows
                ? ` <span class="o_xlsx_more">(showing ${shownRows} of ${totalRows} rows)</span>`
                : (totalRows ? ` <span class="o_xlsx_more">(${totalRows} rows)</span>` : "");
            parts.push(
                `<div class="o_xlsx_sheet" data-sheet-idx="${i}">` +
                `<div class="o_xlsx_sheet_title">${escapeHtml(name)}${more}</div>` +
                html +
                `</div>`
            );
        });

        this.gridRef.el.innerHTML = parts.join("");
        this.state.sheetCounts = counts;
        this.state.totalRows = total;
        this.state.shownRows = shown;
    }

    /** Scroll to a sheet section instead of swapping the visible sheet. */
    selectSheet(i) {
        this.state.active = i;
        const el = this.gridRef.el
            && this.gridRef.el.querySelector(`[data-sheet-idx="${i}"]`);
        if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    _b64ToArrayBuffer(b64) {
        const binary = atob(b64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }
}

export const excelViewerField = {
    component: ExcelViewerField,
    supportedTypes: ["binary", "char"],
    // options from the XML arch only reach the component through extractProps
    extractProps: ({ options }) => ({
        maxRows: (options && options.max_rows) || 300,
    }),
};
registry.category("fields").add("excel_viewer", excelViewerField);
