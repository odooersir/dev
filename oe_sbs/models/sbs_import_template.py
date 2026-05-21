from odoo import models, fields, api
import re

class SbsMovTerm(models.Model):
    _name = 'sbs.mov.term'
    _description = 'MOV Terms'

    name = fields.Char(string='Name', required=True)

class SbsImportTemplate(models.Model):
    _name = 'sbs.import.template'
    _description = 'SBS Import Template'

    name = fields.Char(string='Template Name', required=True)
    supplier_id = fields.Many2one('res.partner', string='Supplier')
    active = fields.Boolean(default=True)

    sheet_name = fields.Char(string="Sheet Name", help="If left empty, the first sheet will be used.")


    header_row = fields.Integer(string='Header Row', default=1, help='Row number where headers are located')

   
    #signature_cell = fields.Char(string='Signature Cell', required=True, default='A1', help='e.g., A1')
    #signature_text = fields.Char(string='Signature Text', required=True)

    # 4. فیلدهای Lead Time و Offer Validity
    WEEK_SELECTION = [
        ('1', '1 Week'),
        ('2', '2 Weeks'),
        ('3', '3 Weeks'),
        ('4', '4 Weeks'),
        ('5', '5 Weeks'),
        ('6', '6 Weeks'),
        ('7', '7 Weeks'),
        ('8', '8 Weeks'),
    ]


    # EAN
    ean_col = fields.Char(string='EAN Cell', required=True, help='e.g., A3')
    ean_header = fields.Char(string='EAN Header', help='Expected column name in Excel file, e.g., "EAN"')
    ean_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='EAN Type', default='text', help='Expected data type for validation')

    # Product Name
    product_name_col = fields.Char(string='Product Name Cell')
    product_name_header = fields.Char(string='Product Name Header', help='Expected column name in Excel file')
    product_name_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Product Name Type', default='text', help='Expected data type for validation')

    # Price
    price_col = fields.Char(string='Price Cell', required=True)
    price_header = fields.Char(string='Price Header', help='Expected column name in Excel file, e.g., "Price"')
    price_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Price Type', default='float', help='Expected data type for validation')

    # Supplier Code
    supplier_code_col = fields.Char(string='Supplier Code Cell')
    supplier_code_header = fields.Char(string='Supplier Code Header', help='Expected column name in Excel file')
    supplier_code_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Supplier Code Type', default='text', help='Expected data type for validation')

    # Brand
    brand_col = fields.Char(string='Brand Cell')
    brand_header = fields.Char(string='Brand Header', help='Expected column name in Excel file')
    brand_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Brand Type', default='text', help='Expected data type for validation')

    # Size
    size_col = fields.Char(string='Size Cell')
    size_header = fields.Char(string='Size Header', help='Expected column name in Excel file')
    size_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Size Type', default='text', help='Expected data type for validation')

    # Case Size
    case_size_col = fields.Char(string='Case Size Cell')
    case_size_header = fields.Char(string='Case Size Header', help='Expected column name in Excel file')
    case_size_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Case Size Type', default='integer', help='Expected data type for validation')

    # Layer
    layer_col = fields.Char(string='Layer Cell')
    layer_header = fields.Char(string='Layer Header', help='Expected column name in Excel file')
    layer_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Layer Type', default='integer', help='Expected data type for validation')

    # Pallet
    pallet_col = fields.Char(string='Pallet Cell')
    pallet_header = fields.Char(string='Pallet Header', help='Expected column name in Excel file')
    pallet_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Pallet Type', default='integer', help='Expected data type for validation')

    unit_per_layer_col = fields.Char(string='Unit/Layer Cell')
    unit_per_layer_header = fields.Char(string='Unit/Layer Header')

    unit_per_pallet_col = fields.Char(string='Unit/Pallet Cell')
    unit_per_pallet_header = fields.Char(string='Unit/Pallet Header')

    hs_code_col = fields.Char(string='HS Code Cell')
    hs_code_header = fields.Char(string='HS Code Header')
    # MOQ
    moq_col = fields.Char(string='MOQ Cell')
    moq_header = fields.Char(string='MOQ Header', help='Expected column name in Excel file, e.g., "MOQ"')
    moq_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='MOQ Type', default='integer', help='Expected data type for validation')
    moq_fixed = fields.Char(string='Fixed MOQ')

    # MOV
    mov_col = fields.Char(string='MOV Cell')
    mov_header = fields.Char(string='MOV Header', help='Expected column name in Excel file, e.g., "MOV"')
    mov_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='MOV Type', default='float', help='Expected data type for validation')
    #mov_fixed = fields.Char(string='Fixed MOV')
    mov_fixed = fields.Many2one('sbs.mov.term', string="Fixed MOV")

    # Available Qty
    available_qty_col = fields.Char(string='Available Qty Cell')
    available_qty_header = fields.Char(string='Available Qty Header', help='Expected column name in Excel file')
    available_qty_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Available Qty Type', default='integer', help='Expected data type for validation')

    # Currency
    currency_col = fields.Char(string='Currency Cell')
    currency_header = fields.Char(string='Currency Header', help='Expected column name in Excel file')
    currency_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Currency Type', default='text', help='Expected data type for validation')
    currency_fixed_id = fields.Many2one('res.currency', string='Fixed Currency')

    # Offer Validity
    offer_validity_col = fields.Char(string='Offer Validity Cell')
    offer_validity_header = fields.Char(string='Offer Validity Header', help='Expected column name in Excel file')
    offer_validity_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Offer Validity Type', default='date', help='Expected data type for validation')
    #offer_validity_fixed = fields.Date(string='Fixed Offer Validity')
    offer_validity_fixed = fields.Selection(WEEK_SELECTION, string="Fixed Validity")

    # COO
    coo_col = fields.Char(string='COO Cell')
    coo_header = fields.Char(string='COO Header', help='Expected column name in Excel file')
    coo_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='COO Type', default='text', help='Expected data type for validation')
    #coo_fixed = fields.Char(string='Fixed COO')
    coo_fixed = fields.Many2one('res.country', string="Fixed COO")

    

    
    # Lead Time
    lead_time_col = fields.Char(string='Lead Time Cell')
    lead_time_header = fields.Char(string='Lead Time Header', help='Expected column name in Excel file')
    lead_time_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Lead Time Type', default='text', help='Expected data type for validation')
    #lead_time_fixed = fields.Char(string='Fixed Lead Time')
    lead_time_fixed = fields.Selection(WEEK_SELECTION, string="Fixed Lead Time")

    # Payment Terms
    payment_terms_col = fields.Char(string='Payment Terms Cell')
    payment_terms_header = fields.Char(string='Payment Terms Header', help='Expected column name in Excel file')
    payment_terms_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Payment Terms Type', default='text', help='Expected data type for validation')
    payment_terms_fixed = fields.Char(string='Fixed Payment Terms')

    # متد برای دکمه پر کردن خودکار شرایط پرداخت
    def action_set_default_payment_term(self):
        for rec in self:
            rec.payment_terms_fixed = "30% Deposite, Balance before shipping"


    # Incoterms
    incoterms_col = fields.Char(string='Incoterms Cell')
    incoterms_header = fields.Char(string='Incoterms Header', help='Expected column name in Excel file')
    incoterms_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Incoterms Type', default='text', help='Expected data type for validation')
    #incoterms_fixed = fields.Char(string='Fixed Incoterms')

    incoterm_id = fields.Many2one('account.incoterms', string="Fixed Incoterm")
    incoterm_country_id = fields.Many2one('res.country', string="Incoterm Country")
    incoterm_city = fields.Char(string="Incoterm City")

    # T1/T2
    t1_t2_col = fields.Char(string='T1/T2 Cell')
    t1_t2_header = fields.Char(string='T1/T2 Header', help='Expected column name in Excel file')
    t1_t2_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='T1/T2 Type', default='text', help='Expected data type for validation')
    t1_t2_fixed = fields.Selection([('T1', 'T1'), ('T2', 'T2')], string='Fixed T1/T2')

    # Note
    note_col = fields.Char(string='Note Cell')
    note_header = fields.Char(string='Note Header', help='Expected column name in Excel file')
    note_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Note Type', default='text', help='Expected data type for validation')
    note_fixed = fields.Char(string='Fixed Note')
    '''
    # Import Date
    import_date_col = fields.Char(string='Import Date Cell', help='e.g., A3')
    import_date_header = fields.Char(string='Import Date Header', help='Expected column name in Excel file')
    import_date_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='Import Date Type', default='date', help='Expected data type for validation')

    # End Date
    end_date_col = fields.Char(string='End Date / Validity Cell', help='e.g., G3')
    end_date_header = fields.Char(string='End Date Header', help='Expected column name in Excel file')
    end_date_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
    ], string='End Date Type', default='date', help='Expected data type for validation')
    '''