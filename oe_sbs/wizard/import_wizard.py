from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
from io import BytesIO
from datetime import datetime,date,timedelta
import re
from openpyxl import load_workbook,Workbook
from unidecode import unidecode
import json
import io
import zipfile

import re


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

            # ---- استخراج داده‌ها به یک لیست دیکشنری مشترک ----
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
                   # print (file_content)
                    is_json = True
                else:
                    raise UserError(_('Unsupported document type: %s') % mimetype)

            rows_list = []



            if is_json:
                data = file_content if isinstance(file_content, dict) else json.loads(file_content)
                sheets = data.get("sheets", [])
                sheet = next((s for s in sheets if s["name"].strip().lower() == "climax"), sheets[0])
                cells = sheet.get("cells", {})
                
                print("celcccccccccccccccccccccccccccccccccccccccccsss")
                print(cells)

                # 🔹 تابع کمکی برای استخراج مقدار
                def get_cell_value(cell_data):
                    """استخراج مقدار سلول - هم برای dict و هم برای string"""
                    if isinstance(cell_data, dict):
                        return cell_data.get("content", "")
                    return str(cell_data) if cell_data else ""
                
                # هدرها در ردیف 1 (A1, B1, ...)
                headers = []
                col = 1
                while True:
                    col_letter = chr(64 + col)
                    key = f"{col_letter}1"
                    if key not in cells:
                        break
                    headers.append(get_cell_value(cells[key]).strip().lower())
                    col += 1

                # داده‌ها از ردیف 2 به بعد
                rows_list = []
                max_row = sheet.get("rowNumber", 100)
                for row_num in range(2, max_row + 1):
                    row_dict = {}
                    has_data = False  # 🔹 تغییر نام به has_data (واضح‌تر)
                    
                    for idx, header in enumerate(headers, start=1):
                        col_letter = chr(64 + idx)
                        key = f"{col_letter}{row_num}"
                        value = get_cell_value(cells.get(key, ""))

                        # 🔹 اصلاح تاریخ فقط برای ستون‌های موردنظر
                        if header in ["import date", "offer validity", "end date"]:
                            if value:  # فقط اگر مقدار داشت
                                print("hhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh")
                                print(value)
                                value = self.excel_date_to_str(value)
                                print(value)

                        row_dict[header] = value
                        
                        # 🔹 چک کردن تمام ستون‌ها (نه فقط تاریخ‌ها)
                        if value and str(value).strip():
                            has_data = True
                    
                    # 🔹 فقط اگر حداقل یک سلول پر بود، ردیف را اضافه کن
                    if has_data:
                        rows_list.append(row_dict)
                    else:
                        print(f"⚠️ ردیف {row_num} خالی است - رد شد")

                            #print("Headers:", headers)
                            #print("Rows:", rows_list)


            else:
                workbook = load_workbook(filename=BytesIO(file_content), data_only=True)
                
                # انتخاب شیت "climax" اگر موجود باشد
                sheet_name = next((n for n in workbook.sheetnames if n.strip().lower() == "climax"), workbook.sheetnames[0])
                sheet = workbook[sheet_name]

                # استخراج هدر
                headers = [str(cell.value).strip().lower() if cell.value else '' for cell in sheet[1]]

                # استخراج داده‌ها
                for row in sheet.iter_rows(min_row=2):
                    print ("POOOOOOOOOOOOOOOOOOOOO")
                    print(row)
                    row_dict = {headers[idx]: cell for idx, cell in enumerate(row)}
                    rows_list.append(row_dict)

            print ("jjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjj")
            # ستون‌های الزامی ساده
            required_columns = ['import date', 'description', 'supplier unit price', 'supplier name']
            missing_columns = [col for col in required_columns if col not in headers]

            # ستون‌هایی که حداقل یکی باید وجود داشته باشد
            if 'ean' not in headers and 'barcode' not in headers:
                missing_columns.append('ean or barcode')
            if 'end date' not in headers and 'offer validity' not in headers:
                missing_columns.append('end date or offer validity')

            if missing_columns:
                raise UserError(_('Missing required columns: %s') % ", ".join(missing_columns))


            print ("KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK")

            column_mapping = {
                'unit/case': 'case_size',
                'case/layer': 'layer',
                'case/pallet': 'pallet',
                'case size': 'case_size',
                'layer': 'layer',
                'pallet': 'pallet',
                'note': 'note',
                'coo': 'coo',
                'lead time': 'lead_time',
                #'moq': 'moq',
               # 'mov':'mov',
               # 'available qty':'availabale_qty',
                #'available units':'availabale_qty',
                'incoterms':'incoterms',
                #'t1/t2':'t1_t2',
                'payment terms':'payment_term',
                'supplier code':'supplier_code'
            }

            SBSData = self.env['sbs.data']
            existing_file = SBSData.with_context(prefetch_fields=False).search([('excel_filename', '=', self.file_name)])
            if existing_file:
                print ("fnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn")
                print (self.file_name)

                raise UserError(_('File Already Exist!'))

            print ("rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr")
            valid_currency_ids = self.env['res.currency'].search([]).ids
            ICP = self.env['ir.config_parameter'].sudo()
            margin = float(ICP.get_param('oe_sbs.default_profit_margin', '8')) / 100
            min_margin = float(ICP.get_param('oe_sbs.min_profit_margin', '7')) / 100
            usd_currency = self.env.ref('base.USD')

            print (rows_list)
            for row_index, row_data in enumerate(rows_list, start=2):
                record_vals = {'excel_filename': self.file_name}
                row_errors = []

                # ---------------- import date ----------------

                print ("import dateimport dateimport date")
                print (row_data.get('import date'))
                import_date_cell = row_data.get('import date')
                val = import_date_cell.value if hasattr(import_date_cell, 'value') else import_date_cell
                try:
                    if val:
                        if isinstance(val, datetime):
                            date_obj = val
                        else:
                            parsed_date = None
                            for fmt in ( "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):  # فرمت‌های قابل قبول
                                try:
                                    parsed_date = datetime.strptime(str(val), fmt)
                                    break
                                except ValueError:
                                    continue

                            if not parsed_date:
                                raise ValueError("Unsupported date format")

                            date_obj = parsed_date
                            #date_obj = datetime.strptime(str(val), "%d-%b-%Y")

                        if date_obj.date() > date.today():
                            row_errors.append("Import date cannot be in the future")
                        else:
                            record_vals['import_date'] = date_obj.isoformat()
                    else:
                        row_errors.append("Invalid import date (expected DD-Mon-YYYY, e.g. 19-Sep-2025)")
                except Exception:
                    row_errors.append("Invalid import date (expected DD-Mon-YYYY, e.g. 19-Sep-2025)")
                # ---------------- EAN / Barcode ----------------
                ean_val = ''
                val = row_data.get('ean') or row_data.get('barcode')
                val = val.value if hasattr(val, 'value') else val
                ean_val = str(val).strip() if val else ''

                if not ean_val:
                    row_errors.append("Missing EAN (barcode)")
                elif not ean_val.isdigit():
                    row_errors.append(f"Invalid EAN (non-numeric): {ean_val}")
                elif len(ean_val) > 13:
                    row_errors.append(f"Invalid EAN length > 13: {ean_val}")
                else:
                    # اگر کوتاه‌تر از ۱۳ بود با صفر پر می‌شود
                    ean_val = ean_val.zfill(13)
                    record_vals['ean'] = ean_val


                # ---------------- Product Name ----------------
                desc_cell = row_data.get('description')
                val = desc_cell.value if hasattr(desc_cell, 'value') else desc_cell
                if not val:
                    row_errors.append("Missing product name")
                else:
                    record_vals['product_name'] = unidecode(str(val).strip()).title()

                # ---------------- Supplier Name ----------------
                supplier_cell = row_data.get('supplier name')
                val = supplier_cell.value if hasattr(supplier_cell, 'value') else supplier_cell
                if not val:
                    row_errors.append("Missing supplier name")
                else:
                    record_vals['supplier_name'] = str(val).strip().title()

                # ---------------- Supplier Code ----------------
                #supplier_code_cell = row_data.get('supplier code')
                #val = supplier_code_cell.value if hasattr(supplier_code_cell, 'value') else supplier_code_cell
                #if not val:
                #    row_errors.append("Missing supplier code")
                #else:
                #    record_vals['supplier_code'] = str(val).strip()

                # ---------------- Price & Currency ----------------
                price_cell = row_data.get('supplier unit price')
                val = price_cell.value if hasattr(price_cell, 'value') else price_cell
                #try:
                price_value, currency_id = self._parse_accounting_number(price_cell)
                if not currency_id or currency_id not in valid_currency_ids or price_value is None or price_value == 0:
                    row_errors.append("Invalid price or currency")
                else:
                    record_vals['supplier_unit_price'] = abs(price_value)
                    record_vals['currency_id'] = currency_id
                #except Exception:
                #    row_errors.append("Invalid price or currency")

                # ---------------- End Date / Offer Validity ----------------

                end_cell = row_data.get('end date') or row_data.get('offer validity')
                val = end_cell.value if hasattr(end_cell, 'value') else end_cell

                try:
                    if val:
                        if isinstance(val, datetime):
                            date_obj = val
                        else:
                            # فقط این فرمت معتبره: DD-Mon-YYYY (مثلاً 19-Sep-2025)
                            parsed_date = None
                            for fmt in ( "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):  # فرمت‌های قابل قبول
                                try:
                                    parsed_date = datetime.strptime(str(val), fmt)
                                    break
                                except ValueError:
                                    continue

                            if not parsed_date:
                                raise ValueError("Unsupported date format")

                            date_obj = parsed_date
                            #date_obj = datetime.strptime(str(val), "%d-%b-%Y")

                        record_vals['end_date'] = date_obj.isoformat()
                    else:
                        row_errors.append(f"Row {row_index}: Invalid offer validity format (expected DD-Mon-YYYY)")
                except Exception:
                    row_errors.append(f"Row {row_index}: Invalid offer validity format (expected DD-Mon-YYYY)")




                # ---------- بررسی اعتبار تاریخ‌ها ----------
                today = date.today()
                if 'end_date' in record_vals and record_vals['end_date']:
                    end_date1 = datetime.strptime(record_vals['end_date'], '%Y-%m-%dT%H:%M:%S').date()
                    if 'import_date' in record_vals and record_vals['import_date']:
                        import_date1 = datetime.strptime(record_vals['import_date'], '%Y-%m-%dT%H:%M:%S').date()
                        if end_date1 <= import_date1:
                            row_errors.append(f"Row {row_index}: Offer validity is earlier than import date")
                    record_vals['is_expired'] = bool(end_date1 < today)
                    if end_date1 < today:
                        row_errors.append(f"Row {row_index}: Offer validity date is expired")

                # ---------------- MOQ & MOV ----------------
                moq_val = row_data.get('moq')
                mov_val = row_data.get('mov')
                moq_val = moq_val.value if hasattr(moq_val, 'value') else moq_val
                mov_val = mov_val.value if hasattr(mov_val, 'value') else mov_val

                if not moq_val and not mov_val:
                    row_errors.append(f"Row {row_index}: At least one of MOQ or MOV must have value")
                if moq_val and isinstance(moq_val, str) and re.search(r'(€|\$|£|aed)', moq_val, re.IGNORECASE):
                    row_errors.append(f"Row {row_index}: MOQ must not contain currency")
                if mov_val:
                    mov_raw = str(mov_val).strip()
                    m = re.search(r'(€|\$|£|aed)', mov_raw, re.IGNORECASE)
                    if not m:
                        row_errors.append(f"Row {row_index}: MOV must contain a currency symbol (€, $, £ or AED)")
                    else:
                        mov_symbol = m.group(0).upper()
                        body = re.sub(r'(€|\$|£|aed)\s*', '', mov_raw, flags=re.IGNORECASE)
                        body = re.sub(r'[^0-9\.,kK]', '', body)
                        body = body.replace('K', 'k')
                        if body.count('k') > 1:
                            row_errors.append(f"Row {row_index}: MOV contains multiple 'k' characters")
                        else:
                            if 'k' in body and not body.endswith('k'):
                                body = re.sub(r'k', '', body) + 'k'
                            if not re.search(r'\d', body):
                                row_errors.append(f"Row {row_index}: MOV must contain at least one digit")
                            else:
                                record_vals['mov'] = f"{mov_symbol}{body}"
                                # بررسی تطابق نماد MOV با currency_id
                                cur_symbol = None
                                try:
                                    cur = self.env['res.currency'].browse(record_vals.get('currency_id') or False)
                                except Exception:
                                    cur = False
                                if cur and cur.exists() and cur.symbol in ('$', '€', '£', 'AED'):
                                    cur_symbol = cur.symbol
                                else:
                                    try:
                                        cur_symbol = (
                                            '$' if record_vals.get('currency_id') == self.env.ref('base.USD').id else
                                            '€' if record_vals.get('currency_id') == self.env.ref('base.EUR').id else
                                            '£' if record_vals.get('currency_id') == self.env.ref('base.GBP').id else
                                            'AED' if record_vals.get('currency_id') == self.env.ref('base.AED').id else None
                                        )
                                    except Exception:
                                        cur_symbol = None
                                if cur_symbol and mov_symbol != cur_symbol:
                                    row_errors.append(
                                        f"Row {row_index}: MOV currency ({mov_symbol}) does not match supplier unit price currency ({cur_symbol})"
                                    )

                # ---------------- Available QTY ----------------
                avail_cell = row_data.get('available qty') or row_data.get('available units')
                val = avail_cell.value if hasattr(avail_cell, 'value') else avail_cell
                if val not in (None, ''):
                    try:
                        val_str = str(val).strip()
                        if re.search(r'(€|\$|£|aed)', val_str, re.IGNORECASE):
                            row_errors.append(f"Row {row_index}: Available Units must not contain currency symbols")
                        else:
                            record_vals['availabale_qty'] = float(val_str)
                    except ValueError:
                        row_errors.append(f"Row {row_index}: Available Units must be numeric")

                # ---------------- T1/T2 ----------------
                t1t2_cell = row_data.get('t1/t2')
                val = t1t2_cell.value if hasattr(t1t2_cell, 'value') else t1t2_cell
                if val:
                    tval = str(val).strip().upper()
                    if tval not in ['T1', 'T2']:
                        row_errors.append(f"Row {row_index}: T1-T2 must be empty or T1/T2")
                    else:
                        record_vals['t1_t2'] = tval

                # ---------------- سایر فیلدهای optional ----------------
                for excel_field, odoo_field in column_mapping.items():
                    if excel_field in required_columns:
                        continue
                    cell = row_data.get(excel_field)
                    val = cell.value if hasattr(cell, 'value') else cell
                    if val not in (None, ''):
                        if odoo_field in ['case_size', 'layer', 'pallet']:
                            try:
                                record_vals[odoo_field] = int(float(val))
                            except:
                                record_vals[odoo_field] = 0
                        else:
                            record_vals[odoo_field] = str(val).strip()

                # ---------------- ثبت خطا یا رکورد ----------------
                if row_errors:
                    validation_errors.append(f"Row {row_index}: " + "; ".join(row_errors))
                else:
                    # ---- محاسبه قیمت تبدیل شده و selling price ----
                    cur = False
                    try:
                        cur = self.env['res.currency'].browse(record_vals.get('currency_id') or False)
                    except Exception:
                        cur = False
                    converted_price = 0
                    converted_rate=0

                    if cur == usd_currency:
                        converted_price = record_vals.get('supplier_unit_price', 0)
                        converted_rate=1
                    elif cur:
                        #converted_price = usd_currency._convert(record_vals.get('supplier_unit_price', 0), cur, self.env.company, date.today())
                        converted_price = cur._convert(record_vals.get('supplier_unit_price', 0), usd_currency, self.env.company, date.today())
                        converted_rate= cur._get_conversion_rate(cur, usd_currency, self.env.company, date.today())


                    record_vals['converted_price'] = converted_price
                    record_vals['selling_price'] = converted_price * (1 + margin)
                    record_vals['selling_price_2'] = record_vals.get('supplier_unit_price', 0) * (1 + margin)
                    record_vals['min_sell'] = record_vals.get('supplier_unit_price', 0) * (1 + min_margin)
                    record_vals['converted_rate'] = converted_rate

                    temp_records.append(record_vals)

            # ---------------- اگر خطا بود ----------------
            if validation_errors:
                if self.from_rpc:
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
            # ثبت رکوردها
            import_number = self.env['ir.sequence'].next_by_code('sbs.import.sequence') or _('New')
            for rec in temp_records:
                
                ##############################################
                
                Product = self.env['product.template']
                product = Product.search([('barcode', '=', rec['ean'])], limit=1)
                if product:
                    rec['product_id'] = product.id
                else:
                    product = Product.create({
                        'name': rec['product_name'],
                        'barcode': rec['ean'],
                        'type': 'consu',  # یا 'consu' یا 'service' بسته به نیاز
                        'is_storable': True, 
                        'tracking':'lot',
                        'creation_method':'sbs',
                    })
                    rec['product_id'] = product.id
                ############################################

                if 'supplier_code'  in rec:
                    Partner = self.env['res.partner'].search([('partner_code', '=',  rec['supplier_code'])], limit=1)
                    if Partner:
                        rec['supplier_id'] = Partner.id

                ############################################
                rec['import_number'] = import_number
                rec['document_id'] = self.document_id.id
                SBSData.create(rec)
                imported_count += 1

            self.write({
                'import_number': import_number,
                'total_imported': imported_count,
                'result_error': '',
                'show_results': True
            })

            #if imported_count > 0:
                #imported_records = SBSData.search([('import_number', '=', import_number)])
                #imported_records._compute_selling_prices()

            print ("rankkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk")
            # print (self.env['ir.config_parameter'].sudo().get_param('oe_sbs.auto_rank'))
            if ICP.get_param('oe_sbs.auto_rank') == 'True' and imported_count > 0:
                print ("rankkkk2222222222222222222222222222222222222222222222222222222222222222222")

                self.env['sbs.data'].action_rank_products()

            
            
            cleanup_msg=''
            # Auto Cleanup Old Lists
            if ICP.get_param('oe_sbs.auto_cleanup_old_lists') == 'True' and imported_count > 0:
                #try:
                    cleanup_summary = self.env['sbs.data'].action_cleanup_old_lists(
                        new_import_number=import_number,
                        new_import_date= fields.Date.today()
                    )
                    
                    # اضافه کردن به پیام
                    if cleanup_summary.get('deleted_lists', 0) > 0:
                        cleanup_msg = (
                            f"\n\n🧹 Cleanup Summary:\n"
                            f"Supplier: {cleanup_summary['supplier_name']}\n"
                            f"Old lists removed: {cleanup_summary['deleted_lists']}\n"
                            f"Records deleted: {cleanup_summary['total_records_deleted']}"
                        )
                       
                        
                #except Exception as e:
                #   print(f"Auto cleanup failed: {str(e)}")
                    # عدم توقف فرآیند اصلی

            self.write({'cleanup_msg': cleanup_msg})
            
            
            
            
            
            
            if self.from_rpc:
                return {"status": "ok",  'import_number': import_number,'total_imported': imported_count,'cleanup_msg': cleanup_msg}

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
            print ("exceptionnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn")
            print (str(e))
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