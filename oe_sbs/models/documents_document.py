from odoo import models, api , fields, _
from odoo.exceptions import AccessError,UserError
import base64
import json
import logging
import io
import re
_logger = logging.getLogger(__name__)


XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _sbs_fix_xlsx_rels(xlsx_bytes):
    """
    Repair two openpyxl quirks that break split files:

    1. Worksheet relationship targets written as ABSOLUTE paths
       (Target="/xl/worksheets/sheet1.xml") - Excel/SheetJS reject these.
       We rewrite them to relative paths.

    2. Text stored as INLINE strings (t="inlineStr") with no sharedStrings.xml.
       Odoo's spreadsheet importer only reads shared strings, so an inline-only
       file opens with every text cell blank. We convert inline strings to a
       proper sharedStrings.xml table.

    Returns fixed bytes (or the input unchanged if it can't be processed).
    """
    import zipfile
    try:
        src = io.BytesIO(xlsx_bytes)
        with zipfile.ZipFile(src) as zin:
            names = zin.namelist()
            items = {n: zin.read(n) for n in names}
    except Exception:
        return xlsx_bytes  # not a zip / unreadable - leave as-is

    def fix_rels(text):
        text = re.sub(r'Target="/xl/', 'Target="', text)
        text = re.sub(r'Target="/', 'Target="', text)
        return text

    # --- pass 1: collect inline strings across all worksheets --------------
    shared = []
    shared_index = {}

    def _convert_sheet(sheet_xml):
        # Replace each inlineStr cell with a shared-string reference. The text is
        # taken verbatim from the source <t>...</t>, so it is ALREADY XML-encoded
        # (e.g. '&#163;' for '£'); we must NOT escape it again or entities would
        # double-encode into literal '&#163;' text.
        def repl(m):
            cell = m.group(0)
            tm = re.search(r'<t[^>]*>(.*?)</t>', cell, re.DOTALL)
            text = tm.group(1) if tm else ''
            if text not in shared_index:
                shared_index[text] = len(shared)
                shared.append(text)
            idx = shared_index[text]
            cell = re.sub(r't="inlineStr"', 't="s"', cell)
            cell = re.sub(r'<is>.*?</is>', '<v>%d</v>' % idx, cell, flags=re.DOTALL)
            return cell
        return re.sub(r'<c[^>]*t="inlineStr"[^>]*>.*?</c>', repl, sheet_xml,
                      flags=re.DOTALL)

    has_inline = False
    for name in list(items.keys()):
        if name.startswith('xl/worksheets/') and name.endswith('.xml'):
            txt = items[name].decode('utf-8', errors='replace')
            if 't="inlineStr"' in txt:
                has_inline = True
                items[name] = _convert_sheet(txt).encode('utf-8')

    # build sharedStrings.xml if we converted anything (text is already encoded)
    if has_inline:
        sst = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
               'count="%d" uniqueCount="%d">' % (len(shared), len(shared)))
        sst += ''.join('<si><t xml:space="preserve">%s</t></si>' % s
                       for s in shared)
        sst += '</sst>'
        items['xl/sharedStrings.xml'] = sst.encode('utf-8')

        # register the part in [Content_Types].xml and workbook rels
        ct_name = '[Content_Types].xml'
        if ct_name in items:
            ct = items[ct_name].decode('utf-8', errors='replace')
            if 'sharedStrings.xml' not in ct:
                ct = ct.replace('</Types>',
                    '<Override PartName="/xl/sharedStrings.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.'
                    'spreadsheetml.sharedStrings+xml"/></Types>')
                items[ct_name] = ct.encode('utf-8')
        wr_name = 'xl/_rels/workbook.xml.rels'
        if wr_name in items:
            wr = items[wr_name].decode('utf-8', errors='replace')
            if 'sharedStrings.xml' not in wr:
                # use a high rId to avoid clashing with existing ones
                existing = [int(x) for x in re.findall(r'Id="rId(\d+)"', wr)]
                nid = (max(existing) + 1) if existing else 1
                wr = wr.replace('</Relationships>',
                    '<Relationship '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/sharedStrings" Target="sharedStrings.xml" '
                    'Id="rId%d"/></Relationships>' % nid)
                items[wr_name] = wr.encode('utf-8')

    # --- pass 2: fix absolute rel paths -----------------------------------
    for name in list(items.keys()):
        if name.endswith('.rels'):
            items[name] = fix_rels(items[name].decode('utf-8', errors='replace')).encode('utf-8')

    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name, data in items.items():
            zout.writestr(name, data)
    return out.getvalue()



