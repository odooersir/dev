from odoo import fields, models,api
import json
from datetime import date, datetime
from odoo.exceptions import UserError


class Task(models.Model):
    _inherit = "project.task"


    po_company_id =fields.Many2one('res.partner', string='Company', ondelete='restrict') 
    agent_id =fields.Many2one('res.partner', string='Agent', ondelete='restrict') 


    request_type =fields.Many2one('task.request.type', string='Request Type', ondelete='restrict') 
    previous_request_type =fields.Many2one('task.request.type', string='Previous Request Type', ondelete='restrict') 




    setting_date = fields.Datetime(string='Setting Date')
    sending_date = fields.Datetime(string='Sending Date')
    receive_date = fields.Datetime(string='Receive Date')
    end_reg_date = fields.Datetime(string='End Registration Date')   
    post_doc_date = fields.Datetime(string='Post Document Date')
    pre_ad_date = fields.Datetime(string='Pre Ad Date')
    fix_problem_date = fields.Datetime(string='Fix Problem Date')
    system_sign_date = fields.Datetime(string='System Sign Date')
    applicant_send_date = fields.Datetime(string='Applicant Send Date')
    tracking_number = fields.Char(string='Tracking Number')
    Corrective_number = fields.Char(string='Corrective Number')
    Barcode_post = fields.Char(string='Barcode Post')





    company_name = fields.Char(string='Company Name')  # partner_id.name
    company_address = fields.Char(string='Company Address')  # partner_id.street
    company_city = fields.Char(string='Company City')  # partner_id.city
    register_number= fields.Char(string='Register Number')  # partner_id.register_number
    company_register_type_id =fields.Many2one('res.partner.companyregistertype', string='Company Type', ondelete='restrict')       # partner_id.company_register_type_id
    national_identity= fields.Char(string='National Identity')  # partner_id.national_identity
    newspaper = fields.Char(string='Newspaper')  # partner_id.newspaper
    file_number= fields.Char(string='File Number')  # partner_id.file_number
    
    company_capital=fields.Char(string="Capital of the Company")    # partner_id.company_capital
    share_number= fields.Char(string='Share Number')  # partner_id.share_number
    share_value=fields.Char(string="Share Value") # partner_id.share_value
    share_type=fields.Char(string="Share Type") 
    shareholder_number=fields.Integer(string="Shareholder Number") # partner_id.shareholder_number
   
    board_number= fields.Integer(string='Board Number') # partner_id.board_number
    board_end= fields.Date(string='Board End') # partner_id.board_end   
    board_start= fields.Date(string='Board Start') # partner_id.board_start
    signatory_papers= fields.Char(string='Signatory of the papers') # partner_id.signatory_papers
    token_signature_holder = fields.Many2one('res.partner',string='Token Signature Holder') 

    last_ordinary_assembly=fields.Date(string='Last Ordinary Assembly')
    last_extension_inspector=fields.Date(string='Last Extension Inspector')
    approval_financial_statements= fields.Date(string='Approval Financial Statements') # partner_id.approval_financial_statements


    


    company_member_ids = fields.One2many('project.task.member','task_id',  string='Company Member', copy=True,   )




    write_partner = fields.Boolean( compute='_copy_to_contact' , readonly=False, store=True)
    po_sequence = fields.Char(string='Pouyande Sequence',readonly=True, store=True)


    @api.depends('state')
    def _copy_to_contact(self):
        for task in self:
            if task.state == '1_done':
                cl = self._get_change_field_list()  # Get the list of fields to update

                # Initialize an empty dictionary to store field-value pairs
                values_to_write = {}

                # Iterate over each field name in cl and get the corresponding value from task
                for field_name in cl:
                    # Check if the task has the attribute and add to the dictionary
                    if hasattr(task, field_name):
                        if field_name=='company_name':
                            values_to_write['name'] = getattr(task, field_name)
                        elif field_name=='company_address':
                            values_to_write['street'] = getattr(task, field_name)
                        elif field_name=='company_city':
                            values_to_write['city'] = getattr(task, field_name)
                        else:
                            values_to_write[field_name] = getattr(task, field_name)

                #overwrite the company member
                task.po_company_id.company_member_ids.unlink()

                # Loop in your One2many field in sale order
                new_member =[]
                for l in task.company_member_ids:
                    new_member.append(
                    (0,0,{
                        'company_member_id':l.company_member_id.id,
                        'position_id':l.position_id.id,
                        'is_board_member':l.is_board_member,
                        'is_inspector':l.is_inspector,
                        'share_number':l.share_number,
                        'share_value':l.share_value,
                        'share_type':l.share_type.id
                    }))
                    
                task.po_company_id.write({'company_member_ids': new_member})
                
                
                # If there are values to update, perform the write operation
                if values_to_write:
                    task.po_company_id.sudo().write(values_to_write)
                    '''
                    # Convert the dictionary to a JSON string
                    values_to_write_json = json.dumps(values_to_write,default=self.json_serial)

                    # Log the operation with the JSON data

                    self.env['partner.task.log'].sudo().create({
                        'partner_id': task.partner_id.id,
                        'task_id': task.id,
                        'state': '1_done',
                        'change_date': fields.Datetime.now(),
                        'chang_list': values_to_write_json  # Assuming there is a JSON field to store this
                    })
                    '''

                   
    def _get_change_field_list(self):
        for task in self:

            cl=[]
            partner=task.partner_id

            if task.company_name and task.company_name != partner.name:
                cl.append('company_name')
            if task.company_address and task.company_address != partner.street:
                cl.append('company_address')
            if  task.company_city and task.company_city != partner.city:
                cl.append('company_city')
            if  task.register_number and task.register_number != partner.register_number:
                cl.append('register_number')
            if  task.company_register_type_id.id and task.company_register_type_id.id != partner.company_register_type_id.id:
                cl.append('company_register_type_id')
            if  task.national_identity and task.national_identity != partner.national_identity:
                cl.append('national_identity')
            if  task.newspaper and task.newspaper != partner.newspaper:
                cl.append('newspaper')
            if  task.file_number and task.file_number != partner.file_number:
                cl.append('file_number')
            if  task.company_capital and task.company_capital != partner.company_capital:
                cl.append('company_capital')
            if  task.share_number and task.share_number != partner.share_number:
                cl.append('share_number')
            if  task.share_value and task.share_value != partner.share_value:
                cl.append('share_value')
           # if task.share_type and task.share_type != partner.share_type:
            #    cl.append('share_type')
            if task.shareholder_number and task.shareholder_number != partner.shareholder_number:
                cl.append('shareholder_number')
            if task.board_number and task.board_number != partner.board_number:
                cl.append('board_number')
            if task.board_end and task.board_end != partner.board_end:
                cl.append('board_end')
            if task.board_start and task.board_start != partner.board_start:
                cl.append('board_start')
            if task.signatory_papers and task.signatory_papers != partner.signatory_papers:
                cl.append('signatory_papers')
            if task.token_signature_holder.id and task.token_signature_holder.id != partner.token_signature_holder.id:
                cl.append('token_signature_holder')
            if task.last_ordinary_assembly and task.last_ordinary_assembly != partner.last_ordinary_assembly:
                cl.append('last_ordinary_assembly')
            if task.last_extension_inspector and task.last_extension_inspector != partner.last_extension_inspector:
                cl.append('last_extension_inspector')
            if task.approval_financial_statements and task.approval_financial_statements != partner.approval_financial_statements:
                cl.append('approval_financial_statements')

        
            print ("DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD")
            print (cl)
            return cl



    def _get_change_company_field_list(self):
        for task in self:

            cl=[]

            task_members=task.company_member_ids.sorted('company_member_id.id')
            partner_members=task.po_company_id.company_member_ids.sorted('company_member_id.id')
    
            '''
            for task_member in task_members:
                if task_member.board_member_id.id not in [partner_member.board_member_id.id for partner_member in partner_members]:
                    cl.append({'task_member.board_member_id.name':{'name':task_member.board_member_id.name,'function':task_member.function,'start_date':task_member.start_date,'end_date':task_member.end_date}}) })
        
        

            if task.company_name and task.company_name != partner.name:
                cl.append('company_name')
            '''
        return cl

    def json_serial(self,obj):
        """JSON serializer for objects not serializable by default json code"""

        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError ("Type %s not serializable" % type(obj))
   

    @api.model
    def create(self, vals):
        # Call the super to ensure the record is created
        vals.update({'po_company_id': vals.get('partner_id')})

        print ("valsssssssssssssssssssssssssssssssssssssssssssssssss")

        print (vals)

        record = super(Task, self).create(vals)
        
        # Check if the sequence exists
        sequence_code = 'COMP-'+ str(record.po_company_id.id)  # Define your sequence code here
        sequence_exists = self.env['ir.sequence'].search([('code', '=', sequence_code)], limit=1)
        
        code_name=str(record.po_company_id.name)

        # Create the sequence if it doesn't exist
        if not sequence_exists:
            self.env['ir.sequence'].create({
                'name': sequence_code,  # User-friendly name for the sequence
                'code': sequence_code,
               
                'padding': 5,  # Number of digits to pad with zeros
                'prefix': code_name + '-'  # Prefix for the sequence (optional)
            })
        square_string=self.env['ir.sequence'].next_by_code(sequence_code)

        record.write({'po_sequence':square_string})

        self.fiid_data(record)
        self.get_previous_request_type(record)

        return record

    '''
    @api.model
    def write(self, vals):
        # Call the super to ensure the record is created
        if 'partner_id' in vals:
            raise UserError("You cannot change customer after creation of the task")
        
        if 'project_id' in vals:
            raise UserError("You cannot change project after creation of the task")
        
        
        return super(Task, self).write(vals)
    '''
  


    def fiid_data(self,task):
     # fill task and task board with partner(company_id) and company_member_ids data from partner(company_id)
            vals = {'company_name': task.po_company_id.name,
                    'company_address': task.po_company_id.street,
                    'company_city': task.po_company_id.city,
                   'register_number': task.po_company_id.register_number,
                    'company_register_type_id': task.po_company_id.company_register_type_id.id,
                    'national_identity': task.po_company_id.national_identity,
                    'newspaper': task.po_company_id.newspaper,
                    'file_number': task.po_company_id.file_number,
                    'company_capital': task.po_company_id.company_capital,
                   'share_number': task.po_company_id.share_number,
                   'share_value': task.po_company_id.share_value,
                   #'share_type': task.po_company_id.share_type,
                   'shareholder_number': task.po_company_id.shareholder_number,
                    'board_number': task.po_company_id.board_number,
                    'board_end': task.po_company_id.board_end,
                    'board_start': task.po_company_id.board_start,
                   'signatory_papers': task.po_company_id.signatory_papers,
                    'token_signature_holder': task.po_company_id.token_signature_holder.id,
                    'last_ordinary_assembly': task.po_company_id.last_ordinary_assembly,
                    'last_extension_inspector': task.po_company_id.last_extension_inspector,
                    'approval_financial_statements': task.po_company_id.approval_financial_statements,
                    }
            task.write(vals)
            task.company_member_ids.unlink()
            for company_member in task.po_company_id.company_member_ids:
                task.company_member_ids.create({'task_id':task.id,  'company_member_id':company_member.company_member_id.id,'position_id':company_member.position_id.id,'share_number':company_member.share_number,'share_value':company_member.share_value,'share_type':company_member.share_type.id})     
            return True 

    #get previous request type base on po_company_id and fill previous_request_type field, fist sort all project.task and then filter by po_company_id and request_type and get the previous request type
  
    def get_previous_request_type(self,task):
        if task.po_company_id:
            tasks = self.env['project.task'].search([('po_company_id', '=', task.po_company_id.id)], order="id desc")

            try:
                if tasks[1]:
                
                    task.write({'previous_request_type': tasks[1].request_type.id}) 
                else:
                    task.write({'previous_request_type': False})
            except: 
                task.write({'previous_request_type': False})    
        else:
            task.write({'previous_request_type': False})

        return True 
   
class TaskRequestType(models.Model):
    _description = 'Task Request Type'
    _name = "task.request.type"
    _order = "name"

    name = fields.Char('Name', translate=True)
    active = fields.Boolean('Active', default=True)
