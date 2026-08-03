/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useRef, onMounted, onPatched, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { buildGridHtml } from "./excel_grid";

const SBS_FIELDS = [
    { label: "Barcode", col: "ean_col", header: "ean_header", syn: ["barcode", "ean", "gtin", "ean13", "bar code"] },
    { label: "HS Code", col: "hs_code_col", header: "hs_code_header", syn: ["hs code", "hs", "tariff", "hscode", "commodity code"] },
    { label: "Language", col: "cover_language_col", header: "cover_language_header", syn: ["language", "languages", "cover language", "pack language", "lang", "languages on pack"] },
    { label: "Product Name", col: "product_name_col", header: "product_name_header", syn: ["description", "product name", "item name", "article", "desc", "product", "name"] },
    { label: "Case Price", col: "case_price_col", header: "case_price_header", syn: ["case price", "price/case", "case cost", "cost/case", "price per case", "carton price", "price/carton", "box price", "ctn price"] },
    { label: "Unit Price", col: "price_col", header: "price_header", syn: ["price", "unit price", "cost", "net price", "ppu"] },
   // { label: "Supplier Code", col: "supplier_code_col", header: "supplier_code_header", syn: ["supplier code", "vendor code", "sku", "item code", "ref", "reference", "article code"] },
    { label: "Brand", col: "brand_col", header: "brand_header", syn: ["brand"] },
    { label: "Unit/Case", col: "case_size_col", header: "case_size_header", syn: ["case pack", "case size", "carton", "units per case", "ctn", "case", "pcspercarton", "pcs per carton", "pieces per carton", "units per carton", "pcs/carton", "unit/case", "units/case", "unit per case", "u/case", "pcs/case", "qty/case"] },
    { label: "Size", col: "size_col", header: "size_header", syn: ["size", "volume", "content", "ml"] },
    { label: "Unit/Layer", col: "unit_per_layer_col", header: "unit_per_layer_header", syn: ["unit/layer", "units per layer", "unit per layer", "u/layer", "units/layer", "pcs/layer", "pcs per layer", "pieces per layer", "qty/layer"] },
    { label: "Unit/Pallet", col: "unit_per_pallet_col", header: "unit_per_pallet_header", syn: ["unit/pallet", "units per pallet", "unit per pallet", "u/pallet", "units/pallet", "pcs/pallet", "pcs per pallet", "pieces per pallet", "qty/pallet", "pcs/pll", "pcs/plt", "pcs per pll", "u/pll", "units/pll", "unit/pll", "pcs/pal", "pcs per pal", "u/pal", "units/pal"] },
    { label: "Case/Layer", col: "layer_col", header: "layer_header", syn: ["layer", "ti", "case/layer", "cases/layer", "case per layer", "cases per layer", "ctn/layer", "carton/layer", "cartons per layer"] },
    { label: "Case/Pallet", col: "pallet_col", header: "pallet_header", syn: ["pallet", "hi", "ctnperpallet", "ctn per pallet", "cartons per pallet", "cases per pallet", "cases/pallet", "ctn/pallet", "case/pallet", "case per pallet", "carton/pallet", "case/pll", "cases/pll", "ctn/pll", "case/plt", "cases/plt", "case/pal", "cases/pal"] },
    { label: "Available Case", col: "available_case_col", header: "available_case_header", syn: ["available case", "available cases", "stock case", "stock cases", "cases available", "case stock", "avail case", "avail cases", "qty case", "case qty"] },
    { label: "Available Pallet", col: "available_pallet_col", header: "available_pallet_header", syn: ["available pallet", "available pallets", "stock pallet", "stock pallets", "pallets available", "pallet stock", "avail pallet", "avail pallets", "qty pallet", "pallet qty", "available pll", "stock pll"] },
    { label: "Available Unit", col: "available_qty_col", header: "available_qty_header", syn: ["stock", "qty", "quantity", "available", "availability"] },
   // { label: "MOQ", col: "moq_col", header: "moq_header", syn: ["moq", "minimum order quantity", "min order qty", "min order"] },
   // { label: "MOV", col: "mov_col", header: "mov_header", syn: ["mov", "minimum order value", "min order value"] },
  //  { label: "Payment Terms", col: "payment_terms_col", header: "payment_terms_header", syn: ["payment terms", "payment", "terms"] },
   // { label: "Incoterms", col: "incoterms_col", header: "incoterms_header", syn: ["incoterms", "incoterm", "delivery terms"] },
  //  { label: "T1 / T2", col: "t1_t2_col", header: "t1_t2_header", syn: ["t1/t2", "t1", "t2", "customs status"] },
    { label: "COO", col: "coo_col", header: "coo_header", syn: ["country of origin", "coo", "origin", "made in"] },
   // { label: "Lead Time", col: "lead_time_col", header: "lead_time_header", syn: ["lead time", "leadtime", "delivery time"] },
    { label: "Product Expiry", col: "product_expiry_col", header: "product_expiry_header", syn: ["product expiry", "expiry date", "expiration date", "best before", "exp date", "shelf life", "bbd", "best before date"] },
    { label: "Note", col: "note_col", header: "note_header", syn: ["note", "notes", "remarks", "remark", "comment"] },
];

