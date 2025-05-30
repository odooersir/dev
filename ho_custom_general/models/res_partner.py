# -*- coding: utf-8 -*-

from odoo import fields, models
class ResPartner(models.Model):
    _inherit = "res.partner"

    def _get_complete_name(self):
        self.ensure_one()

        displayed_types = self._complete_name_displayed_types
        type_description = dict(self._fields['type']._description_selection(self.env))

        name = self.name or ''

        #if not self.is_company:

        #    name= str(self.first_name) or '' +'' + str(self.last_name) or ''

        '''
        if self.company_name or self.parent_id:
            if not name and self.type in displayed_types:
                name = type_description[self.type]
            if not self.is_company:
                name = f"{self.commercial_company_name or self.sudo().parent_id.name}, {name}"
        '''
        return name.strip()


 

    first_name = fields.Char(string='First Name')
    last_name = fields.Char(string='Last Name')
    business_name = fields.Char(string='Business Name')
    file_number = fields.Char(string='File Number')

    citizen_id = fields.Many2one('res.country', string='citizen', ondelete='restrict')
    passport_number = fields.Char(string='Passport Number')
    comprehensive_code = fields.Char(string='Comprehensive Code')
    national_code = fields.Char(string='National Code')
    father_name = fields.Char(string='Father Name')
    birth_date = fields.Date(string='Birthdate')


      
    national_identity = fields.Char(string='National ID')
    register_number = fields.Char(string='Register Number')
    
    company_register_type_id =fields.Many2one('res.partner.companyregistertype', string='Company Type', ondelete='restrict') 
    company_state_id = fields.Many2one('res.partner.companystate', string='Company State', ondelete='restrict')
    
    establishment_date = fields.Date(string='Establishment Date')
    presenter= fields.Char(string='Presenter')
    telegram= fields.Char(string='telegram')
    instagram= fields.Char(string='instagram')
    linkedin= fields.Char(string='linkedin')
    board_number= fields.Integer(string='Board Number')

    newspaper = fields.Char(string='Newspaper')

    board_start= fields.Date(string='Board Start')
    board_end= fields.Date(string='Board End')
    fiscal_start= fields.Char(string='Fiscal Year Start')

    inspector_select= fields.Date(string='Inspector Select')

    approval_financial_statements= fields.Date(string='Approval Financial Statements')


    signatory_registers= fields.Char(string='Signatory of the Registers')
    signatory_papers= fields.Char(string='Signatory of the papers')

    company_capital=fields.Char(string="Capital of the Company")

    share_value=fields.Char(string="Share Value")

    share_number=fields.Integer(string="Share Number")

    shareholder_number=fields.Integer(string="Shareholder Number")

    #industry=fields.Char(string='Industry')
    #industry_id = fields.Many2one('res.partner.industry', string='Industry', ondelete='restrict')

    activity_subject_id=fields.Many2one('res.partner.activitysubject', string='Activity Subject', ondelete='restrict')

    goods_service_provided=fields.Char(string='Goods Or Services to be Provided')

    goods_service_required=fields.Char(string='Goods Or Services to be Required')


    phone2 = fields.Char(string='Phone',unaccent=False)
    phone3 = fields.Char(string='Phone',unaccent=False)

    mobile2 = fields.Char(string='Mobile', unaccent=False)
    mobile3 = fields.Char(string='Mobile',unaccent=False)
    internal_number = fields.Char(string='Internal Number',unaccent=False)

    knowing_method_id = fields.Many2one('res.partner.knowingmethod', string='Knowing Method', ondelete='restrict')

    position = fields.Char(string='Position')
    position_start = fields.Date(string='Position Start')

    position_end = fields.Date(string='Position End')


    
    study_field_id = fields.Many2one('res.partner.studyfield', string='Study Field', ondelete='restrict')
    
    education_degree =  fields.Selection([
            ('diploma', 'Diploma'),
            ('advanced_diploma', 'Advanced Diploma'),
            ('bachelor', 'Bachelor'),
            ('master', 'Master'),
            ('doctorate', 'Doctorate'),
            ('post_doctorate', 'Post Doctorate'),
        ],string='Education Degree')
    
    
    year_degree = fields.Char(string='Year Degree')
    insurance_number= fields.Char(string='Insurance Number')
    father_name= fields.Char(string='Father Name')

    birth_place= fields.Char(string='Birth Place')

    token_signature_holder = fields.Many2one('res.partner',string='Token Signature Holder') 
    
    last_ordinary_assembly=fields.Date(string='Last Ordinary Assembly')
    last_extension_inspector=fields.Date(string='Last Extension Inspector')
    approval_financial_statements= fields.Date(string='Approval Financial Statements') 



    company_member_ids = fields.One2many('res.partner.member','partner_id',  string='Company Member', copy=True,)

    _sql_constraints = [

        ('national_id_uniq', 'unique (national_identity)', "National ID already exists!"),
        ('national_code_uniq', 'unique (national_code)', "National Code already exists!"),
        ('mobile_uniq', 'unique (mobile)', "Mobile already exists!"),

    ]

class ResPartnerStudyField(models.Model):
    _description = 'Study Field'
    _name = "res.partner.studyfield"
    _order = "name"

    name = fields.Char('Name', translate=True)
    active = fields.Boolean('Active', default=True)


class ResPartnerKnowingMethod(models.Model):
    _description = 'Knowing Method'
    _name = "res.partner.knowingmethod"
    _order = "name"

    name = fields.Char('Name', translate=True)
    active = fields.Boolean('Active', default=True)


class ResPartnerCompanyRegisterType(models.Model):
    _description = 'company Register Type'
    _name = "res.partner.companyregistertype"
    _order = "name"

    name = fields.Char('Name', translate=True)
    active = fields.Boolean('Active', default=True)


class ResPartnerCompanyState(models.Model):
    _description = 'Company State'
    _name = "res.partner.companystate"
    _order = "name"

    name = fields.Char('Name', translate=True)
    active = fields.Boolean('Active', default=True)

class ResPartnerActivitySubject(models.Model):
    _description = 'Activity Subject'
    _name = "res.partner.activitysubject"
    _order = "name"

    name = fields.Char('Name', translate=True)
    active = fields.Boolean('Active', default=True)



    
class PartnerTaskLog(models.Model):
    _name = "partner.task.log"

    partner_id = fields.Many2one('res.partner', string='Customer')
    task_id = fields.Many2one('project.task', string='Task')
    change_date = fields.Datetime(string='Change Date')
    state = fields.Selection([('1_done', 'Done')])
    chang_list=fields.Text(string='Change List')


class MemberPosition(models.Model):
    _description = 'Member Position'
    _name = "member.position"
    _order = "name"

    name = fields.Char('Name', translate=True)
    active = fields.Boolean('Active', default=True)


