class Document(models.Model):
    _inherit = 'documents.document'
    _order = 'name, sequence, id desc'


    tag_ids = fields.Many2many('documents.tag', 'document_tag_rel', string="Tags", tracking=True)


    # --- SBS auto-split of multi-sheet files --------------------------
    sbs_origin_id = fields.Many2one('documents.document', string="Split From",
                                    index=True, copy=False)
    sbs_split_done = fields.Boolean(string="Sheets Split", default=False, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env.context.get('sbs_no_split'):
            return records
        for rec in records:
            # Only touch real, still-existing spreadsheet FILES. Creating an
            # Alias Domain (or other admin actions) can trigger create/recompute
            # cycles on folder or transient document rows that get rolled back;
            # calling split logic on those raised MissingError. Guard against it.
            if not rec.exists():
                continue
            # skip folders. A file document may carry its bytes via attachment_id
            # OR via raw (zip-extracted children are created with raw=...), so we
            # check for actual bytes rather than requiring attachment_id, which
            # would wrongly skip those children and stop them from splitting.
            if rec.type == 'folder':
                continue
            has_bytes = bool(rec.attachment_id) or bool(getattr(rec, 'raw', False))
            if not has_bytes:
                continue
            # ZIP archives: extract the spreadsheet files inside, each as its own
            # document, then stop - the zip itself is a parent (sbs_split_done)
            # and its extracted children run through convert/split on their own
            # create().
            name = (rec.name or '').lower()
            mime = rec.mimetype or ''
            # Archives (.zip / .rar): pull the spreadsheet files out, each as its
            # own document, then stop. The archive is kept as a parent.
            if (name.endswith(('.zip', '.rar'))
                    or 'zip' in mime or 'rar' in mime
                    or 'compressed' in mime):
                try:
                    if rec._sbs_extract_archive_if_needed():
                        continue   # handled as an archive; skip xls/split here
                except Exception:
                    _logger.exception("SBS archive extract failed for document %s", rec.id)
            try:
                rec._sbs_convert_xls_if_needed()
            except Exception:
                _logger.exception("SBS xls->xlsx convert failed for document %s", rec.id)
            try:
                rec._sbs_split_sheets_if_needed()
            except Exception:
                # Never let a bad file block the Documents upload
                _logger.exception("SBS auto-split failed for document %s", rec.id)
        return records

    def _sbs_get_file_bytes(self):
        data = False
        if self.attachment_id:
            data = self.attachment_id.raw
        if not data:
            data = getattr(self, 'raw', False)
        if not data and getattr(self, 'datas', False):
            data = base64.b64decode(self.datas)
        return data

    def _sbs_extract_archive_if_needed(self):
        """
        If this document is an archive (.zip or .rar), extract the SPREADSHEET
        files inside and create one child document per spreadsheet in the same
        folder. Non-spreadsheet entries (pdf, images, ...) are ignored - SBS only
        cares about spreadsheets. The archive is kept and flagged
        sbs_split_done=True so it acts as a parent and isn't re-processed. Each
        child runs through the normal create() hooks (xls->xlsx convert,
        sheet/price split) on its own.

        RAR needs the 'rarfile' python package plus a system 'unrar'/'unar' tool;
        if either is missing we log a clear warning and leave the .rar as-is
        rather than crashing the upload.
        Returns True if it handled an archive, False otherwise.
        """
        self.ensure_one()
        if self.sbs_split_done:
            return False
        data = self._sbs_get_file_bytes()
        if not data:
            return False

        name = (self.name or '').lower()
        mime = self.mimetype or ''
        is_rar = name.endswith('.rar') or 'rar' in mime

        # open the archive with the matching library, normalising to a common
        # interface: a list of (member_name, read_bytes_callable).
        members = []
        if is_rar:
            try:
                import rarfile
            except ImportError:
                _logger.warning(
                    "SBS: document %s is a .rar but the 'rarfile' package is not "
                    "installed - leaving it untouched.", self.id)
                return False
            # rarfile only invokes the external unrar/unar/bsdtar tool lazily (on
            # read), so a missing tool would otherwise blow up once per member.
            # Probe it once here and bail out cleanly with a clear message.
            try:
                rarfile.tool_setup()
            except Exception as e:
                _logger.warning(
                    "SBS: cannot extract .rar document %s - no working RAR tool "
                    "found (%s). Install 'unar' (apt-get install unar) or 'unrar' "
                    "on the Odoo server/container. Leaving the .rar untouched.",
                    self.id, e)
                return False
            try:
                rf = rarfile.RarFile(io.BytesIO(data))
            except Exception as e:
                # covers BadRarFile and other open-time problems
                _logger.warning(
                    "SBS: cannot open .rar document %s (%s).", self.id, e)
                return False
            archive, infolist = rf, rf.infolist()
            def _is_dir(i): return i.isdir()
            def _fname(i): return i.filename
        else:
            import zipfile
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                _logger.warning("SBS: document %s is not a valid zip", self.id)
                return False
            archive, infolist = zf, zf.infolist()
            def _is_dir(i): return i.is_dir()
            def _fname(i): return i.filename

        SPREADSHEET_EXT = ('.xlsx', '.xls', '.xlsb', '.xlsm', '.csv')
        made = 0
        with archive:
            for info in infolist:
                if _is_dir(info):
                    continue
                inner_name = _fname(info)
                if '__MACOSX' in inner_name:
                    continue                                    # macOS resource junk
                base = inner_name.replace('\\', '/').rsplit('/', 1)[-1]  # drop path
                if not base or base.startswith('.') or base.startswith('__'):
                    continue                                    # skip junk / hidden
                if not base.lower().endswith(SPREADSHEET_EXT):
                    continue                                    # spreadsheets only
                try:
                    inner_bytes = archive.read(info)
                except Exception:
                    _logger.exception("SBS: failed reading %s from archive %s",
                                      inner_name, self.id)
                    continue
                if not inner_bytes:
                    continue
                child_vals = {
                    'name': base,
                    'folder_id': self.folder_id.id,
                    'mimetype': XLSX_MIME if base.lower().endswith('.xlsx') else False,
                    'raw': inner_bytes,
                    'sbs_origin_id': self.id,
                }
                if 'owner_id' in self._fields and self.owner_id:
                    child_vals['owner_id'] = self.owner_id.id
                if 'partner_id' in self._fields and self.partner_id:
                    child_vals['partner_id'] = self.partner_id.id
                # child is created normally so its own create() hooks run
                # (convert / sheet-split / price-split).
                self.create(child_vals)
                made += 1

        # flag the archive as a handled parent so it isn't reprocessed
        self.sbs_split_done = True
        _logger.info("SBS: extracted %s spreadsheet(s) from %s archive %s",
                     made, 'rar' if is_rar else 'zip', self.id)
        return True

    @staticmethod
    def _sbs_looks_like_xls(data):
        """Legacy .xls (BIFF/OLE2) files start with the magic header D0 CF 11 E0."""
        return bool(data) and data[:4] == b'\xd0\xcf\x11\xe0'

    @staticmethod
    def _sbs_xls_bytes_to_xlsx(xls_bytes):
        """
        Convert legacy .xls (OLE2) bytes to .xlsx bytes in memory, preserving all
        sheets and converting date cells. Raises ImportError if xlrd is missing
        (callers decide how to surface that). Pure bytes-in / bytes-out so it can
        be reused by both the upload converter and the Create-Template action.
        """
        import xlrd
        from openpyxl import Workbook as _WB
        book = xlrd.open_workbook(file_contents=xls_bytes)
        wb = _WB()
        wb.remove(wb.active)
        for sheet_name in book.sheet_names():
            xs = book.sheet_by_name(sheet_name)
            ws = wb.create_sheet(title=str(sheet_name)[:31])
            for r in range(xs.nrows):
                for c in range(xs.ncols):
                    cell = xs.cell(r, c)
                    value = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            value = xlrd.xldate_as_datetime(value, book.datemode)
                        except Exception:
                            pass
                    ws.cell(row=r + 1, column=c + 1, value=value)
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    @staticmethod
    def _sbs_csv_bytes_to_xlsx(csv_bytes):
        """Convert CSV bytes to a single-sheet .xlsx. Sniffs the delimiter and
        decodes utf-8 (falling back to latin-1)."""
        import csv as _csv
        from openpyxl import Workbook as _WB
        try:
            text = csv_bytes.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = csv_bytes.decode('latin-1', errors='replace')
        sample = text[:4096]
        try:
            dialect = _csv.Sniffer().sniff(sample, delimiters=',;\t|')
        except Exception:
            class _D(_csv.Dialect):
                delimiter = ','; quotechar = '"'; doublequote = True
                skipinitialspace = False; lineterminator = '\r\n'
                quoting = _csv.QUOTE_MINIMAL
            dialect = _D()
        wb = _WB()
        ws = wb.active
        ws.title = 'Sheet1'
        reader = _csv.reader(io.StringIO(text), dialect)
        for row in reader:
            ws.append(row)
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    @staticmethod
    def _sbs_xlsb_bytes_to_xlsx(xlsb_bytes):
        """Convert .xlsb (binary) bytes to .xlsx using pyxlsb to read."""
        import pyxlsb
        from openpyxl import Workbook as _WB
        wb = _WB()
        wb.remove(wb.active)
        with pyxlsb.open_workbook(io.BytesIO(xlsb_bytes)) as book:
            for sheet_name in book.sheets:
                ws = wb.create_sheet(title=str(sheet_name)[:31])
                with book.get_sheet(sheet_name) as sheet:
                    for row in sheet.rows():
                        ws.append([c.v for c in row])
        if not wb.sheetnames:
            wb.create_sheet(title='Sheet1')
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    @staticmethod
    def _sbs_xlsm_bytes_to_xlsx(xlsm_bytes):
        """Convert .xlsm (macro-enabled) to plain .xlsx by re-saving without VBA."""
        from openpyxl import load_workbook as _load
        wb = _load(io.BytesIO(xlsm_bytes), data_only=True)
        try:
            wb.vba_archive = None     # drop macros so it saves as .xlsx
        except Exception:
            pass
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    def _sbs_detect_spreadsheet_kind(self, data):
        """
        Return one of 'xls', 'xlsb', 'xlsm', 'csv', 'xlsx', or None based on the
        file name, mimetype and content. xlsx needs no conversion.
        """
        name = (self.name or '').lower()
        mime = self.mimetype or ''
        # content signatures
        if self._sbs_looks_like_xls(data):
            return 'xls'                       # OLE2 (could be .xls)
        is_zip = bool(data) and data[:2] == b'PK'   # xlsx/xlsm/xlsb are zip-based
        if name.endswith('.xlsb') or 'spreadsheetml.binary' in mime:
            return 'xlsb'
        if name.endswith('.xlsm') or 'spreadsheetml.sheet.macroEnabled' in mime:
            return 'xlsm'
        if name.endswith('.xlsx'):
            return 'xlsx'
        if name.endswith('.csv') or mime in ('text/csv', 'application/csv'):
            return 'csv'
        if name.endswith('.xls') or mime in ('application/vnd.ms-excel', 'application/excel'):
            return 'xls'
        # content-based last resort
        if is_zip:
            return 'xlsx'                       # assume already-fine xlsx
        return None

    def _sbs_convert_xls_if_needed(self):
        """
        If this document is a non-xlsx spreadsheet (.xls/.xlsb/.xlsm/.csv),
        convert it to .xlsx in place so the rest of the pipeline (preview, split,
        import) only ever deals with xlsx. Missing optional libraries (xlrd for
        .xls, pyxlsb for .xlsb) are tolerated: the file is left as-is and a clear
        error surfaces later at import time.
        """
        self.ensure_one()
        if self.sbs_origin_id:
            return  # split children are already xlsx
        data = self._sbs_get_file_bytes()
        if not data:
            return
        kind = self._sbs_detect_spreadsheet_kind(data)
        if kind in (None, 'xlsx'):
            return  # already xlsx or not a spreadsheet -> nothing to do

        converters = {
            'xls':  self._sbs_xls_bytes_to_xlsx,
            'xlsb': self._sbs_xlsb_bytes_to_xlsx,
            'xlsm': self._sbs_xlsm_bytes_to_xlsx,
            'csv':  self._sbs_csv_bytes_to_xlsx,
        }
        try:
            xlsx_bytes = converters[kind](data)
        except ImportError as e:
            # optional reader lib missing (xlrd / pyxlsb): keep the upload intact
            _logger.warning("[SBS] cannot convert %s '%s' (%s); leaving as-is.",
                            kind, self.name, e)
            return
        except Exception:
            _logger.exception("[SBS] %s->xlsx conversion failed for '%s'.",
                              kind, self.name)
            return

        new_name = self.name or 'Document'
        for ext in ('.xls', '.xlsb', '.xlsm', '.csv', '.xlsx'):
            if new_name.lower().endswith(ext):
                new_name = new_name[:-len(ext)]
                break
        new_name += '.xlsx'

        self.with_context(sbs_no_split=True).write({
            'raw': xlsx_bytes,
            'mimetype': XLSX_MIME,
            'name': new_name,
        })

    @staticmethod
    def _sbs_sheet_has_data(ws):
        for row in ws.iter_rows(values_only=True):
            if any(c not in (None, '') for c in row):
                return True
        return False

    # =================================================================
    # Price-column detection & split
    # =================================================================
    @staticmethod
    def _sbs_guess_header_row(ws, max_scan_rows=15):
        """
        Guess the header row: the row (within the first max_scan_rows) with the
        most non-empty SHORT text cells - headers are short labels, data rows
        mix numbers/currency, and title/address rows have only one or two cells.
        Falls back to row 1. Mirrors the scan used elsewhere so the price-column
        detector lines up with the real header.
        """
        best_row, best_score = 1, -1
        max_col = ws.max_column or 1
        for r in range(1, min(max_scan_rows, (ws.max_row or 1)) + 1):
            short_text = 0
            for c in range(1, max_col + 1):
                v = ws.cell(row=r, column=c).value
                if v is None:
                    continue
                s = str(v).strip()
                # a header cell is short and not purely numeric
                if s and len(s) <= 40 and not re.fullmatch(r'[\d.,$€£%\-\s]+', s):
                    short_text += 1
            if short_text > best_score:
                best_score, best_row = short_text, r
        return best_row

    @staticmethod
    def _sbs_detect_price_columns(ws, header_row=1, max_scan_rows=20):
        """
        Detect price-like columns automatically by content.
        A column qualifies only if EITHER:
          (a) most data cells carry an explicit currency symbol/code, OR
          (b) the header contains a price/MOQ keyword AND cells are decimals.
        Weight/volume columns (plain decimals, no currency, no price header)
        are deliberately excluded to avoid false positives.
        Returns list of (col_idx_0_based, header_text).
        """
        headers = [ws.cell(row=header_row, column=c).value
                   for c in range(1, ws.max_column + 1)]
        n_cols = len(headers)

        data_rows = []
        for r in range(header_row + 1, min(header_row + 1 + max_scan_rows, ws.max_row + 1)):
            row = [ws.cell(row=r, column=c).value for c in range(1, n_cols + 1)]
            if any(v not in (None, '') for v in row):
                data_rows.append(row)
        if not data_rows:
            return []

        CUR = r'(€|\$|£|aed|\beur\b|\busd\b|\bgbp\b|\bdirham\b)'
        # NOTE: 'mov'/'moq' are metadata labels, NOT price headers - a cell like
        # 'MOV' sitting above a value must never be treated as a price column.
        PRICE_HDR = r'(price|prix|cost|plt|pallet|tariff|rate|offer|exw)'
        # Headers that look monetary but are computed totals, not unit prices.
        NON_PRICE_HDR = r'(total|subtotal|sum|amount|value|grand|qty|quantity|'\
                        r'order\s*qty|#\s*carton|cartons?\b)'
        # A header that IS exactly a metadata label (MOV/MOQ/MOA/Incoterm/...) or
        # a bare number is not a price column - it's a stray metadata cell that
        # ended up on the scanned row (e.g. wrong header row).
        META_LABEL = re.compile(
            r'^\s*(mov|moq|moa|incoterms?|currency|lead\s*time|leadtime|'
            r'payment(\s*terms?)?|origin|coo)\s*$', re.IGNORECASE)
        BARE_NUMBER = re.compile(r'^[\d.,\s]+$')

        def has_currency(v):
            if v is None or str(v).strip() == '':
                return None
            return bool(re.search(CUR, str(v), re.IGNORECASE))

        def is_decimal(v):
            if v is None or str(v).strip() == '':
                return None
            num = re.sub(r'[^\d,.\-]', '', str(v))
            return bool(re.search(r'\d[.,]\d', num))

        def is_zeroish(v):
            # treat '€ 0.00', '0', '' as non-informative (computed/empty column)
            if v is None or str(v).strip() == '':
                return True
            num = re.sub(r'[^\d.\-]', '', str(v))
            try:
                return float(num) == 0.0 if num else True
            except ValueError:
                return False

        price_cols = []
        for ci in range(n_cols):
            hdr = str(headers[ci]).strip() if headers[ci] else ''
            # a price column MUST have a header - a headerless column can't carry
            # its condition (currency/MOV/incoterm) into the split file, so skip.
            if not hdr:
                continue
            # skip obvious computed/total columns even if they carry a currency
            if re.search(NON_PRICE_HDR, hdr, re.IGNORECASE):
                continue
            # skip a header that is itself a metadata label ('MOV', 'MOQ', ...)
            # or a bare number ('5000') - these are stray metadata cells, not a
            # price column (happens when the header row is mis-detected).
            if META_LABEL.match(hdr) or BARE_NUMBER.match(hdr):
                continue
            vals = [row[ci] for row in data_rows if ci < len(row)]
            # a real price column has some non-zero values; a 'Total Value'
            # column that is all 0.00 (to be filled on order) is not a price.
            non_zero = [v for v in vals if not is_zeroish(v)]
            if not non_zero:
                continue
            cur_judged = [j for j in (has_currency(v) for v in vals) if j is not None]
            dec_judged = [j for j in (is_decimal(v) for v in vals) if j is not None]
            if not cur_judged and not dec_judged:
                continue
            cur_ratio = sum(cur_judged) / len(cur_judged) if cur_judged else 0
            hdr_is_price = bool(re.search(PRICE_HDR, hdr, re.IGNORECASE))
            dec_ratio = sum(dec_judged) / len(dec_judged) if dec_judged else 0
            if cur_ratio >= 0.6 or (hdr_is_price and dec_ratio >= 0.6):
                price_cols.append((ci, hdr or "Col%d" % (ci + 1)))
        return price_cols

    @staticmethod
    def _sbs_detect_column_blocks(ws, header_row=1, max_blocks=8):
        """
        Detect several INDEPENDENT product tables laid out SIDE BY SIDE on one
        sheet: the same header sequence repeated across the header row, e.g.
        'Reference|EAN|Description|Price' in A-D and again in F-I.

        This is a different shape from the one the price-column split handles.
        There, a single product list is priced under several conditions, so the
        identifier columns appear once and only the price header repeats -
        keeping all non-price columns is correct. Here every block owns its own
        Reference/EAN/Description, so dropping the other price column leaves the
        child pairing one block's price with ANOTHER block's barcodes.

        Returns [(start_col0, end_col0), ...] with at least two blocks, or []
        when the sheet is not laid out this way.
        """
        n_cols = ws.max_column or 1
        labels = []
        for c in range(1, n_cols + 1):
            v = ws.cell(row=header_row, column=c).value
            labels.append(re.sub(r'\s+', ' ', str(v).strip().lower())
                          if v not in (None, '') else '')
        filled = [i for i, lb in enumerate(labels) if lb]
        if len(filled) < 4:
            return []

        first = labels[filled[0]]
        starts = [i for i in filled if labels[i] == first]
        if not 2 <= len(starts) <= max_blocks:
            return []

        bounds = []
        for n, st in enumerate(starts):
            end = (starts[n + 1] - 1) if n + 1 < len(starts) else n_cols - 1
            bounds.append((st, end))

        # Every block must repeat the SAME header sequence. Without this guard a
        # label that merely happens to occur twice ('Price' in a single table
        # priced twice) would be mistaken for a block boundary.
        sigs = [tuple(lb for lb in labels[a:b + 1] if lb) for a, b in bounds]
        if len(set(sigs)) != 1 or len(sigs[0]) < 3:
            return []
        return bounds

    def _sbs_split_column_blocks(self, data, header_row, blocks):
        """
        One child document per side-by-side table. Each child keeps ONLY its own
        block's columns, so the block lands on the same columns the template
        maps and its identifiers stay with its prices.

        Everything ABOVE the header row is file-level metadata (lead time, MOQ,
        T1/T2, incoterm, brand) and usually sits in the first block's columns,
        so it is rescued before the deletion and re-stamped onto every child.
        """
        from openpyxl import load_workbook

        base = self.name or 'Document'
        if base.lower().endswith('.xlsx'):
            base = base.rsplit('.', 1)[0]

        probe = load_workbook(io.BytesIO(data), data_only=True)
        pw = probe[probe.sheetnames[0]]
        rescued = []
        for r in range(1, header_row):
            for c in range(1, (pw.max_column or 1) + 1):
                v = pw.cell(row=r, column=c).value
                if v in (None, ''):
                    continue
                text = str(v).strip()
                if text and text not in rescued:
                    rescued.append(text)
        probe.close()

        for n, (start_c0, end_c0) in enumerate(blocks, start=1):
            wbk = load_workbook(io.BytesIO(data))
            w = wbk[wbk.sheetnames[0]]
            self._sbs_unmerge_fill_ws(w, header_row)
            # drop every column outside this block, right to left so the
            # remaining indices stay valid
            keep = set(range(start_c0 + 1, end_c0 + 2))          # 1-based
            for c in range(w.max_column or 1, 0, -1):
                if c not in keep:
                    w.delete_cols(c)

            # re-stamp the file-level metadata that the deletion may have taken
            # with it, in a spare column to the right so it still reads as
            # metadata sitting outside the mapped table
            if rescued:
                stamp_col = (w.max_column or 1) + 2
                for i, text in enumerate(rescued):
                    w.cell(row=i + 1, column=stamp_col, value=text)

            out = io.BytesIO()
            wbk.save(out)

            child_vals = {
                'name': "%s - Table %d.xlsx" % (base, n),
                'folder_id': self.folder_id.id,
                'mimetype': XLSX_MIME,
                'raw': _sbs_fix_xlsx_rels(out.getvalue()),
                'sbs_origin_id': self.id,
            }
            if 'owner_id' in self._fields and self.owner_id:
                child_vals['owner_id'] = self.owner_id.id
            if 'partner_id' in self._fields and self.partner_id:
                child_vals['partner_id'] = self.partner_id.id

            child = self.with_context(sbs_no_split=True).create(child_vals)
            # a block may still be priced in several currencies/incoterms
            try:
                child._sbs_split_price_columns_if_needed()
            except Exception:
                _logger.exception(
                    "SBS price-column split failed for block child %s", child.id)

        self.sbs_split_done = True
        _logger.info("[SBS] split %s into %s side-by-side tables.",
                     self.name, len(blocks))
        return True

    @staticmethod
    def _sbs_parse_price_header(header):
        """
        Extract the 'condition' a price column represents from its header text,
        so it can travel with the split file into the SBS record. Handles:
          currency  - '$'/'€'/'£'/'AED' or the words USD/EUR/GBP  -> code
          incoterm  - EXW/FOB/CIF/... (whole word)
          mov       - a large monetary figure, e.g. '€100,000 - ...' -> 100000
          moq       - count + unit, e.g. 'MOQ 5 PLT' -> (5, 'plt')
        Returns a dict with any of: currency, incoterm, mov, moq, moq_unit.
        Examples:
          'EXW UK  £'                 -> {'currency':'GBP','incoterm':'EXW'}
          '€100,000 - €249,999 2.5%'  -> {'currency':'EUR','mov':100000}
          'MOQ 5 PLT'                 -> {'moq':5,'moq_unit':'plt'}
        """
        h = str(header or '').strip()
        meta = {}
        if re.search(r'£|\bgbp\b|\bpound', h, re.I):
            meta['currency'] = 'GBP'
        elif re.search(r'€|\beur|\beuro', h, re.I):
            meta['currency'] = 'EUR'
        elif re.search(r'\$|\busd\b|\bdollar', h, re.I):
            meta['currency'] = 'USD'
        elif re.search(r'\baed\b|\bdirham', h, re.I):
            meta['currency'] = 'AED'

        m = re.search(r'\b(EXW|FOB|CIF|CFR|FCA|DAP|DDP|CPT|CIP|FAS)\b', h, re.I)
        if m:
            meta['incoterm'] = m.group(1).upper()
            # Origin/place usually follows the incoterm, e.g. 'EXW UK', 'FOB USA',
            # 'EXW Rotterdam'. Grab the word(s) right after it, up to a currency
            # symbol or price keyword, so 'UNIT PRICE £ EXW UK' -> origin 'UK'.
            after = h[m.end():]
            # Unicode-aware: place names may carry non-ASCII letters (e.g. the
            # Polish 'ŚWIDNIK'), so match on any letters, not just A-Za-z.
            om = re.match(
                r'[\s:\-]*((?![\d])[^\W\d_][^\W\d_ .]*(?:[ .][^\W\d_][^\W\d_ .]*){0,4}?)'
                r'(?=\s*(?:£|\$|€|\bunit\b|\bprice\b|\bper\b|\bcost\b|[,()/]|$))',
                after, re.IGNORECASE | re.UNICODE)
            if om:
                origin = om.group(1).strip(' .-')
                # drop a trailing currency word ('UK EUROS' -> 'UK', 'UK £' handled
                # by the lookahead) and reject a pure currency token as origin.
                origin = re.sub(
                    r'\s+(euros?|gbp|usd|eur|aed|pounds?|dollars?)\s*$', '',
                    origin, flags=re.I).strip()
                if origin and origin.lower() not in (
                        'gbp', 'usd', 'eur', 'aed', 'euros', 'euro', 'pounds',
                        'pound', 'dollars', 'dollar'):
                    meta['origin'] = origin

        # MOV: first large money figure next to a currency symbol
        mov_m = re.search(r'(?:€|\$|£)\s*([\d][\d,]{3,})', h)
        if mov_m:
            num = int(re.sub(r'[^\d]', '', mov_m.group(1)))
            if num >= 1000:
                meta['mov'] = num

        # MOQ: count + pallet/case/carton unit
        moq_m = re.search(r'\b(\d+)\s*(plt|pallets?|cases?|ctn|cartons?)\b', h, re.I)
        if moq_m:
            meta['moq'] = int(moq_m.group(1))
            meta['moq_unit'] = moq_m.group(2).lower()
        return meta

    @staticmethod
    def _sbs_unmerge_fill_ws(ws, header_row=1):
        """
        Unmerge every merged range in the sheet's DATA area (at/below header_row)
        and copy the top-left value into each covered cell, so merged prices/qty
        (e.g. one price spanning several product rows) become per-row values.
        Merges entirely ABOVE the header (titles/metadata banners) are left as-is.
        """
        try:
            ranges = list(ws.merged_cells.ranges)
        except Exception:
            return
        for mr in ranges:
            try:
                min_col, min_row, max_col, max_row = (
                    mr.min_col, mr.min_row, mr.max_col, mr.max_row)
                if max_row < header_row:
                    continue
                top_left = ws.cell(row=min_row, column=min_col).value
                ws.unmerge_cells(str(mr))
                if top_left is None:
                    continue
                for r in range(min_row, max_row + 1):
                    for c in range(min_col, max_col + 1):
                        if r == min_row and c == min_col:
                            continue
                        ws.cell(row=r, column=c).value = top_left
            except Exception:
                continue

    def _sbs_split_price_columns_if_needed(self):
        """
        If the (single) data sheet has more than one price column, create one
        child document per price column (each keeping all non-price columns +
        exactly one price column). Mirrors the multi-sheet split flow.
        Returns True if a split happened.
        """
        self.ensure_one()
        name = (self.name or '').lower()
        if self.mimetype != XLSX_MIME and not name.endswith('.xlsx'):
            return False

        data = self._sbs_get_file_bytes()
        if not data:
            return False
        # NOTE: unlike sheet-split, we do NOT bail out on sbs_origin_id here.
        # A sheet-split child legitimately carries sbs_origin_id and still needs
        # its price columns split. Only sbs_split_done means "already handled".
        if self.sbs_split_done:
            return False

        from openpyxl import load_workbook

        probe = load_workbook(io.BytesIO(data), data_only=True)
        # only single-sheet files reach here (multi-sheet already split earlier)
        if len(probe.sheetnames) != 1:
            return False
        ws = probe[probe.sheetnames[0]]

        # header row: use the template hint if set; otherwise auto-detect the
        # row that looks most like a header (the first row whose cells are mostly
        # short text labels), so files like Mamado (header on row 4) work too.
        header_row = 1
        if self.template_id and getattr(self.template_id, 'header_row', False):
            header_row = int(self.template_id.header_row or 1)
        else:
            header_row = self._sbs_guess_header_row(ws)

        # merged price/qty cells (one value spanning several product rows) would
        # otherwise read as blank on all but the first row - unmerge & fill so
        # detection and the split children carry a value on every row.
        self._sbs_unmerge_fill_ws(ws, header_row)

        # Side-by-side tables first: when each price column belongs to its OWN
        # product block, splitting by price column would keep every child on the
        # FIRST block's identifier columns and pair the wrong barcodes with the
        # wrong prices. Block-splitting is the correct shape for that layout.
        blocks = self._sbs_detect_column_blocks(ws, header_row)
        if len(blocks) > 1:
            return self._sbs_split_column_blocks(data, header_row, blocks)

        price_cols = self._sbs_detect_price_columns(ws, header_row)
        if len(price_cols) <= 1:
            return False  # nothing to split

        base = self.name or 'Document'
        if base.lower().endswith('.xlsx'):
            base = base.rsplit('.', 1)[0]

        price_idxs = {ci for ci, _ in price_cols}

        # Rescue any metadata that lives ABOVE the header row (e.g. 'MOV' in H1
        # with '5000' in I1). Such label/value pairs often sit over a price
        # column, so deleting that column would wipe the value. We read those
        # rows once, pair adjacent label:value cells, and re-stamp them onto every
        # split file so no file loses the file-level condition.
        rescued = []                       # list of "Label: Value" strings
        KNOWN = ('mov', 'moq', 'incoterm', 'incoterms', 'currency', 'lead time',
                 'leadtime', 'payment', 'origin')
        for r in range(1, header_row):     # rows strictly above the header
            row_cells = [ws.cell(row=r, column=c).value
                         for c in range(1, (ws.max_column or 1) + 1)]
            for idx, val in enumerate(row_cells):
                if val is None:
                    continue
                text = str(val).strip()
                low = text.lower()
                # 'MOV: 5000' style already-complete cell
                if ':' in text and any(k in low for k in KNOWN):
                    rescued.append(text)
                    continue
                # 'MOV' label in one cell, value in the next non-empty cell
                if low in KNOWN or any(low == k for k in KNOWN):
                    nxt = next((row_cells[j] for j in range(idx + 1, len(row_cells))
                                if row_cells[j] not in (None, '')), None)
                    if nxt is not None:
                        rescued.append("%s: %s" % (text, str(nxt).strip()))

        for keep_ci, label in price_cols:
            wbk = load_workbook(io.BytesIO(data))   # fresh copy (deletion is destructive)
            w = wbk[wbk.sheetnames[0]]
            # same unmerge on the copy we actually save, so the child file keeps a
            # price on every row (not just the merge's top-left row).
            self._sbs_unmerge_fill_ws(w, header_row)
            # delete the other price columns (right-to-left so indices stay valid)
            to_delete = sorted([ci for ci in price_idxs if ci != keep_ci], reverse=True)
            for ci in to_delete:
                w.delete_cols(ci + 1)           # openpyxl is 1-based

            # --- stamp the column's condition as metadata cells --------------
            # Parse the kept price header (e.g. 'EXW UK £', '€100,000 - ...') and
            # write 'Label: Value' cells the import scanner already understands
            # (MOV/MOQ/Incoterm anchors), so the split file carries its own
            # currency/MOV/MOQ/incoterm into the SBS record. We place them in a
            # spare column to the RIGHT of the data (a few rows down) rather than
            # inserting rows, so the header row position is preserved and the
            # cells still fall outside the mapped table (=> read as metadata).
            meta = self._sbs_parse_price_header(label)
            stamp = []
            if meta.get('mov'):
                stamp.append("MOV: %d" % meta['mov'])
            if meta.get('moq'):
                unit = meta.get('moq_unit', '')
                stamp.append(("MOQ: %d %s" % (meta['moq'], unit)).strip())
            if meta.get('incoterm'):
                # append the origin/place so the import's standardize_incoterm
                # can resolve it, e.g. 'Incoterm: EXW UK' -> 'EXW: United Kingdom'
                inc = meta['incoterm']
                if meta.get('origin'):
                    inc = "%s %s" % (inc, meta['origin'])
                stamp.append("Incoterm: %s" % inc)
            if meta.get('currency'):
                stamp.append("Currency: %s" % meta['currency'])
            # add rescued above-header metadata (e.g. 'MOV: 5000') unless the
            # header already produced a value of the same kind.
            have_keys = {s.split(':', 1)[0].strip().lower() for s in stamp}
            for text in rescued:
                key = text.split(':', 1)[0].strip().lower()
                if key not in have_keys:
                    stamp.append(text)
                    have_keys.add(key)
            if stamp:
                stamp_col = (w.max_column or 1) + 2   # gap column, then metadata
                for i, text in enumerate(stamp):
                    w.cell(row=i + 1, column=stamp_col, value=text)

            out = io.BytesIO()
            wbk.save(out)

            safe_label = re.sub(r'[\\/:*?"<>|]', '_', str(label)).strip() or 'Price'
            child_vals = {
                'name': "%s - %s.xlsx" % (base, safe_label),
                'folder_id': self.folder_id.id,
                'mimetype': XLSX_MIME,
                'raw': _sbs_fix_xlsx_rels(out.getvalue()),
                'sbs_origin_id': self.id,
            }
            if 'owner_id' in self._fields and self.owner_id:
                child_vals['owner_id'] = self.owner_id.id
            if 'partner_id' in self._fields and self.partner_id:
                child_vals['partner_id'] = self.partner_id.id

            self.with_context(sbs_no_split=True).create(child_vals)

        self.sbs_split_done = True
        return True

    def _sbs_split_sheets_if_needed(self):
        self.ensure_one()
        # Only real .xlsx (openpyxl can't write .xls / native spreadsheets)
        name = (self.name or '').lower()
        if self.mimetype != XLSX_MIME and not name.endswith('.xlsx'):
            return
        # NOTE: don't bail out on sbs_origin_id here. A zip-extracted child DOES
        # carry sbs_origin_id (its origin is the zip) yet still needs sheet/price
        # splitting. Only sbs_split_done means "already handled". A real sheet-
        # split child is single-sheet, so it just falls through to price-split
        # without recursing.
        if self.sbs_split_done:
            return

        data = self._sbs_get_file_bytes()
        if not data:
            return

        from openpyxl import load_workbook

        # 1) Which sheets actually contain data
        probe = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        data_sheets = [s for s in probe.sheetnames if self._sbs_sheet_has_data(probe[s])]
        probe.close()
        if len(data_sheets) <= 1:
            # Single data sheet -> no sheet split, but it may still have
            # multiple price columns that need their own split.
            self._sbs_split_price_columns_if_needed()
            return

        base = self.name or 'Document'
        if base.lower().endswith('.xlsx'):
            base = base.rsplit('.', 1)[0]

        # 2) One single-sheet .xlsx document per data sheet, in the SAME folder
        for sheet in data_sheets:
            wbk = load_workbook(io.BytesIO(data))   # fresh copy (deletion is destructive)
            for s in list(wbk.sheetnames):
                if s != sheet:
                    del wbk[s]
            out = io.BytesIO()
            wbk.save(out)

            child_vals = {
                'name': "%s - %s.xlsx" % (base, sheet),
                'folder_id': self.folder_id.id,
                'mimetype': XLSX_MIME,
                'raw': _sbs_fix_xlsx_rels(out.getvalue()),
                'sbs_origin_id': self.id,
            }
            if 'owner_id' in self._fields and self.owner_id:
                child_vals['owner_id'] = self.owner_id.id
            if 'partner_id' in self._fields and self.partner_id:
                child_vals['partner_id'] = self.partner_id.id

            # Each single-sheet child is created with sheet-split off,
            # but still gets a chance to be split by price columns.
            child = self.with_context(sbs_no_split=True).create(child_vals)
            try:
                child._sbs_split_price_columns_if_needed()
            except Exception:
                _logger.exception("SBS price-column split failed for document %s", child.id)

        # 3) Flag the original so it isn't reused as a multi-sheet source
        self.sbs_split_done = True
        # If you prefer to hide the original entirely, archive it instead:
        # self.active = False

    DOCUMENT_STATE = [
        ('draft', "Draft"),
        ('approve', "Approve"),
         ('sent_to_sbs', "Manually Sent"),
        ('auto_sent_to_sbs', "Auto Sent"),
        ('deleted_from_sbs', "Deleted From SBS"),
        ('auto_deleted', "Auto Deleted"),
        ('no_template', "Waiting For Mapping"),
        ('reject', "Reject"),

    ]

    state = fields.Selection(
        selection=DOCUMENT_STATE,
        string="SBS Status",
        readonly=True, copy=False, index=True,
        tracking=True,
        default='draft')

    import_number = fields.Char(string='IN',help='Import Number',copy=False,  default=False)
    old_import_number = fields.Char(string='OIN',help='Old Import Number',copy=False,  default=False)

    def action_open_template(self):
        """Open the form of the Import Mapping (template) linked to this doc."""
        self.ensure_one()
        if not self.template_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _("Import Mapping"),
            'res_model': 'sbs.import.template',
            'res_id': self.template_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_view_sbs_records(self):
        """Open the SBS rows imported from this document (by IN), with a
        REMOVABLE default filter so clearing it returns to the full list."""
        self.ensure_one()
        ctx = dict(self.env.context)
        if self.import_number:
            ctx['search_default_import_number'] = self.import_number
        else:
            ctx['search_default_document_id'] = self.id
        return {
            'type': 'ir.actions.act_window',
            'name': _("SBS Records - %s") % (self.import_number or self.name or ''),
            'res_model': 'sbs.data',
            'view_mode': 'list,form',
            'target': 'current',
            'context': ctx,
        }


    is_tag_editor = fields.Boolean(compute='_compute_is_tag_editor')

    modifier=  fields.Many2one('res.users', string="Modifier")

    # <field name="state" widget="statusbar" statusbar_visible="draft,approve,reject"/>

    template_id = fields.Many2one('sbs.import.template', string='Import Template', help='Template used', readonly=True)

    rejection_reason = fields.Char()

    # The compute does not get triggered without a depends on record creation
    # aka keep the 'useless' depends
    @api.depends_context('uid')
    @api.depends('tag_ids')
    def _compute_is_tag_editor(self):
        self.is_tag_editor = self.env.user.has_group("oe_sbs.group_tag_editor")

    # ---------------------------------------------------------------------
    # Email intake: route incoming supplier files to the right folder
    # ---------------------------------------------------------------------
    def _sbs_supplier_from_folder(self):
        """
        Resolve the supplier (res.partner) for this document from its folder.
        Prefers the folder's own 'Contact' (partner_id) field - a direct, exact
        link - and only falls back to matching the folder NAME against partner
        names when the folder has no contact set (backward compatible).
        Returns a res.partner recordset (possibly empty).
        """
        self.ensure_one()
        folder = self.folder_id
        if not folder:
            return self.env['res.partner'].browse()
        # 1) exact link via the folder's Contact field
        if folder.partner_id:
            return folder.partner_id
        # 2) fallback: match the folder name against partner names
        if folder.name:
            return self.env['res.partner'].sudo().search(
                [('name', 'ilike', folder.name)], limit=1)
        return self.env['res.partner'].browse()

    @api.model
    def _sbs_folder_for_sender(self, sender_email):
        """
        Resolve the destination folder for an incoming email, from the SENDER's
        exact email address:
          1. find the res.partner whose email matches sender_email exactly
          2. find that supplier's sub-folder under 'SBS Files' - by the folder's
             Contact (partner_id) first, then by folder name as a fallback
        Returns the folder document, or the 'Unmatched' folder when the supplier
        or its folder can't be found. Returns False only if even 'Unmatched'
        is missing (folders are expected to pre-exist).
        """
        Doc = self.sudo()

        def _find_folder(name, parent=None):
            domain = [('name', '=', name)]
            if parent is not None:
                domain.append(('folder_id', '=', parent.id))
            return Doc.search(domain, limit=1)

        parent = _find_folder('SBS Files')
        unmatched = _find_folder('Unmatched', parent) or _find_folder('Unmatched')

        email = (sender_email or '').strip().lower()
        if not email or not parent:
            return unmatched

        # 1. exact email -> partner (supplier). The main email is checked first;
        #    failing that, the supplier's registered Offer Emails, so a supplier
        #    who sends from a second address still reaches their own folder
        #    instead of 'Unmatched'.
        partner = self.env['res.partner'].sudo().search(
            [('email', '=ilike', email)], limit=1)
        if not partner:
            alias = self.env['sbs.partner.offer.email'].sudo().search(
                [('email', '=ilike', email)], limit=1)
            partner = alias.partner_id
            if partner:
                _logger.info("[SBS] sender %s matched supplier %s via its "
                             "Offer Emails list.", email, partner.display_name)
        if not partner:
            return unmatched

        # 2. supplier's sub-folder under 'SBS Files'. Prefer the folder whose
        #    Contact (partner_id) IS this partner - an exact link - and fall back
        #    to matching the folder name against the partner name.
        folder = Doc.search([
            ('folder_id', '=', parent.id),
            ('partner_id', '=', partner.id),
        ], limit=1)
        if not folder:
            folder = Doc.search([
                ('folder_id', '=', parent.id),
                ('name', '=ilike', partner.name),
            ], limit=1)
        return folder or unmatched

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """
        Called by Odoo when an email arrives on this model's mail alias
        (e.g. sbs@company.com). We route the message to the sender's supplier
        folder; attachments are added by the standard mail flow, and the normal
        document-create hooks (sheet/price split) then run on each xlsx.
        """
        custom_values = dict(custom_values or {})
        sender = (msg_dict or {}).get('email_from') or ''

        # Email intake cutoff: ignore anything sent BEFORE the configured start
        # date. Uses the email's own Date header (msg_dict['date'], a UTC
        # datetime string set by mail.thread). On a new server this stops old
        # backlog mail from flooding in.
        # We still return a real record (Odoo's mail flow expects an id), but
        # route it to a throwaway state so no supplier folder / SBS pipeline
        # picks it up.
        start = self.env['ir.config_parameter'].sudo().get_param(
            'oe_sbs.email_intake_start_date')
        mail_date = (msg_dict or {}).get('date')
        # Both are UTC 'YYYY-MM-DD HH:MM:SS' strings, so a lexicographic compare
        # is chronological. Normalise defensively in case date arrives as a
        # datetime object.
        if start and mail_date:
            mail_date_s = fields.Datetime.to_string(
                fields.Datetime.to_datetime(mail_date)) or str(mail_date)
        else:
            mail_date_s = None
        if start and mail_date_s and mail_date_s < start:
            _logger.info(
                "[SBS email] ignored: sent %s, before intake start %s (from %s)",
                mail_date, start, sender)
            # Do NOT route to a supplier folder and mark it so the auto-send
            # cron skips it. It stays in the Unmatched/parent folder as a plain
            # record with no import pipeline attached.
            custom_values.setdefault('state', 'reject')
            custom_values.setdefault(
                'rejection_reason',
                "Email predates the Email Intake Start Date (%s); not imported."
                % start)
            return super().message_new(msg_dict, custom_values)

        # extract a bare address from 'Name <addr@x.com>'
        import re as _re
        m = _re.search(r'[\w.+-]+@[\w.-]+\.\w+', sender)
        sender_email = m.group(0) if m else sender
        folder = self._sbs_folder_for_sender(sender_email)
        if folder:
            # override, not setdefault: the alias already puts folder_id=Unmatched
            # in custom_values, but OUR sender-based routing must win so the file
            # lands in the supplier's folder (falling back to Unmatched only when
            # no supplier matched).
            custom_values['folder_id'] = folder.id
        _logger.info("[SBS email] from=%s -> folder=%s",
                     sender_email, folder.name if folder else '<none>')
        return super().message_new(msg_dict, custom_values)

    # ---------------------------------------------------------------------
    # Send-to-SBS core (shared by the HTTP controller and the auto cron)
    # ---------------------------------------------------------------------
    def _sbs_template_candidates(self):
        """
        Which of this supplier's mappings match this file?

        Returns (candidates, reason) where candidates is [(template, score), ...]
        best score first, and reason explains an EMPTY list. The reason matters:
        "no supplier on the folder", "this supplier has no mappings" and "none of
        the 4 mappings match the columns" are three different problems with three
        different fixes, and collapsing them into an empty list left the user
        with a dialog that did nothing.

        The scoring is not re-implemented here - it delegates to
        sbs.import.wizard._score_all_templates, the same code the import runs, so
        the picker can never offer a mapping the import would then refuse.
        """
        self.ensure_one()
        supplier = self._sbs_supplier_from_folder()
        if not supplier:
            return [], _(
                "No supplier could be resolved for the folder %(folder)s. Set the "
                "folder's Contact, or move the file to the supplier's folder.",
                folder=self.folder_id.display_name or _('(none)'))

        templates = self.env['sbs.import.template'].sudo().search([
            ('supplier_id', '=', supplier.id), ('active', '=', True),
        ])
        if not templates:
            return [], _(
                "%(supplier)s has no active import mapping yet. Create one from "
                "this file with the 'Create Template' button.",
                supplier=supplier.display_name)

        Wizard = self.env['sbs.import.wizard'].sudo()
        wizard = Wizard.new({'from_doc': True, 'document_id': self.id,
                             'file_name': self.name, 'supplier_id': supplier.id})
        try:
            content, is_json = wizard._read_source_file()
            scored = wizard._score_all_templates(content, is_json, templates)
        except Exception as exc:
            _logger.exception("[SBS] could not score templates for document %s",
                              self.id)
            return [], _("This file could not be read: %(error)s", error=exc)

        if not scored:
            return [], _(
                "None of the %(count)s mapping(s) for %(supplier)s match this "
                "file's columns: %(names)s.\n\nEither the file layout changed, or "
                "it belongs to a different supplier. Compare the header row with "
                "the mapping, or create a new mapping from this file.",
                count=len(templates), supplier=supplier.display_name,
                names=', '.join(templates.mapped('display_name')))

        return [(t, score) for t, score, _sheet in scored], ''

    def action_sbs_send_with_mapping(self):
        """
        Manual 'Send to SBS' for ONE document: ask which mapping to use.

        A person sending a single file by hand has a reason to be there, so the
        choice is always offered even when only one mapping matches - silently
        picking is what made a wrong mapping hard to notice. Multi-select and the
        unattended cron stay fully automatic: a dialog per file would be worse
        than today's behaviour, and the cron has nobody to answer it.

        This ALWAYS returns a client action. It used to fall back to
        _sbs_send_one() when nothing matched, which returns a plain dict rather
        than an action - so the button appeared to do nothing at all.
        """
        self.ensure_one()
        candidates, reason = self._sbs_template_candidates()
        if not candidates:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("No matching mapping"),
                    'message': reason,
                    'type': 'warning',
                    'sticky': True,
                },
            }
        wizard = self.env['sbs.send.wizard'].create({
            'document_id': self.id,
            'template_id': candidates[0][0].id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send to SBS'),
            'res_model': 'sbs.send.wizard',
            'res_id': wizard.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'new',
        }

    def _sbs_send_one(self, auto=False, forced_template_id=False):
        """
        Import ONE document into SBS and update its state. Returns a result dict:
          {'status': 'ok'|'no'|'no_template', ...}
        This holds the logic previously living in the controller so both the
        manual button and the auto cron behave identically. It does NOT raise;
        every outcome is reflected in the document's state + returned dict.

        auto=True marks the success state as 'auto_sent_to_sbs' (cron), so manual
        sends ('sent_to_sbs') can be told apart from automatic ones.
        """
        self.ensure_one()

        # split parents are handled via their children, never sent directly
        if self.sbs_split_done:
            return {'status': 'no',
                    'result_error': 'This file was split into separate '
                                    'single-sheet/price documents. Send those.'}
        if any(t.state == 'reject' for t in self.tag_ids):
            return {'status': 'no', 'result_error': 'document is rejected'}
        if self.import_number:
            return {'status': 'no', 'result_error': 'document was already imported.'}
        if self.state == 'auto_deleted':
            return {'status': 'no',
                    'result_error': 'document was already imported and deleted'}

        # supplier is resolved from the folder's Contact (partner_id), falling
        # back to the folder name - see _sbs_supplier_from_folder.
        supplier = self._sbs_supplier_from_folder()
        if not supplier:
            msg = "No supplier found for folder '%s'." % (
                self.folder_id.name if self.folder_id else '')
            self._sbs_reject(msg)
            return {'status': 'no', 'result_error': msg}

        # run the import wizard
        try:
            wizard = self.env['sbs.import.wizard'].sudo().create({
                'from_doc': True,
                'from_rpc': True,
                'document_id': self.id,
                'file_name': self.name,
                'supplier_id': supplier.id,
            })
            # A mapping chosen by hand overrides the score-based pick.
            if forced_template_id:
                wizard = wizard.with_context(
                    sbs_forced_template_id=forced_template_id)
            result = wizard.action_import()
        except Exception as e:
            # distinguish "no template matched" from a genuine rejection, so the
            # user knows the file is fine but still needs a template built.
            text = str(e)
            if 'no matching template' in text.lower() or 'template' in text.lower():
                self._sbs_reject(text, state='no_template')
                return {'status': 'no_template', 'result_error': text}
            self._sbs_reject(text)
            return {'status': 'no', 'result_error': text}

        if result.get('status') == 'ok':
            self.sudo().write({
                'import_number': result.get('import_number'),
                'template_id': result.get('template_id'),
                'modifier': self.env.user.id,
                'state': 'auto_sent_to_sbs' if auto else 'sent_to_sbs',
            })
        else:
            self._sbs_reject(result.get('result_error') or _("Unknown error."))
        return result

    def _sbs_reject(self, message, state='reject'):
        """
        Single place to fail a document: record the reason on the record AND
        push it to the chatter so somebody actually finds out.

        The auto-send cron runs unattended, so a transient UI notification is
        useless there - the reason has to be durable (rejection_reason) and
        pushed (chatter message to the document owner).
        """
        self.ensure_one()
        self.sudo().write({'rejection_reason': message, 'state': state})
        try:
            partner_ids = []
            if 'owner_id' in self._fields and self.owner_id \
                    and self.owner_id.partner_id:
                partner_ids = [self.owner_id.partner_id.id]
            body = _("SBS import failed: %s", message)
            self.sudo().message_post(
                body=body,
                partner_ids=partner_ids,
                subtype_xmlid='mail.mt_note',
            )
        except Exception:
            # never let the notification break the import flow
            _logger.warning("SBS: could not post rejection message on document %s",
                            self.id, exc_info=True)
        return True

    def action_sbs_retry(self):
        """
        Put a failed / waiting-for-mapping document back in the auto-send queue.
        The cron deliberately skips 'reject' and 'no_template' so it doesn't
        retry them forever; use this once the cause is fixed (template built,
        supplier set on the folder, ...).
        """
        for doc in self:
            if doc.import_number:
                continue                     # already imported - nothing to redo
            doc.sudo().write({
                'state': 'draft',
                'rejection_reason': False,
            })
        return True

    # ------------------------------------------------------------------
    # Excel preview (reuses the SheetJS viewer built for import templates)
    # ------------------------------------------------------------------
    SBS_PREVIEW_EXT = ('.xlsx', '.xls', '.xlsm', '.xlsb', '.csv')

    sbs_is_spreadsheet = fields.Boolean(
        string="Is Spreadsheet", compute='_compute_sbs_is_spreadsheet',
        help="Technical: drives the visibility of the Excel preview button.")

    @api.depends('name', 'mimetype')
    def _compute_sbs_is_spreadsheet(self):
        spreadsheet_mimes = (
            XLSX_MIME,
            'application/vnd.ms-excel',
            'application/vnd.ms-excel.sheet.macroenabled.12',
            'application/vnd.ms-excel.sheet.binary.macroenabled.12',
            'text/csv',
        )
        for rec in self:
            name = (rec.name or '').lower()
            rec.sbs_is_spreadsheet = bool(
                name.endswith(rec.SBS_PREVIEW_EXT)
                or (rec.mimetype or '') in spreadsheet_mimes
            )

    def _sbs_file_bytes(self):
        """Read the document's raw bytes, whichever way the file is stored
        (attachment, `raw`, or base64 `datas`). Returns bytes or False."""
        self.ensure_one()
        data = False
        if self.attachment_id:
            data = self.attachment_id.raw
        if not data:
            data = getattr(self, 'raw', False)
        if not data and getattr(self, 'datas', False):
            data = base64.b64decode(self.datas)
        return data or False

    def sbs_get_file_b64(self):
        """
        Return the file as base64 for the JS Excel viewer.
        Going through the ORM (instead of a /web/content URL) keeps the same
        robust byte lookup the import path uses, so it works for documents
        whose bytes live on the attachment, on `raw`, or on `datas`.
        """
        self.ensure_one()
        data = self._sbs_file_bytes()
        if not data:
            return {'error': _("This document has no file content.")}
        return {
            'name': self.name or '',
            'data': base64.b64encode(data).decode('ascii'),
        }

    def action_sbs_preview_excel(self):
        """Open the document in a read-only Excel viewer dialog."""
        self.ensure_one()
        if not self.sbs_is_spreadsheet:
            raise UserError(_("This document is not a spreadsheet."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Excel Preview: %s", self.name or ''),
            'res_model': 'documents.document',
            'res_id': self.id,
            'views': [(self.env.ref(
                'oe_sbs.documents_document_view_excel_preview_form').id, 'form')],
            'target': 'new',
            'context': dict(self.env.context, sbs_excel_preview=1),
        }

    @api.model
    def cron_auto_send_to_sbs(self, limit=100):
        """
        Auto-send eligible documents to SBS. Runs every 10 minutes via the
        'cron_sbs_auto_send' scheduled action.

        Scope: every file living under the 'SBS Files' folder - which is a parent
        holding one sub-folder per supplier - so we collect that parent's child
        folders and take the files inside them. Only not-yet-imported, non-split
        files are processed; _sbs_send_one applies the finer rules and skips
        anything already handled.
        """
        Doc = self.sudo()

        # locate the 'SBS Files' parent folder by name. Folders are documents
        # too; we don't hard-depend on a 'type' value (which varies by version) -
        # a folder is simply the record other documents point to via folder_id.
        parent = Doc.search([('name', '=', 'SBS Files')], limit=1)
        if not parent:
            _logger.info("[SBS auto-send] 'SBS Files' folder not found - nothing to do.")
            return True

        # supplier sub-folders directly under it, then the files inside them.
        sub_folders = Doc.search([('folder_id', '=', parent.id)])
        folder_ids = sub_folders.ids + [parent.id]

        # Start-date cutoff: never auto-import files that arrived BEFORE this
        # date. On a new server this stops the very first cron run from sweeping
        # in every historical file at once. Configurable in
        # Settings > SBS ('Auto-import start date'); stored as a config
        # parameter so it survives upgrades.
        # If the parameter is unset, we do NOT process anything and log a clear
        # note - a missing cutoff must never be read as "import everything".
        domain = [
            ('folder_id', 'in', folder_ids),
            ('import_number', '=', False),
            ('sbs_split_done', '=', False),
            ('state', 'not in', ('reject', 'no_template', 'sent_to_sbs',
                                 'auto_sent_to_sbs', 'deleted_from_sbs',
                                 'auto_deleted')),
        ]
        start_date = self.env['ir.config_parameter'].sudo().get_param(
            'oe_sbs.auto_import_start_date')
        if start_date:
            # Both create_date and the stored cutoff are UTC datetimes, so a
            # direct comparison is correct - a file counts as "new" when it was
            # created at or after the cutoff moment.
            domain.append(('create_date', '>=', start_date))
        else:
            _logger.info(
                "[SBS auto-send] 'Auto-import start date' is not set - "
                "skipping. Set it in Settings to enable auto-import.")
            return True

        # Only files that have never been through a send attempt (see domain).
        docs = Doc.search(domain, limit=limit)

        if not docs:
            _logger.info(
                "[SBS auto-send] no eligible files under 'SBS Files' "
                "(sub-folders=%s).", len(sub_folders))

        sent = failed = no_tpl = 0
        reasons = {}
        for doc in docs:
            name = (doc.name or '').lower()
            mime = doc.mimetype or ''
            # accept any spreadsheet: xlsx/xls/xlsb/xlsm/csv AND Odoo Spreadsheet
            is_spreadsheet = (
                mime == XLSX_MIME
                or mime == 'application/o-spreadsheet'
                or 'spreadsheet' in mime
                or mime in ('application/vnd.ms-excel', 'application/excel',
                            'text/csv', 'application/csv')
                or name.endswith(('.xlsx', '.xls', '.xlsb', '.xlsm', '.csv'))
            )
            if not is_spreadsheet:
                continue
            try:
                res = doc._sbs_send_one(auto=True)
                status = res.get('status')
                if status == 'ok':
                    sent += 1
                elif status == 'no_template':
                    no_tpl += 1
                else:
                    failed += 1
                    err = (res.get('result_error') or 'unknown')[:80]
                    reasons[err] = reasons.get(err, 0) + 1
            except Exception as e:
                failed += 1
                reasons[str(e)[:80]] = reasons.get(str(e)[:80], 0) + 1
                _logger.exception("[SBS auto-send] document %s failed: %s", doc.id, e)
        _logger.info("[SBS auto-send] found=%s sent=%s no_template=%s failed=%s",
                     len(docs), sent, no_tpl, failed)
        if reasons:
            # show WHY things failed - a bare count hides the actual problem
            _logger.warning("[SBS auto-send] failure reasons: %s", "; ".join(
                "%s x%d" % (msg, n) for msg, n in sorted(
                    reasons.items(), key=lambda kv: -kv[1])[:5]))
        return True


    def write(self, vals):

        if not self.env.su and 'tag_ids' in vals and not self.env.user.has_group('oe_sbs.group_tag_editor'):
            raise AccessError("Only members of Tag Editor group can modify tags.")


            # A tag is being added
        if 'tag_ids' in vals:

            print ("tag_ids tag_ids tag_ids tag_ids tag_ids tag_ids tag_ids tag_ids")
            print (vals['tag_ids'])
            tag_cmds = vals['tag_ids']
            for cmd in tag_cmds:
                # only (4, id) means linking an existing tag
                if isinstance(cmd, (list, tuple)) and len(cmd) >= 2 and cmd[0] == 4:
                    tag = self.env['documents.tag'].browse(cmd[1])
                    if tag.state == 'reject':
                        vals['modifier'] = self.env.user.id
                        break  # no need to continue

        #vals['modifier'] = False

        return super().write(vals)

    def export_final_xlsx(self):
            self.ensure_one()
            if self.mimetype != "application/o-spreadsheet":
                raise UserError(_("Not a spreadsheet"))

            snapshot = self._get_spreadsheet_serialized_snapshot()
           # print(snapshot)
            revisions = self.spreadsheet_revision_ids
           # print(revisions)

            final_data = self._apply_revisions(snapshot, revisions)
          #  print (final_data )
           # if "files" not in final_data:
            #    raise UserError(_("No files in final data"))
            #return self.env["spreadsheet.mixin"]._zip_xslx_files(final_data["sheets"])
            return final_data


    def _apply_revisions(self, snapshot, revisions):
        data = json.loads(json.dumps(snapshot))
        for rev in revisions:
            # Get commands from ORM object
            commands = rev.commands if hasattr(rev, 'commands') else []

            # Parse if it's a JSON string
            if isinstance(commands, str):
                try:
                    commands = json.loads(commands)
                except (json.JSONDecodeError, TypeError):
                    commands = []

            # Ensure commands is a list
            if not isinstance(commands, list):
                commands = []

            for cmd in commands:
                # Parse individual command if it's still a string
                if isinstance(cmd, str):
                    try:
                        cmd = json.loads(cmd)
                    except (json.JSONDecodeError, TypeError):
                        continue

                data = self._apply_command(data, cmd)
        return data

    def _apply_command(self, data, cmd):
        """
        Minimal server-side simulation of revision commands.
        Extend as needed (UPDATE_CELL, INSERT_ROW, DELETE_ROW, MERGE_CELLS, ...).
        """
        cmd_type = cmd.get("type")

        if cmd_type == "UPDATE_CELL":
            sheet_id = cmd.get("sheetId")
            row, col, value = cmd.get("row"), cmd.get("col"), cmd.get("value")
            for sheet in data.get("sheets", []):
                if sheet["id"] == sheet_id:
                    cells = sheet.setdefault("cells", {})
                    key = f"{row}:{col}"
                    cells[key] =  value
                    break

        elif cmd_type == "INSERT_ROW":
            sheet_id, row_index = cmd.get("sheetId"), cmd.get("row")
            for sheet in data.get("sheets", []):
                if sheet["id"] == sheet_id:
                    rows = sheet.setdefault("rows", [])
                    rows.insert(row_index, {})
                    break

        elif cmd_type == "DELETE_ROW":
            sheet_id, row_index = cmd.get("sheetId"), cmd.get("row")
            for sheet in data.get("sheets", []):
                if sheet["id"] == sheet_id:
                    rows = sheet.get("rows", [])
                    if 0 <= row_index < len(rows):
                        rows.pop(row_index)
                    break

        elif cmd_type == "MERGE_CELLS":
            sheet_id = cmd.get("sheetId")
            merge_range = cmd.get("range")
            for sheet in data.get("sheets", []):
                if sheet["id"] == sheet_id:
                    merges = sheet.setdefault("merges", [])
                    merges.append(merge_range)
                    break

        # TODO: more commands like INSERT_COLUMN, DELETE_COLUMN, RENAME_SHEET, ...

        return data


    def action_create_sbs_template(self):
        """Create an sbs.import.template from this document's xlsx, with the
        column mapping pre-filled by reading the file headers."""
        self.ensure_one()

        name = (self.name or '').lower()
        xlsx_mimes = (
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.ms-excel',
        )
        if self.mimetype not in xlsx_mimes and not name.endswith(('.xlsx', '.xls')):
            raise UserError(_("Please select an .xlsx file "
                            "(native Odoo spreadsheets must be exported to xlsx first)."))

        # Robustly read the raw bytes of the document
        data = False
        if self.attachment_id:
            data = self.attachment_id.raw
        if not data:
            data = getattr(self, 'raw', False)
        if not data and getattr(self, 'datas', False):
            data = base64.b64decode(self.datas)
        if not data:
            raise UserError(_("This document has no file content."))

        # A legacy .xls (OLE2) can't be read by openpyxl; convert to .xlsx bytes
        # first so auto-mapping and the stored preview both work on xlsx.
        if self._sbs_looks_like_xls(data):
            try:
                import xlrd
            except ImportError:
                raise UserError(_(
                    "Reading legacy .xls files requires the 'xlrd' Python package, "
                    "which is not installed on the server. Ask your administrator "
                    "to run 'pip install xlrd', or re-save the file as .xlsx."))
            data = self._sbs_xls_bytes_to_xlsx(data)

        Template = self.env['sbs.import.template']
        auto_vals = Template._auto_map_vals_from_xlsx(data)

        # ean_col / price_col are required -> guarantee a value (user can fix by click)
        auto_vals.setdefault('ean_col', 'A')
        auto_vals.setdefault('price_col', 'A')

        # Derive supplier from the folder's Contact (partner_id), falling back
        # to the folder name - same rule as Send to SBS.
        supplier = self._sbs_supplier_from_folder()

        # Create the template record so its Binary preview_file is stored
        # properly (a Binary can't be passed reliably through context defaults).
        # sbs_no_learn=True prevents this machine creation from populating the
        # synonym dictionary; learning happens later when the user saves the
        # template by hand (write -> _sbs_learn_mapped_headers).
        vals = {
            'name': _("Template - %s") % (self.name or 'Document'),
            'supplier_id': supplier.id if supplier else False,
            'document_id': self.id,
            'preview_file': base64.b64encode(data),
        }
        vals.update(auto_vals)
        template = Template.with_context(sbs_no_learn=True).create(vals)

        return {
            'type': 'ir.actions.act_window',
            'name': _("Create Template"),
            'res_model': 'sbs.import.template',
            'res_id': template.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }


class Tags(models.Model):
    _inherit = "documents.tag"



    def write(self, vals):

        if not self.env.su and 'tag_ids' in vals and not self.env.user.has_group('oe_sbs.group_tag_editor'):
            raise AccessError("Only members of Tag Editor group can modify tags.")

        return super().write(vals)
