from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
from io import BytesIO
from datetime import datetime,date,timedelta
from dateutil.relativedelta import relativedelta
import re
from openpyxl import load_workbook,Workbook
from unidecode import unidecode
import json
import io
import zipfile
import re
import logging
_logger = logging.getLogger(__name__)

def parse_cell_reference(cell_ref):
    """ تبدیل آدرس (مثلاً A3) به (ایندکس ستون، شماره ردیف شروع) - ایندکس ستون از 0 شروع می‌شود """
    if not cell_ref: return None, None
    match = re.match(r"([A-Z]+)(\d+)", str(cell_ref).strip().upper())
    if not match: return None, None
    col_str, row_str = match.groups()
    col_idx = 0
    for char in col_str:
        col_idx = col_idx * 26 + (ord(char) - ord('A') + 1)
    return col_idx - 1, int(row_str)

class ImportDataWizard(models.TransientModel):
    _name = 'sbs.import.wizard'
    _description = 'SBS Import Wizard'
    
    file = fields.Binary(string='Excel File')
    file_name = fields.Char(string='Filename')
    #import_number = fields.Char(string='Import Number',  default=lambda self: self._generate_import_number())
    import_number = fields.Char(string='Import Number',  default=False)
    
    currency_id = fields.Many2one('res.currency', string='Default Currency', 
                                default=lambda self: self.env.ref('base.USD'))
    total_imported = fields.Integer(string="Imported Records", readonly=True)
    total_skipped = fields.Integer(string="Skipped Records", readonly=True)
    show_results = fields.Boolean(string="Show Results", default=False)
    result_error = fields.Char(string='Result Error')
    cleanup_msg= fields.Char(string='CleanUP Message')
    
    from_doc = fields.Boolean(string="From Documents", default=False)
    from_rpc = fields.Boolean(string="From RPC", default=False)


    document_id = fields.Many2one('documents.document', string="Excel File")

   # def _generate_import_number(self):
    #    return self.env['ir.sequence'].next_by_code('sbs.import.sequence') or _('New')

    supplier_id = fields.Many2one('res.partner', string='Supplier')
    # فیلد template_id دیگر required نیست
    template_id = fields.Many2one('sbs.import.template', string='Template', domain="[('supplier_id', '=', supplier_id)]")
    
   

        
    @api.onchange('template_id')
    def _onchange_template_id(self):
        """Auto-fill sheet name when template is selected"""
        if self.template_id:
            self.sheet_name = self.template_id.sheet_name or 'climax'

    def _get_template_column_mapping(self):
        """Build column mapping from template lines"""
        if not self.template_id:
            return {}
        
        mapping = {}
        for line in self.template_id.line_ids:
            mapping[line.excel_column.strip().lower()] = line.field_name
        
        return mapping

    def _get_template_required_columns(self):
        """Get list of required columns from template"""
        if not self.template_id:
            return []
        
        required = []
        for line in self.template_id.line_ids:
            if line.is_required:
                required.append(line.excel_column.strip().lower())
        
        return required

    
    def _safe_unidecode(self,text):
        result = ""
        for i, ch in enumerate(text):
            converted = unidecode(ch)
            # اگر خروجی فقط یک حرف بود و upper شد، اصلاحش کن
            if len(converted) == 1 and ch.islower() and converted.isupper():
                result += converted.lower()
            else:
                result += converted
        return result

    def _parse_accounting_number(self, cell):
        """Parse Excel cells with flexible currency and accounting formats."""

        try:
            # --- 1. Extract raw_value safely ---
            if hasattr(cell, "value"):  # یعنی یه cell واقعی هست
                raw_value = cell.value
                fmt = getattr(cell, "number_format", "") or ""
            else:  # یعنی فقط str یا عدد داده شده
                raw_value = cell
                fmt = ""

            if raw_value is None or raw_value == "":
                return 0.0, False

            fmt_lower = fmt.lower()
            currency_id = False
            symbol = None

            # --- 2. Try to extract currency symbol from number_format ---
            match = re.search(r'\[\$(.)', fmt_lower)
            if match:
                symbol = match.group(1)

            # --- 3. If not in number format, try from value string ---
            if not symbol and isinstance(raw_value, str):
                # شناسایی نمادهای ارزی (USD, EUR, GBP, AED)
                symbol_match = re.search(r'(€|\$|£|aed)', raw_value, re.IGNORECASE)
                if symbol_match:
                    symbol = symbol_match.group(0).upper()

            # --- 4. Map symbol to currency ID ---
            if symbol == '$':
                currency_id = self.env.ref('base.USD').id
            elif symbol == '€':
                currency_id = self.env.ref('base.EUR').id
            elif symbol == '£':
                currency_id = self.env.ref('base.GBP').id
            elif symbol == 'AED':
                currency_id = self.env.ref('base.AED').id

            # --- 5. Extract numeric value ---
            amount = 0.0
            if isinstance(raw_value, (int, float)):
                amount = float(raw_value)

            elif isinstance(raw_value, str):
                # حذف همه currency symbols و فاصله بعدش/قبلش
                cleaned = re.sub(r'(€|\$|£|aed)\s*', '', raw_value, flags=re.IGNORECASE)

                # هندل کردن اعداد منفی پرانتزی مثل (123)
                if '(' in raw_value and ')' in raw_value:
                    cleaned = '-' + cleaned.replace('(', '').replace(')', '')

                # حذف کاما
                cleaned = cleaned.replace(',', '')

                try:
                    amount = float(cleaned)
                except ValueError:
                    amount = 0.0

            # --- 6. Handle negative from number format ---
            if '(' in fmt and amount > 0:
                amount = -amount

            return amount, currency_id

        except Exception:
            return 0.0, False
   
    '''
    def get_final_spreadsheet_xlsx(self, document):
        """
        Return bytes of the final XLSX file for a documents.document record.
        Supports:
          - document.spreadsheet_data that is already an unzipped xlsx mapping
          - document.spreadsheet_data that contains a 'files' key (client export format)
        If spreadsheet_data is only a 'snapshot' (sheets + revisions), raise descriptive error.
        """
        self.ensure_one()
        if not document:
            raise ValueError("No document provided")
        if document.mimetype != "application/o-spreadsheet":
            raise ValueError("Document is not an Odoo spreadsheet (mimetype != application/o-spreadsheet)")

        # 1) load the spreadsheet_data (it's a text field)
        raw = document.spreadsheet_data or ''
        if not raw:
            # maybe spreadsheet_binary_data contains base64 JSON
            if getattr(document, 'spreadsheet_binary_data', False):
                try:
                    raw = base64.b64decode(document.spreadsheet_binary_data).decode('utf-8')
                except Exception:
                    raw = ''
        if not raw:
            raise ValueError("Document has no spreadsheet_data / spreadsheet_binary_data to export")

        try:
            data = json.loads(raw)
        except Exception as e:
            raise ValueError("Could not parse spreadsheet_data JSON: %s" % e)

        # Helper to detect if data is unzipped xlsx mapping (keys like '[Content_Types].xml' or 'xl/')
        def looks_like_unzipped(mapping):
            if not isinstance(mapping, dict):
                return False
            for k in mapping.keys():
                if k == "[Content_Types].xml" or k.startswith("xl/"):
                    return True
            return False

        files_list = None

        # Case A: client-style export: it already contains 'files'
        if isinstance(data, dict) and 'files' in data and isinstance(data['files'], list):
            files_list = data['files']

        # Case B: data is an unzipped xlsx mapping -> convert to list of {path, content} or {path, imageSrc}
        elif looks_like_unzipped(data):
            files_list = []
            for path, content in data.items():
                if isinstance(content, str):
                    files_list.append({'path': path, 'content': content})
                elif isinstance(content, dict) and 'imageSrc' in content:
                    # keep imageSrc entry (spreadsheet.mixin._zip_xslx_files will fetch image)
                    files_list.append({'path': path, 'imageSrc': content.get('imageSrc')})
                else:
                    # fallback: serialize unknown content into string
                    files_list.append({'path': path, 'content': json.dumps(content)})

        else:
            # This is very likely the 'snapshot' (sheets + formulas) case which needs client-side merge.
            # We cannot reliably produce final XLSX on server without implementing JS merge logic.
            raise ValueError(
                "The spreadsheet data is a 'snapshot' (sheets) not raw xlsx files. "
                "To obtain the final XLSX you have three options:\n"
                " 1) Ask the user to Export/Download XLSX from the UI (client will produce final .xlsx).\n"
                " 2) Freeze the spreadsheet (action_freeze_and_copy / freeze UI) to populate document.excel_export, "
                "   then read document.excel_export (base64) server-side.\n"
                " 3) Implement the full server-side merger of snapshot+revisions (complex — requires re-implementing client logic)."
            )

        # now files_list holds the expected structure for _zip_xslx_files
        print ("ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ")
        xlsx_bytes = self.env['spreadsheet.mixin']._zip_xslx_files(files_list)
        return xlsx_bytes
    '''
     
    def excel_date_to_str(self, value):
        try:
            # مطمئن بشیم عدد هست (نه رشته)
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            elif isinstance(value, (int, float)):
                value = int(value)
            else:
                return value  # اصلاً تاریخ نیست

            # اکسل تاریخ‌ها رو از 1899-12-30 شروع می‌کنه
            base_date = datetime(1899, 12, 30)
            date_obj = base_date + timedelta(days=value)
            return date_obj.strftime("%d/%m/%Y")
        except Exception:
            return value

    def _get_or_create_uom(self, case_size):
        """
        Find or create a UOM based on case_size.
        Compatible with Odoo 19 tree-based UOM structure.
        """
        UoM = self.env['uom.uom']

        try:
            unit_uom = self.env.ref('uom.product_uom_unit')
        except ValueError:
            unit_uom = UoM.search([
                ('relative_uom_id', '=', False),
                ('relative_factor', '=', 1.0),
            ], limit=1)

        if not unit_uom:
            _logger.warning("[SBS UOM] Base Unit of Measure not found.")
            return False

        # case_size <= 1: برگشت واحد پایه
        if not case_size or int(case_size) <= 1:
            return unit_uom

        case_size_float = float(int(case_size))

        # جستجوی UOM موجود
        uom = UoM.search([
            ('relative_uom_id', '=', unit_uom.id),
            ('relative_factor', '=', case_size_float),
        ], limit=1)

        # ساخت UOM جدید در صورت نبود
        if not uom:
            try:
                uom = UoM.sudo().create({
                    'name': f'Pack of {int(case_size)}',
                    'relative_uom_id': unit_uom.id,
                    'relative_factor': case_size_float,
                })
                _logger.info(
                    "[SBS UOM] New UOM created: '%s' (id=%s, factor=%s)",
                    uom.name, uom.id, case_size_float
                )
            except Exception as e:
                _logger.warning("[SBS UOM] Failed to create UOM: %s", e)
                return unit_uom

        return uom


    def _sync_uom_to_product(self, product_tmpl, uom):
        """
        Add the UOM to product.template.uom_ids (Many2many field).

        uom_ids = fields.Many2many('uom.uom', string='Packagings',
            domain="[('id', '!=', uom_id)]")
        """
        if not product_tmpl or not uom:
            return

        # اگر همان uom_id پیش‌فرض محصول است → skip
        if product_tmpl.uom_id.id == uom.id:
            _logger.debug(
                "[SBS UOM] UOM '%s' is the default UOM of product '%s' — skipping",
                uom.name, product_tmpl.name
            )
            return

        # اگر قبلاً در uom_ids وجود دارد → skip
        if uom in product_tmpl.uom_ids:
            _logger.debug(
                "[SBS UOM] UOM '%s' already in uom_ids of product '%s' — skipping",
                uom.name, product_tmpl.name
            )
            return

        # اضافه کردن به Many2many با command (4, id)
        try:
            product_tmpl.sudo().write({
                'uom_ids': [(4, uom.id)]
            })
            _logger.info(
                "[SBS UOM] UOM '%s' added to uom_ids of product '%s' (id=%s)",
                uom.name, product_tmpl.name, product_tmpl.id
            )
        except Exception as e:
            _logger.warning(
                "[SBS UOM] Failed to add UOM '%s' to product '%s': %s",
                uom.name, product_tmpl.name, e
            )

    def action_import(self):
        self.ensure_one()
        if not self.from_doc and not self.file:
            raise UserError(_('Please upload a file first.'))
        if self.from_doc and not self.document_id:
            raise UserError(_('Please select a file first.'))

        try:
            imported_count = 0
            validation_errors = []
            temp_records = []

            #import_date = date.today().isoformat()
            import_date = date.today()


            # =================================================================
            # 1. خواندن فایل و تبدیل به ماتریس 2 بعدی (List of Lists)
            # =================================================================
            if not self.from_doc:
                file_content = base64.b64decode(self.file)
                is_json = False
            else:
                mimetype = self.document_id.mimetype
                if mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                    file_content = base64.b64decode(self.document_id.datas)
                    is_json = False
                elif mimetype == 'application/o-spreadsheet':
                    file_content = self.document_id.export_final_xlsx()
                    is_json = True
                else:
                    raise UserError(_('Unsupported document type: %s') % mimetype)

            # =================================================================
            # 1 و 2. جستجوی قالب‌ها، انتخاب شیت و استخراج داده‌ها به صورت همزمان
            # =================================================================
            if hasattr(self, 'supplier_id') or not self.supplier_id:
                available_templates = self.env['sbs.import.template'].search([
                    ('supplier_id', '=', self.supplier_id.id),
                    ('active', '=', True)
                ])
            
            if not available_templates:
                available_templates = self.env['sbs.import.template'].search([('active', '=', True), ('supplier_id', '=', False)])
                
            template = None
            sheet_data = []
    
            print(self.supplier_id)
            print(available_templates)
            print("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFffffffffffffffffffffff")
            print(is_json)

            
            # --- تابع اعتبارسنجی دقیق هدرها ---
                        # --- تابع اعتبارسنجی بسیار دقیق هدرها ---
            
            def validate_template_headers(t, current_sheet_data):
                header_row_val = getattr(t, 'header_row', 1)
                header_row_idx = header_row_val - 1 if header_row_val > 0 else 0
                
                if header_row_idx < 0 or header_row_idx >= len(current_sheet_data):
                    return False

                fields_to_check = [
                    (t.ean_col, t.ean_header, 'EAN'),
                    (t.product_name_col, t.product_name_header, 'Product Name'),
                    (t.price_col, t.price_header, 'Price'),
                    (t.supplier_code_col, t.supplier_code_header, 'Supplier Code'),
                    (t.brand_col, t.brand_header, 'Brand'),
                    (t.moq_col, t.moq_header, 'MOQ'),
                    (t.mov_col, t.mov_header, 'MOV'),
                    (t.available_qty_col, t.available_qty_header, 'Available Qty'),
                ]
                
                has_headers_to_check = False

                for col_ref, expected_header, field_name in fields_to_check:
                    # اگر ستون (مثلا A) در تنظیمات پر شده بود، باید حتما چکش کنیم
                    if col_ref:
                        has_headers_to_check = True
                        c_idx, _ = parse_cell_reference(col_ref)
                        
                        if c_idx is not None:
                            try:
                                val = current_sheet_data[header_row_idx][c_idx]
                                # مدیریت مقادیر خالی
                                actual_header = str(val.value if hasattr(val, 'value') and val.value is not None else val if val is not None else "").strip()
                                expected_str = str(expected_header).strip() if expected_header else ""
                                
                                # مقایسه دقیق
                                if not expected_str:
                                    print(f"❌ Template '{t.name}' rejected: expected header is empty in template settings.")
                                    return False

                                if actual_header.lower() != expected_str.lower():
                                    print(f"❌ Template '{t.name}' rejected: {field_name} mismatch. Excel has '{actual_header}', Template expects '{expected_str}'")
                                    return False
                                    
                            except IndexError:
                                print(f"❌ Template '{t.name}' rejected: Column {col_ref} does not exist in Excel.")
                                return False
                
                if not has_headers_to_check:
                    print(f"❌ Template '{t.name}' rejected: No columns defined in template settings.")
                    return False
                    
                print(f"✅ Template '{t.name}' EXACT MATCH FOUND!")
                return True

            
            
            # ----------------------------------------

            if is_json:
                data = file_content if isinstance(file_content, dict) else json.loads(file_content)
                sheets = data.get("sheets", [])
                
                for t in available_templates:
                    
                    print ("tttttttttttttttttttttttttttttttttttttttttttttt")
                    print (t)

                    # پیدا کردن شیت بر اساس نام در قالب یا انتخاب شیت اول
                    t_sheet_name = t.sheet_name.strip().lower() if getattr(t, 'sheet_name', False) else None
                    if t_sheet_name:
                        sheet = next((s for s in sheets if s["name"].strip().lower() == t_sheet_name), None)
                    else:
                        sheet = sheets[0] if sheets else None

                    if not sheet: 
                        continue
                        
                    cells = sheet.get("cells", {})
                    def get_json_val(cell_data):
                        if isinstance(cell_data, dict): return cell_data.get("content", "")
                        return str(cell_data) if cell_data else ""

                    # ساخت موقت داده‌های این شیت
                    temp_sheet_data = []
                    max_row = sheet.get("rowNumber", 100)
                    max_col = 50 
                    for r in range(1, max_row + 1):
                        row_vals = []
                        for c in range(1, max_col + 1):
                            col_letter = chr(64 + c) if c <= 26 else chr(64 + c//26) + chr(64 + c%26)
                            key = f"{col_letter}{r}"
                            row_vals.append(get_json_val(cells.get(key, "")))
                        temp_sheet_data.append(row_vals)
                        
                    '''
                    # بررسی امضای قالب و سپس اعتبارسنجی هدرها در این شیت
                    col_idx, row_num = parse_cell_reference(t.signature_cell)
                    if col_idx is not None and row_num is not None:
                        try:
                            cell_val = str(temp_sheet_data[row_num - 1][col_idx]).strip()
                            if cell_val == t.signature_text.strip():
                                if validate_template_headers(t, temp_sheet_data): # چک کردن هدرها
                                    template = t
                                    sheet_data = temp_sheet_data
                                    break  # قالب پیدا شد، خروج از حلقه
                        except IndexError:
                            continue
                    '''
                    # بررسی امضای قالب فعلاً حذف شده است و فقط هدرها چک می‌شوند
                    if validate_template_headers(t, temp_sheet_data): # چک کردن هدرها
                        template = t
                        sheet_data = temp_sheet_data
                        break  # قالب پیدا شد، خروج از حلقه

                print ("TTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTT")
                print (template)

            else: # حالت XLSX
                workbook = load_workbook(filename=BytesIO(file_content), data_only=True)
                
                for t in available_templates:
                    t_sheet_name = t.sheet_name.strip().lower() if getattr(t, 'sheet_name', False) else None
                    if t_sheet_name:
                        sheet_name = next((n for n in workbook.sheetnames if n.strip().lower() == t_sheet_name), None)
                    else:
                        sheet_name = workbook.sheetnames[0] if workbook.sheetnames else None
                        
                    if not sheet_name: 
                        continue
                        
                    sheet = workbook[sheet_name]
                    temp_sheet_data = []
                    for row in sheet.iter_rows():
                        temp_sheet_data.append([cell.value for cell in row])
                        
                    '''
                    # بررسی امضای قالب و سپس اعتبارسنجی هدرها
                    col_idx, row_num = parse_cell_reference(t.signature_cell)
                    if col_idx is not None and row_num is not None:
                        try:
                            val = temp_sheet_data[row_num - 1][col_idx]
                            cell_val = str(val).strip() if val is not None else ""
                            if cell_val == t.signature_text.strip():
                                if validate_template_headers(t, temp_sheet_data): # چک کردن هدرها
                                    template = t
                                    sheet_data = temp_sheet_data
                                    break  # قالب پیدا شد، خروج از حلقه
                        except IndexError:
                            continue
                    '''

                    # بررسی امضای قالب فعلاً حذف شده است و فقط هدرها چک می‌شوند
                    if validate_template_headers(t, temp_sheet_data): # چک کردن هدرها
                        template = t
                        sheet_data = temp_sheet_data
                        break  # قالب پیدا شد، خروج از حلقه

            # اگر هیچ قالبی مچ نشد (به دلیل امضا یا هدر)
            if not template:
                raise UserError(_('No matching template found. Please ensure both the column number and the expected column headers match the uploaded file.'))

         
            # --- تعیین سطر شروع داده‌ها بر اساس ترکیب header_row و ean_col ---
            header_row_val = getattr(template, 'header_row', 0)
            ean_col_idx, start_row_from_ean = parse_cell_reference(template.ean_col)
            
            if header_row_val and header_row_val > 0:
                # اگر کاربر سطر هدر را مشخص کرده، داده‌ها از سطر بعدی شروع می‌شوند
                start_row = header_row_val + 1
            else:
                # اگر مشخص نکرده بود، از عدد همراه ستون (مثلا 2 در A2) استفاده می‌کنیم
                start_row = start_row_from_ean if start_row_from_ean is not None else 2

            # =================================================================
            # 3. توابع کمکی
            # =================================================================
            def get_val(col_ref, current_row_idx_0_based):
                c_idx, _ = parse_cell_reference(col_ref)
                if c_idx is None: return None
                try:
                    val = sheet_data[current_row_idx_0_based][c_idx]
                    return val.value if hasattr(val, 'value') else val
                except IndexError:
                    return None


            # --- تابع جدید برای اعمال منطق Fallback ---
            def get_final_val(col_ref, fixed_val, current_row_idx):
                # 1. اول تلاش برای خواندن از ستون اکسل
                val = get_val(col_ref, current_row_idx) if col_ref else None
                if val not in (False, None, ''):
                    return val
                # 2. اگر اکسل خالی بود، استفاده از مقدار ثابت قالب
                if fixed_val not in (False, None, ''):
                    return fixed_val
                # 3. در غیر این صورت هیچی
                return None


            def parse_date_value(val, fmt_list=("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y")):
                if not val: return None
                if isinstance(val, datetime): return val
                if isinstance(val, date): return datetime.combine(val, datetime.min.time())
                for fmt in fmt_list:
                    try:
                        return datetime.strptime(str(val).strip(), fmt)
                    except ValueError:
                        continue
                return None

            SBSData = self.env['sbs.data']
            if SBSData.with_context(prefetch_fields=False).search([('excel_filename', '=', self.file_name)]):
                raise UserError(_('File Already Exist!'))

            valid_currency_ids = self.env['res.currency'].search([]).ids
            ICP = self.env['ir.config_parameter'].sudo()
            margin = float(ICP.get_param('oe_sbs.default_profit_margin', '8')) / 100
            min_margin = float(ICP.get_param('oe_sbs.min_profit_margin', '7')) / 100
            usd_currency = self.env.ref('base.USD')

            # =================================================================
            # 4. پردازش ردیف‌ها
            # =================================================================
            
            print ("SSSSSSSSSSSSSSSSSSSSddddddddddddddddddddddddddddddddddddddddd")
            print (len(sheet_data))
            
            for row_idx_0_based in range(start_row - 1, len(sheet_data)):
                row_index = row_idx_0_based + 1
                row_vals_list = sheet_data[row_idx_0_based]
                
                # اگر ردیف کاملا خالی است رد شود
                if not any(val not in (None, '') for val in row_vals_list):
                    continue

                # بررسی اجمالی: اگر EAN و اسم محصول خالی بود، رد شو
                ean_check = get_val(template.ean_col, row_idx_0_based)
                desc_check = get_val(template.product_name_col, row_idx_0_based)
                if not ean_check and not desc_check:
                    continue

                record_vals = {'excel_filename': self.file_name}
                row_errors = []

                # --- اطلاعات تامین‌کننده (از قالب یا خواندن از اکسل) ---
                if template.supplier_id:
                    record_vals['supplier_id'] = template.supplier_id.id
                    record_vals['supplier_name'] = template.supplier_id.name
                    if hasattr(template.supplier_id, 'partner_code'):
                        record_vals['supplier_code'] = template.supplier_id.partner_code
                else:
                    # اگر قالب تامین‌کننده ثابت نداشت، می‌گذاریم خالی بماند تا بعدا پیدا کنیم
                    record_vals['supplier_id'] = False
                    
                    if hasattr(template, 'supplier_code_col') and template.supplier_code_col:
                        record_vals['supplier_code'] = get_val(template.supplier_code_col, row_idx_0_based)

                # ---------------- Import Date ----------------
                           
                #record_vals['import_date'] =import_date
                
                # ---------------- EAN / Barcode ----------------
                ean_val = str(get_val(template.ean_col, row_idx_0_based) or '').strip()
                if not ean_val:
                    row_errors.append("Missing EAN (barcode)")
                elif not ean_val.isdigit():
                    row_errors.append(f"Invalid EAN (non-numeric): {ean_val}")
                elif len(ean_val) > 13:
                    row_errors.append(f"Invalid EAN length > 13: {ean_val}")
                else:
                    record_vals['ean'] = ean_val.zfill(13)

                # ---------------- Product Name ----------------
                desc_val = get_val(template.product_name_col, row_idx_0_based)
                if not desc_val:
                    row_errors.append("Missing product name")
                else:
                    record_vals['product_name'] = unidecode(str(desc_val).strip()).title()

                # ---------------- Price & Currency ----------------
                price_val = get_val(template.price_col, row_idx_0_based)
                price_value, currency_id = self._parse_accounting_number(price_val)
                
                # اگر ارز از طریق تابع به دست نیامد، از ارز ثابت قالب استفاده می‌کنیم
                if not currency_id and hasattr(template, 'currency_fixed_id') and template.currency_fixed_id:
                    currency_id = template.currency_fixed_id.id

                if not currency_id or currency_id not in valid_currency_ids or price_value is None or price_value == 0:
                    row_errors.append("Invalid price or currency")
                else:
                    record_vals['supplier_unit_price'] = abs(price_value)
                    record_vals['currency_id'] = currency_id

                
                '''
                # ---------------- End Date / Offer Validity ----------------
                end_date_val = get_val(template.end_date_col, row_idx_0_based)
                parsed_end_date = parse_date_value(end_date_val)
                if parsed_end_date:
                    record_vals['end_date'] = parsed_end_date.isoformat()
                else:
                    row_errors.append(f"Row {row_index}: Invalid offer validity format (expected DD-Mon-YYYY)")

                # ---------- بررسی اعتبار تاریخ‌ها ----------
                today = date.today()
                if parsed_end_date:
                    if parsed_import_date and parsed_end_date.date() <= parsed_import_date.date():
                        row_errors.append(f"Row {row_index}: Offer validity is earlier than import date")
                    
                    record_vals['is_expired'] = bool(parsed_end_date.date() < today)
                    if parsed_end_date.date() < today:
                        row_errors.append(f"Row {row_index}: Offer validity date is expired")
                '''
                
                offer_validity_val = None
                
                # ۱. خواندن مقدار Offer Validity از اکسل یا مقدار ثابت قالب
                offer_fixed_key = template.offer_validity_fixed if hasattr(template, 'offer_validity_fixed') else None
                offer_val_from_excel = get_val(getattr(template, 'offer_validity_col', False), row_idx_0_based)
                
                final_offer_val_text = None
                if offer_val_from_excel not in (False, None, ''):
                    offer_validity_val = offer_val_from_excel
                    final_offer_val_text = str(offer_val_from_excel).strip()
                elif offer_fixed_key not in (False, None, ''):
                    offer_validity_val = offer_fixed_key  # مقدار کلید Selection مثل '1', '2'
                    # استخراج متن نمایشی (مثلا '1 Week') برای ذخیره در رکورد
                    final_offer_val_text = dict(template._fields['offer_validity_fixed'].selection).get(offer_fixed_key)

                # ذخیره مقدار متنی offer_validity در رکورد
                if final_offer_val_text:
                    record_vals['end_date'] = final_offer_val_text

                # ۲. تنظیم import_date و محاسبه end_date
                record_vals['import_date'] = import_date
                
                end_date = None
                
                               
                
                if offer_validity_val:
                    try:
                        # استخراج اولین عدد از متن (مثلا از '2 Weeks' یا '2' عدد 2 را می‌گیرد)
                        weeks_to_add = int(re.search(r'\d+', str(offer_validity_val)).group())
                        
                        # استفاده از timedelta که در فایل شما ایمپورت شده است
                        end_date = import_date + timedelta(weeks=weeks_to_add)
                    except (ValueError, AttributeError, TypeError) as e:
                        row_errors.append(f"Row {row_index}: Invalid Offer Validity format: '{offer_validity_val}' - Error: {str(e)}")
                

                record_vals['end_date'] = end_date if end_date else False

                # ---------------- MOQ & MOV ----------------
                moq_val = get_val(template.moq_col, row_idx_0_based) if hasattr(template, 'moq_col') and template.moq_col else None
                #mov_val = get_val(template.mov_col, row_idx_0_based) if hasattr(template, 'mov_col') and template.mov_col else None

                
                 # برای MOV: استخراج مقدار نام از فیلد Many2one در صورت وجود
                mov_fixed_name = template.mov_fixed.name if hasattr(template, 'mov_fixed') and template.mov_fixed else None
                mov_val = get_final_val(getattr(template, 'mov_col', False), mov_fixed_name, row_idx_0_based)

                
                if not moq_val and not mov_val:
                    row_errors.append(f"Row {row_index}: At least one of MOQ or MOV must have value")
                
                if moq_val and isinstance(moq_val, str) and re.search(r'(€|\$|£|aed)', str(moq_val), re.IGNORECASE):
                    row_errors.append(f"Row {row_index}: MOQ must not contain currency")
                else:
                    if moq_val: record_vals['moq'] = str(moq_val).strip()
                
                if mov_val:
                    mov_raw = str(mov_val).strip()
                    m = re.search(r'(€|\$|£|aed)', mov_raw, re.IGNORECASE)
                    if not m:
                        row_errors.append(f"Row {row_index}: MOV must contain a currency symbol (€, $, £ or AED)")
                    else:
                        mov_symbol = m.group(0).upper()
                        body = re.sub(r'(€|\$|£|aed)\s*', '', mov_raw, flags=re.IGNORECASE)
                        body = re.sub(r'[^0-9\.,kK]', '', body).replace('K', 'k')
                        if body.count('k') > 1:
                            row_errors.append(f"Row {row_index}: MOV contains multiple 'k' characters")
                        else:
                            if 'k' in body and not body.endswith('k'):
                                body = re.sub(r'k', '', body) + 'k'
                            if not re.search(r'\d', body):
                                row_errors.append(f"Row {row_index}: MOV must contain at least one digit")
                            else:
                                record_vals['mov'] = f"{mov_symbol}{body}"
                                # بررسی تطابق ارز MOV
                                cur = self.env['res.currency'].browse(currency_id) if currency_id else False
                                cur_symbol = cur.symbol if cur and cur.symbol in ('$', '€', '£', 'AED') else None
                                if not cur_symbol and cur:
                                    cur_symbol = ('$' if cur.id == self.env.ref('base.USD').id else
                                                  '€' if cur.id == self.env.ref('base.EUR').id else
                                                  '£' if cur.id == self.env.ref('base.GBP').id else
                                                  'AED' if cur.id == self.env.ref('base.AED').id else None)
                                if cur_symbol and mov_symbol != cur_symbol:
                                    row_errors.append(f"Row {row_index}: MOV currency ({mov_symbol}) does not match price currency ({cur_symbol})")

                # ---------------- Available QTY ----------------
                avail_val = get_val(template.available_qty_col, row_idx_0_based)
                if avail_val not in (None, ''):
                    try:
                        val_str = str(avail_val).strip()
                        if re.search(r'(€|\$|£|aed)', val_str, re.IGNORECASE):
                            row_errors.append(f"Row {row_index}: Available Units must not contain currency symbols")
                        else:
                            record_vals['availabale_qty'] = float(val_str)
                    except ValueError:
                        row_errors.append(f"Row {row_index}: Available Units must be numeric")

                # ---------------- T1/T2 ----------------
                t1t2_val = get_val(template.t1_t2_col, row_idx_0_based) if hasattr(template, 't1_t2_col') and template.t1_t2_col else None
                if t1t2_val:
                    tval = str(t1t2_val).strip().upper()
                    if tval not in ['T1', 'T2']:
                        row_errors.append(f"Row {row_index}: T1-T2 must be empty or T1/T2")
                    else:
                        record_vals['t1_t2'] = tval

               # ---------------- سایر فیلدهای Optional (معمولی) ----------------
                optional_fields = {
                    'case_size': getattr(template, 'case_size_col', False),
                    'layer': getattr(template, 'layer_col', False),
                    'pallet': getattr(template, 'pallet_col', False),
                    'note': getattr(template, 'note_col', False),
                    'unit_per_layer': getattr(template, 'unit_per_layer_col', False),
                    'unit_per_pallet': getattr(template, 'unit_per_pallet_col', False),
                    'hs_code': getattr(template, 'hs_code_col', False),
                }
                
                for odoo_field, col_ref in optional_fields.items():
                    if not col_ref: continue
                    val = get_val(col_ref, row_idx_0_based)
                    if val not in (None, ''):
                        # فیلدهای عددی جدید به این لیست اضافه شدند
                        if odoo_field in ['case_size', 'layer', 'pallet', 'unit_per_layer', 'unit_per_pallet']:
                            try: record_vals[odoo_field] = int(float(val))
                            except: record_vals[odoo_field] = 0
                        else:
                            # فیلد hs_code و note از این طریق به صورت متن خوانده می‌شوند
                            record_vals[odoo_field] = str(val).strip()

                # ---------------- فیلدهای دارای مقدار ثابت (Fallback) ----------------
                
                # COO (Country of Origin) - Many2one
                coo_fixed = template.coo_fixed.name if hasattr(template, 'coo_fixed') and template.coo_fixed else None
                coo_val = get_final_val(getattr(template, 'coo_col', False), coo_fixed, row_idx_0_based)
                if coo_val not in (None, ''):
                    record_vals['coo'] = str(coo_val).strip()

                # Payment Terms - Char
                pay_fixed = template.payment_terms_fixed if hasattr(template, 'payment_terms_fixed') else None
                pay_val = get_final_val(getattr(template, 'payment_terms_col', False), pay_fixed, row_idx_0_based)
                if pay_val not in (None, ''):
                    record_vals['payment_term'] = str(pay_val).strip()

                # Lead Time - Selection
                lead_fixed = False
                if hasattr(template, 'lead_time_fixed') and template.lead_time_fixed:
                    lead_fixed = dict(template._fields['lead_time_fixed'].selection).get(template.lead_time_fixed)
                lead_val = get_final_val(getattr(template, 'lead_time_col', False), lead_fixed, row_idx_0_based)
                if lead_val not in (None, ''):
                    record_vals['lead_time'] = str(lead_val).strip()

                # Incoterms - ترکیب چند فیلد
                inc_fixed = False
                if hasattr(template, 'incoterm_id') and template.incoterm_id:
                    inc_fixed = template.incoterm_id.name
                    locs = []
                    if template.incoterm_country_id: locs.append(template.incoterm_country_id.name)
                    if template.incoterm_city: locs.append(template.incoterm_city)
                    if locs:
                        inc_fixed += f": {', '.join(locs)}"
                        
                inc_val = get_final_val(getattr(template, 'incoterms_col', False), inc_fixed, row_idx_0_based)
                if inc_val not in (None, ''):
                    record_vals['incoterms'] = str(inc_val).strip()

                # ---------------- ثبت خطا یا محاسبه نهایی ----------------
                if row_errors:
                    validation_errors.append(f"Row {row_index}: " + "; ".join(row_errors))
                else:
                    cur = self.env['res.currency'].browse(record_vals.get('currency_id') or False)
                    converted_price = 0
                    converted_rate = 0

                    if cur == usd_currency:
                        converted_price = record_vals.get('supplier_unit_price', 0)
                        converted_rate = 1
                    elif cur and cur.exists():
                        converted_price = cur._convert(record_vals.get('supplier_unit_price', 0), usd_currency, self.env.company, date.today())
                        converted_rate = cur._get_conversion_rate(cur, usd_currency, self.env.company, date.today())

                    record_vals['converted_price'] = converted_price
                    record_vals['selling_price'] = converted_price * (1 + margin)
                    record_vals['selling_price_2'] = record_vals.get('supplier_unit_price', 0) * (1 + margin)
                    record_vals['min_sell'] = record_vals.get('supplier_unit_price', 0) * (1 + min_margin)
                    record_vals['converted_rate'] = converted_rate

                    temp_records.append(record_vals)

            # =================================================================
            # 5. پایان حلقه و ذخیره‌سازی داده‌ها
            # =================================================================
            
            print ("VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV")
            if validation_errors:
                if getattr(self, 'from_rpc', False):
                    return {"status": "no", "result_error": '\n'.join(validation_errors)}
                self.write({
                    'total_imported': 0,
                    'result_error': '\n'.join(validation_errors),
                    'show_results': True,
                })
                return {
                    'name': _('Import Results'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'sbs.import.wizard',
                    'view_mode': 'form',
                    'res_id': self.id,
                    'view_id': self.env.ref('oe_sbs.view_import_wizard_results').id,
                    'target': 'new',
                    'context': self.env.context,
                }
            
            import_number = self.env['ir.sequence'].next_by_code('sbs.import.sequence') or _('New')
            Product = self.env['product.template']

            print ("tttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttt")
            for rec in temp_records:
                
                # --- پیدا کردن تامین‌کننده (داینامیک از روی فایل اکسل) ---
                if not rec.get('supplier_id') and rec.get('supplier_code'):
                    partner = self.env['res.partner'].search([('partner_code', '=', str(rec['supplier_code']).strip())], limit=1)
                    if partner:
                        rec['supplier_id'] = partner.id
                        rec['supplier_name'] = partner.name
                # --------------------------------------------------------
                
                product = Product.search([('barcode', '=', rec['ean'])], limit=1)
                if product:
                    rec['product_id'] = product.id
                    product.sudo().write({'is_published': True})
                else:
                    product = Product.create({
                        'name': rec['product_name'],
                        'barcode': rec['ean'],
                        'type': 'consu',
                        'is_storable': True, 
                        'tracking': 'lot',
                        'creation_method': 'sbs',
                        'is_published': True, 
                    })
                    rec['product_id'] = product.id

                # ── UOM SYNC ──
                case_size = rec.get('case_size', 0)
                if case_size and int(case_size) > 0:
                    uom = self._get_or_create_uom(case_size)
                    if uom:
                        rec['uom_id'] = uom.id
                        self._sync_uom_to_product(product, uom)

                rec['import_number'] = import_number
                rec['document_id'] = self.document_id.id if self.from_doc else False
                SBSData.create(rec)
                imported_count += 1
            
            print ("wwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwww")
            
            self.write({
                'import_number': import_number,
                'total_imported': imported_count,
                'result_error': '',
                'show_results': True
            })
            print ("aftrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr")

            if ICP.get_param('oe_sbs.auto_rank') == 'True' and imported_count > 0:
                self.env['sbs.data'].action_rank_products()

            print ("CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCcc")
            
            cleanup_msg = ''
            if ICP.get_param('oe_sbs.auto_cleanup_old_lists') == 'True' and imported_count > 0:
                cleanup_summary = self.env['sbs.data'].action_cleanup_old_lists(
                    new_import_number=import_number,
                    new_import_date=fields.Date.today()
                )
                if cleanup_summary.get('deleted_lists', 0) > 0:
                    cleanup_msg = (
                        f"\n\n🧹 Cleanup Summary:\n"
                        f"Supplier: {cleanup_summary.get('supplier_name', '')}\n"
                        f"Old lists removed: {cleanup_summary['deleted_lists']}\n"
                        f"Records deleted: {cleanup_summary['total_records_deleted']}"
                    )

            self.write({'cleanup_msg': cleanup_msg})
            
            if getattr(self, 'from_rpc', False):
                return {"status": "ok", 'import_number': import_number, 'total_imported': imported_count, 'cleanup_msg': cleanup_msg}

            print ("REEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEee")
            return {
                'name': _('Import Results'),
                'type': 'ir.actions.act_window',
                'res_model': 'sbs.import.wizard',
                'view_mode': 'form',
                'res_id': self.id,
                'view_id': self.env.ref('oe_sbs.view_import_wizard_results').id,
                'target': 'new',
                'context': self.env.context,
            }

        except Exception as e:
            raise UserError(_('Error importing file: %s') % str(e))    



    def action_new_import(self):
        """Create a new import wizard for another import"""
        return {
            'name': _('Import Excel Data'),
            'type': 'ir.actions.act_window',
            'res_model': 'sbs.import.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('oe_sbs.view_import_wizard_form').id,
            'target': 'new',
            'context': {},
        }
    
    def action_view_imported(self):
        """View imported records in the main SBS data model"""
        return {
            'name': _('Imported Data'),
            'type': 'ir.actions.act_window',
            'res_model': 'sbs.data',
            'view_mode': 'list,form',
            'domain': [('import_number', '=', self.import_number)],
            'context': {'search_default_group_by_ean': 1},
            'target': 'current',
        }