export class ExcelPreviewField extends Component {
    static template = "oe_sbs.ExcelPreviewField";
    static props = { ...standardFieldProps };

    setup() {
        this.gridRef = useRef("grid");
        this.fields = SBS_FIELDS;
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            error: null, sheets: [], active: 0, menu: null, fullscreen: false,
        });
        this.wb = null;
        onMounted(() => {
            // Delegate clicks: the grid HTML is injected manually, not OWL-managed
            this.gridRef.el.addEventListener("click", (ev) => this._onGridClick(ev));
            this._load();
        });
        onPatched(() => this._paint());
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    // --- loading -------------------------------------------------------
    async _load() {
        const rec = this.props.record;
        if (!rec.resId || !this.value) return;
        try {
            // Fetch real bytes (avoids the bin_size string -> atob problem)
            const url = `/web/content/${rec.resModel}/${rec.resId}/${this.props.name}`;
            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            this._parse(await resp.arrayBuffer());
        } catch (e) {
            this.state.error = String(e);
        }
    }

    async onFileChange(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) return;
        this.state.error = null;
        const buffer = await file.arrayBuffer();

        const XLSX = window.XLSX;
        if (!XLSX) { this.state.error = "SheetJS library not loaded."; return; }

        let wb;
        try {
            wb = XLSX.read(new Uint8Array(buffer), { type: "array" });
        } catch (e) {
            this.state.error = String(e);
            return;
        }

        // A template maps a single-sheet structure -> reject multi-sheet files
        if (wb.SheetNames.length > 1) {
            this.state.error =
                "This file has multiple sheets. Please split it into single-sheet files first.";
            if (ev.target) ev.target.value = "";
            return;
        }

        // Clear the previous mapping (it belonged to a different file)
        const reset = { header_row: 1, sheet_name: false };
        for (const f of SBS_FIELDS) {
            reset[f.col] = false;
            reset[f.header] = false;
        }
        reset[this.props.name] = this._arrayBufferToBase64(buffer);

        await this.props.record.update(reset);
        this._parse(buffer);
    }

    _parse(buffer) {
        const XLSX = window.XLSX;
        if (!XLSX) {
            this.state.error = "SheetJS library not loaded.";
            return;
        }
        this.wb = XLSX.read(new Uint8Array(buffer), { type: "array" });
        const configured = this.props.record.data.sheet_name;
        let active = 0;
        if (configured && this.wb.SheetNames.includes(configured)) {
            active = this.wb.SheetNames.indexOf(configured);
        }
        this._lastSig = null;
        this.state.sheets = this.wb.SheetNames;
        this.state.active = active;
    }

    selectSheet(i) {
        this.state.active = i;
    }

    toggleFullscreen() {
        this.state.fullscreen = !this.state.fullscreen;
    }

    // --- auto map (reuses server logic) --------------------------------
    async autoMap() {
        if (!this.wb) {
            this.state.error = "Please upload a file first.";
            return;
        }
        const XLSX = window.XLSX;
        const ws = this.wb.Sheets[this.wb.SheetNames[this.state.active]];
        if (!ws || !ws["!ref"]) return;
        const range = XLSX.utils.decode_range(ws["!ref"]);

        // Pull the live synonym dictionary from the server (approved only),
        // scoped to this template's supplier so the supplier's own synonyms take
        // priority over generic ones. Falls back to the built-in SBS_FIELDS lists.
        let synByCol = {};
        try {
            const sup = this.props.record.data.supplier_id;
            // Many2one in OWL form data is [id, name]; take the id.
            const supplierId = Array.isArray(sup) ? sup[0] : (sup || false);
            synByCol = await this.orm.call(
                "sbs.field.synonym", "get_automap_dict", [],
                { supplier_id: supplierId }
            );
        } catch (e) {
            synByCol = {};
        }
        const fieldsForMatch = SBS_FIELDS.map((f) => ({
            ...f,
            syn: (synByCol[f.col] && synByCol[f.col].length) ? synByCol[f.col] : (f.syn || []),
        }));

        // 1) Detect header row = row with the most synonym matches (first 15 rows)
        const scanTo = Math.min(range.e.r, range.s.r + 14);
        let bestRow = range.s.r, bestScore = -1;
        for (let r = range.s.r; r <= scanTo; r++) {
            let score = 0;
            for (let c = range.s.c; c <= range.e.c; c++) {
                const cell = ws[XLSX.utils.encode_cell({ r, c })];
                const norm = this._norm(cell ? (cell.w ?? cell.v) : "");
                if (norm && fieldsForMatch.some((f) => (f.syn || []).some((s) => this._synMatch(norm, s)))) {
                    score++;
                }
            }
            if (score > bestScore) { bestScore = score; bestRow = r; }
        }

        // 2) Map columns of the detected header row
        const update = { header_row: bestRow + 1 };
        const used = new Set();
        for (let c = range.s.c; c <= range.e.c; c++) {
            const cell = ws[XLSX.utils.encode_cell({ r: bestRow, c })];
            const text = cell ? String(cell.w ?? cell.v ?? "") : "";
            const norm = this._norm(text);
            if (!norm) continue;
            for (const f of fieldsForMatch) {
                if (used.has(f.col)) continue;
                if ((f.syn || []).some((s) => this._synMatch(norm, s))) {
                    update[f.col] = XLSX.utils.encode_col(c);
                    update[f.header] = text;
                    used.add(f.col);
                    break;
                }
            }
        }

        await this.props.record.update(update);
        this._lastSig = null;
        this.render(true);
    }

    _norm(s) {
        const out = String(s ?? "")
            .trim()
            .toLowerCase()
            .replace(/\s+/g, " ")
            .replace(/\s*\/\s*/g, "/");   // "case/ layer" -> "case/layer"
        // a real header is short; longer = sentence/note (e.g. an MOQ remark),
        // so don't let stray words inside it ('stock', 'qty') match as headers.
        return out.length > 40 ? "" : out;
    }
    _synMatch(norm, syn) {
        if (!norm) return false;
        // tighten slash spacing on BOTH sides so 'case/ layer' matches
        // 'case/layer' even if _norm somehow left a space in.
        const tight = (s) => String(s).replace(/\s*\/\s*/g, "/");
        norm = tight(norm);
        syn = tight(syn);
        if (norm === syn) return true;
        const esc = syn.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        // whole-word match avoids 't1' inside 'netherlands'
        return new RegExp("(^|[^a-z0-9])" + esc + "([^a-z0-9]|$)").test(norm);
    }

    // --- click to map --------------------------------------------------
    _onGridClick(ev) {
        const th = ev.target.closest(".o_xlsx_colhead");
        if (!th) return;
        const letter = th.dataset.col;
        this.state.menu = {
            letter,
            header: this._headerText(letter),
            x: ev.clientX,
            y: ev.clientY,
        };
    }

    async assignField(f) {
        const m = this.state.menu;
        if (!m) return;
        this.state.menu = null;
        const update = {};
        // free this column from any field currently pointing at it,
        // so picking a new field auto-replaces the old one (no manual Clear)
        for (const other of this.fields) {
            if (String(this.props.record.data[other.col] || "").toUpperCase() === m.letter) {
                update[other.col] = false;
                update[other.header] = false;
            }
        }
        // also free the chosen field if it was mapped to a different column
        // (a field should map to exactly one column)
        update[f.col] = m.letter;
        update[f.header] = m.header || false;
        await this.props.record.update(update);

        this._lastSig = null;
        this.render(true);
    }

    async clearColumn() {
        const m = this.state.menu;
        if (!m) return;
        this.state.menu = null;
        const update = {};
        for (const f of this.fields) {
            if (String(this.props.record.data[f.col] || "").toUpperCase() === m.letter) {
                update[f.col] = false;
                update[f.header] = false;
            }
        }
        if (Object.keys(update).length) {
            await this.props.record.update(update);
        }
        this._lastSig = null;
        this.render(true);
    }

    closeMenu() {
        this.state.menu = null;
    }

    _headerText(letter) {
        if (!this.wb) return "";
        const XLSX = window.XLSX;
        const ws = this.wb.Sheets[this.wb.SheetNames[this.state.active]];
        const r = (this.props.record.data.header_row || 1) - 1;
        const c = XLSX.utils.decode_col(letter);
        const cell = ws[XLSX.utils.encode_cell({ r, c })];
        return cell ? String(cell.w !== undefined ? cell.w : cell.v) : "";
    }

    // --- rendering -----------------------------------------------------
    _paint() {
        if (!this.wb || !this.gridRef.el) return;
        // Cache key includes the current mapping signature so the grid repaints
        // whenever a column is mapped/cleared (not just on sheet/file change).
        // Without the mapping in the key, clearing a column left its stale badge
        // on screen (and the next field's header could appear misaligned).
        const mapSig = this.fields
            .map((f) => `${f.col}=${this.props.record.data[f.col] || ""}`)
            .join("|");
        const sig = `${this.state.active}#${mapSig}`;
        if (this._lastSig === sig && this._lastWb === this.wb) return;
        this._lastSig = sig;
        this._lastWb = this.wb;

        const XLSX = window.XLSX;
        const ws = this.wb.Sheets[this.wb.SheetNames[this.state.active]];
        if (!ws || !ws["!ref"]) {
            this.gridRef.el.innerHTML = "<p class='text-muted'>(empty sheet)</p>";
            return;
        }

        const mapped = {};
        for (const f of this.fields) {
            const v = this.props.record.data[f.col];
            if (v) mapped[String(v).toUpperCase()] = f.label;
        }

        // Shared renderer (also used by the read-only document viewer).
        const { html } = buildGridHtml(XLSX, ws, {
            headerRow: this.props.record.data.header_row,
            mapped,
            maxRows: 51,          // preview first ~50 rows (unchanged)
            clickable: true,
        });
        this.gridRef.el.innerHTML = html;
    }

    // --- helpers -------------------------------------------------------
    _esc(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    _arrayBufferToBase64(buffer) {
        let binary = "";
        const bytes = new Uint8Array(buffer);
        const chunk = 0x8000;
        for (let i = 0; i < bytes.length; i += chunk) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
        }
        return btoa(binary);
    }
}

export const excelPreviewField = {
    component: ExcelPreviewField,
    supportedTypes: ["binary"],
};
registry.category("fields").add("excel_preview", excelPreviewField);