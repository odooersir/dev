from odoo import http
from odoo.http import request,route

class DocumentSBSController(http.Controller):

    @http.route('/oe_sbs/send_to_sbs', type='jsonrpc', auth='user')
    def send_to_sbs(self, document_ids):
        
        results = []
        result = {}
        
        if not request.env.user.has_group('oe_sbs.group_sbs_send'):  
            result['status']='no'
            result['result_error']='User has not access to send to SBS.'
            
            result_summary = {
                'document_id': 0,
                'document_name': '',
                'status': result.get('status'),
                'error': result.get('result_error'),
            }
            
            results.append(result_summary)


            return {
            'status': 'multi',
            'results': results,
            }

        
        documents = request.env['documents.document'].browse(document_ids)

       
        
        for document in documents:
            
            if any(tag.state == 'reject' for tag in document.tag_ids):
                result['status']='no'
                result['result_error']='document is rejected'

                #tags_to_add = request.env['documents.tag'].search([('state', '=', 'sent_to_sbs')])
                #document.write({'tag_ids':[(4, tag.id) for tag in tags_to_add]})

                #document.tag_ids = [(4, tag.id) for tag in tags_to_add]
            elif document.import_number:
                result['status']='no'
                result['result_error']='document was already imported.'

            elif document.state=='auto_deleted':
                result['status']='no'
                result['result_error']='document was already imported and deleted'

                

            else:
                 # 1. پیدا کردن تامین‌کننده از روی نام فولدر داکیومنت
                supplier = False
                if document.folder_id and document.folder_id.name:
                    supplier = request.env['res.partner'].sudo().search([
                        ('name', 'ilike', document.folder_id.name)
                    ], limit=1)

                if not supplier:
                    # اگر تامین‌کننده‌ای هم‌نام با فولدر پیدا نشد، خطا می‌دهیم
                    result['status'] = 'no'
                    result['result_error'] = f"تامین‌کننده‌ای با نام '{document.folder_id.name}' یافت نشد."
                else:
                    try:
                        # 2. ارسال supplier_id به ویزارد در زمان ساخت
                        wizard = request.env['sbs.import.wizard'].sudo().create({
                            'from_doc': True,
                            'from_rpc': True,
                            'document_id': document.id,
                            'file_name': document.name,
                            'supplier_id': supplier.id,  # اضافه شدن این خط
                        })
                        
                        # حالا که supplier_id وجود دارد، action_import می‌تواند 
                        # قالب (template) مناسب را به صورت خودکار پیدا کند
                        result = wizard.action_import()
                    except Exception as e:
                        result['status']='no'
                        result['result_error']=str(e)

                        

            # انتظار می‌ره action_import یک dict برگردونه، مثل:
            # {"status": "ok", "import_number": ..., "total_imported": ...}
            # یا {"status": "no", "result_error": "..."}

            result_summary = {
                'document_id': document.id,
                'document_name': document.name,
                'status': result.get('status'),
            }

            if result.get('status') == 'ok':
                result_summary.update({
                    'import_number': result.get('import_number'),
                    'total_imported': result.get('total_imported'),
                    'cleanup_msg':result.get('cleanup_msg'),
                })

                #tags_to_add = request.env['documents.tag'].search([('state', '=', 'sent_to_sbs')])
                tags_to_add=[]
                
                

                document.sudo().write({'import_number': result.get('import_number'),'modifier': request.env.user  ,'state':'sent_to_sbs','tag_ids':[(4, tag.id) for tag in tags_to_add]})
                #tags_to_add = request.env['documents.tag'].search([('state', '=', 'sent_to_sbs')])
                #document.tag_ids = [(4, tag.id) for tag in tags_to_add]
            else:
                result_summary.update({'error': result.get('result_error'),})

                document.sudo().write({'rejection_reason':result.get('result_error'),'state':'reject'})



            results.append(result_summary)

        return {
            'status': 'multi',
            'results': results,
        }



    @http.route('/oe_sbs/delete_from_sbs', type='jsonrpc', auth='user')
    def delete_from_sbs(self, document_ids):
        
        documents = request.env['documents.document'].browse(document_ids)

        results = []
        result = {}

        if not request.env.user.has_group('oe_sbs.group_sbs_send'):  
            result['status']='no'
            result['result_error']='User has not access to delete from SBS.'
            
            result_summary = {
                'document_id': 0,
                'document_name': '',
                'status': result.get('status'),
                'error': result.get('result_error'),
            }
            
            results.append(result_summary)


            return {
            'status': 'multi',
            'results': results,
            }

        
        for document in documents:
            
           
           

            # انتظار می‌ره action_import یک dict برگردونه، مثل:
            # {"status": "ok", "import_number": ..., "total_imported": ...}
            # یا {"status": "no", "result_error": "..."}

            import_number=document.import_number
            if import_number:
                records = request.env['sbs.data'].sudo().search([('import_number', '=', import_number)])
                delete_count=len(records)
                
                if records.unlink():

                    result = {"status": "ok",  'import_number': import_number,'total_deleted': delete_count}
                else:
                    result = {"status": "no", 'result_error':False}
            else:
                result = {"status": "no", 'result_error':'File is not in SBS'}


            result_summary = {
                'document_id': document.id,
                'document_name': document.name,
                'status': result.get('status'),
            }

            if result.get('status') == 'ok':
                result_summary.update({
                    'import_number': result.get('import_number'),
                    'total_deleted': result.get('total_deleted'),
                })

                #tags_to_add = request.env['documents.tag'].search([('state', '=', 'deleted_from_sbs')])
                tags_to_add=[]
                
                document.sudo().write({'import_number': False,'modifier': request.env.user,'state':'deleted_from_sbs','tag_ids':[(4, tag.id) for tag in tags_to_add]})
                #tags_to_add = request.env['documents.tag'].search([('state', '=', 'sent_to_sbs')])
                #document.tag_ids = [(4, tag.id) for tag in tags_to_add]
            else:
                result_summary.update({
                    'error': result.get('result_error'),
                })

            results.append(result_summary)

        return {
            'status': 'multi',
            'results': results,
        }