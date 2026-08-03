from odoo import http
from odoo.http import request, route


class DocumentSBSController(http.Controller):

    @http.route('/oe_sbs/send_to_sbs', type='jsonrpc', auth='user')
    def send_to_sbs(self, document_ids):

        results = []

        if not request.env.user.has_group('oe_sbs.group_sbs_send'):
            results.append({
                'document_id': 0,
                'document_name': '',
                'status': 'no',
                'error': 'User has not access to send to SBS.',
            })
            return {'status': 'multi', 'results': results}

        documents = request.env['documents.document'].browse(document_ids)

        for document in documents:
            # All send logic now lives on the model (_sbs_send_one), shared with
            # the auto-send cron. Manual sends leave auto=False -> 'sent_to_sbs'.
            # The method resolves the supplier, runs the import wizard, and sets
            # the document's state/import_number/template_id itself.
            result = document._sbs_send_one()

            result_summary = {
                'document_id': document.id,
                'document_name': document.name,
                'status': result.get('status'),
            }

            if result.get('status') == 'ok':
                result_summary.update({
                    'import_number': result.get('import_number'),
                    'total_imported': result.get('total_imported'),
                    'cleanup_msg': result.get('cleanup_msg'),
                })
            else:
                result_summary.update({'error': result.get('result_error')})

            results.append(result_summary)

        return {'status': 'multi', 'results': results}

    @http.route('/oe_sbs/delete_from_sbs', type='jsonrpc', auth='user')
    def delete_from_sbs(self, document_ids):

        documents = request.env['documents.document'].browse(document_ids)
        results = []

        if not request.env.user.has_group('oe_sbs.group_sbs_send'):
            results.append({
                'document_id': 0,
                'document_name': '',
                'status': 'no',
                'error': 'User has not access to delete from SBS.',
            })
            return {'status': 'multi', 'results': results}

        for document in documents:
            import_number = document.import_number
            if import_number:
                records = request.env['sbs.data'].sudo().search(
                    [('import_number', '=', import_number)])
                delete_count = len(records)
                if records.unlink():
                    result = {"status": "ok", 'import_number': import_number,
                              'total_deleted': delete_count}
                else:
                    result = {"status": "no", 'result_error': False}
            else:
                result = {"status": "no", 'result_error': 'File is not in SBS'}

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
                document.sudo().write({
                    'import_number': False,
                    'template_id': False,
                    'modifier': request.env.user,
                    'state': 'deleted_from_sbs',
                })
            else:
                result_summary.update({'error': result.get('result_error')})

            results.append(result_summary)

        return {'status': 'multi', 'results': results}
