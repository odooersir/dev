# controllers/main.py
from odoo import http
from odoo.http import request
import json

class PartnerDataAPI(http.Controller):
  
    @http.route('/api/partners', type='http', auth='none', methods=['GET'], csrf=False)
    def get_partners(self, **kwargs):
        """
        API برای ارائه داده تامین‌کننده‌ها به فرمت HTML Table
        نیاز به توکن دارد: ?token=YOUR_SECRET_TOKEN
        """
        # بررسی توکن امنیتی
        STATIC_TOKEN = "e4@clohdfgs89"  # توکن خودت را اینجا بگذار
        request_token = kwargs.get('token', '')
        
        if request_token != STATIC_TOKEN:
            return request.make_response(
                "<h1>خطا: دسترسی غیرمجاز - توکن نامعتبر است</h1>",
                headers=[('Content-Type', 'text/html; charset=utf-8')],
                status=403
            )
        
        # دریافت پارامترها
        limit = int(kwargs.get('limit', 1000))
        offset = int(kwargs.get('offset', 0))
        search = kwargs.get('search', '')
        
        # ساخت domain - فقط تامین‌کننده‌ها
        domain = [('is_supplier', '=', True)]
        if search:
            domain.append(('name', 'ilike', search))

        # دریافت تامین‌کننده‌ها
        partners = request.env['res.partner'].sudo().with_context(do_not_include=True).search(
            domain,
            limit=limit,
            offset=offset,
            order='name asc'
        )

        # ساخت جدول HTML
        html = """
        <html>
        <head>
            <meta charset="utf-8"/>
            <style>
                table { border-collapse: collapse; width: 100%; }
                th, td { border: 1px solid #444; padding: 8px; text-align: center; }
                th { background: #4CAF50; color: white; font-weight: bold; }
                tr:nth-child(even) { background: #f9f9f9; }
            </style>
        </head>
        <body>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Code</th>
                        <th>Type</th>
                    </tr>
                </thead>
                <tbody>
        """

        # افزودن رکوردها به جدول
        for partner in partners:
            partner_type = "Company" if partner.is_company else "Individual"
            html += f"""
                <tr>
                    <td>{partner.name or ''}</td>
                    <td>{partner.partner_code or ''}</td>
                    <td>{partner_type}</td>
                </tr>
            """

        html += """
                </tbody>
            </table>
        </body>
        </html>
        """

        # هدرهای HTTP
        headers = [
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
        ]

        return request.make_response(html, headers=headers)
