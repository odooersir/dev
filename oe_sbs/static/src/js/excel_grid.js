/** @odoo-module **/

/**
 * Shared SheetJS -> HTML grid renderer.
 *
 * Both the import-template mapper (excel_preview.js) and the read-only
 * document viewer (excel_viewer.js) render the same kind of grid, so the
 * markup lives here once. The mapper passes `mapped` + `clickable` to get
 * the click-to-map column headers and field badges; the viewer passes
 * neither and gets a plain, read-only sheet.
 */

export function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

/**
 * @param {object} XLSX      the SheetJS namespace (window.XLSX)
 * @param {object} ws        a SheetJS worksheet
 * @param {object} [opts]
 * @param {number} [opts.headerRow]  1-based row to highlight as the header
 * @param {object} [opts.mapped]     { "A": "Barcode", ... } -> column badges
 * @param {number} [opts.maxRows]    cap the number of rendered rows
 * @param {boolean} [opts.clickable] make column headers clickable
 * @returns {{html: string, totalRows: number, shownRows: number}}
 */
export function buildGridHtml(XLSX, ws, opts = {}) {
    const {
        headerRow = null,
        mapped = null,
        maxRows = 0,
        clickable = false,
    } = opts;

    if (!ws || !ws["!ref"]) {
        return { html: "<p class='text-muted'>(empty sheet)</p>", totalRows: 0, shownRows: 0 };
    }

    const range = XLSX.utils.decode_range(ws["!ref"]);
    const totalRows = range.e.r - range.s.r + 1;
    const lastRow = maxRows > 0
        ? Math.min(range.e.r, range.s.r + maxRows - 1)
        : range.e.r;

    // Merged cells: remember the span on the top-left cell and skip the rest.
    const covered = new Set();
    const spans = {};
    for (const m of ws["!merges"] || []) {
        spans[`${m.s.r}:${m.s.c}`] = {
            rowspan: m.e.r - m.s.r + 1,
            colspan: m.e.c - m.s.c + 1,
        };
        for (let r = m.s.r; r <= m.e.r; r++) {
            for (let c = m.s.c; c <= m.e.c; c++) {
                if (r !== m.s.r || c !== m.s.c) covered.add(`${r}:${c}`);
            }
        }
    }

    let html = '<table class="o_xlsx_grid"><thead><tr><th class="o_xlsx_corner"></th>';
    for (let c = range.s.c; c <= range.e.c; c++) {
        const letter = XLSX.utils.encode_col(c);
        if (clickable) {
            const badge = mapped && mapped[letter]
                ? `<div class="o_xlsx_badge">${escapeHtml(mapped[letter])}</div>`
                : "";
            html += `<th class="o_xlsx_colhead" data-col="${letter}" ` +
                    `title="Click to map this column">${letter}${badge}</th>`;
        } else {
            html += `<th class="o_xlsx_colhead_plain">${letter}</th>`;
        }
    }
    html += "</tr></thead><tbody>";

    for (let r = range.s.r; r <= lastRow; r++) {
        const num = r + 1;
        const rowCls = headerRow && num === headerRow ? ' class="o_xlsx_header_row"' : "";
        html += `<tr${rowCls}><th class="o_xlsx_rowhead">${num}</th>`;
        for (let c = range.s.c; c <= range.e.c; c++) {
            if (covered.has(`${r}:${c}`)) continue;
            const cell = ws[XLSX.utils.encode_cell({ r, c })];
            const sk = spans[`${r}:${c}`];
            const span = sk ? ` rowspan="${sk.rowspan}" colspan="${sk.colspan}"` : "";
            const numCls = cell && cell.t === "n" ? ' class="o_xlsx_num"' : "";
            let val = cell ? (cell.w !== undefined ? cell.w : cell.v) : "";
            if (val === undefined || val === null) val = "";
            html += `<td${span}${numCls}>${escapeHtml(String(val))}</td>`;
        }
        html += "</tr>";
    }
    html += "</tbody></table>";

    return { html, totalRows, shownRows: lastRow - range.s.r + 1 };
}
