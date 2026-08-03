from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website_sale.const import SHOP_PATH
from werkzeug.exceptions import NotFound
from odoo.addons.website.controllers.main import QueryURL
from datetime import date


# ─── MOV Logic ────────────────────────────────────────────────────────────────
def _compute_mov_violations(order_sudo):
    """
    محاسبه MOV violations برای سبد.
    فقط لاین‌هایی که sbs_data_id دارند بررسی می‌شوند.
    
    Returns: list[dict] — violations یا لیست خالی
    """
    import_data = {}

    for line in order_sudo.order_line:
        if not line.sbs_data_id:
            continue

        imp_num = (
            line.snapshot_import_number
            or str(line.sbs_data_id.import_number or '')
            or ''
        ).strip()

        if not imp_num:
            continue

        if imp_num not in import_data:
            import_data[imp_num] = {'total_value': 0.0, 'mov': 0.0}

        import_data[imp_num]['total_value'] += float(line.price_subtotal)

        # MOV از فیلد Char sbs.data → parse
        offer_mov = _parse_numeric_mov(line.sbs_data_id.mov or '', cast=float)
        if offer_mov > import_data[imp_num]['mov']:
            import_data[imp_num]['mov'] = offer_mov

    violations = []
    for imp_num, data in import_data.items():
        if data['mov'] > 0 and data['total_value'] < data['mov']:
            violations.append({
                'import_number': imp_num,
                'mov':           data['mov'],
                'current_value': data['total_value'],
                'remaining':     round(data['mov'] - data['total_value'], 2),
            })

    violations.sort(key=lambda x: x['import_number'])
    return violations


class WebsiteSaleExtended(WebsiteSale):

    """
    بلاک کردن checkout اگر MOV رعایت نشده باشد.
    ریدایرکت به /shop/cart با ذخیره violations در session.
    """

    def shop_checkout(self, try_skip_step=None, **query_params):
        order_sudo = request.cart

        if order_sudo:
            violations = _compute_mov_violations(order_sudo)
            if violations:
                # ذخیره در session — Cart._cart_values() آن را می‌خواند
                request.session['mp_mov_violations'] = violations
                _logger.info(
                    "MOV check failed for order %s: %s violations",
                    order_sudo.name, len(violations)
                )
                return request.redirect('/shop/cart')

        # اگر همه چیز OK بود، violations قدیمی را پاک کن
        request.session.pop('mp_mov_violations', None)
        return super().shop_checkout(try_skip_step=try_skip_step, **query_params)

    def _get_shop_payment_values(self, order, **kwargs):
        # فراخوانی متد والد برای دریافت تمام مقادیر اصلی
        values = super()._get_shop_payment_values(order, **kwargs)

        # تغییر متن دکمه پرداخت
        values['submit_button_label'] = _("Last Confirm")

        return values



    # ─── Route: /shop/brand/<brand> ───────────────────────────────────────────

    @http.route([
         f'{SHOP_PATH}/brand/<model("product.brand"):brand>',
         f'{SHOP_PATH}/brand/<model("product.brand"):brand>/page/<int:page>',
    ], type='http', auth='public', website=True, sitemap=True)
    def shop_brand(self, brand, page=0, **post):
        request.session['shop_brand_id'] = brand.id
        request.session.pop('shop_offer_import', None)
        return super().shop(page=page, **post)

    # ─── Route: /shop/offer/<import_number> ───────────────────────────────────

    @http.route([
         f'{SHOP_PATH}/offer/<string:import_number>',
         f'{SHOP_PATH}/offer/<string:import_number>/page/<int:page>',
    ], type='http', auth='public', website=True, sitemap=False)
    def shop_offer(self, import_number, page=0, search='',
                   min_price=0.0, max_price=0.0, **post):
      
        print ("11111111111111111111111111111111111111111111111111111111111111")
        
        #normalized = str(import_number).lstrip('0') or '0'
        normalized = str(import_number)

        print (normalized)
        exists = request.env['sbs.data'].sudo().search_count([
            ('import_number', '=', normalized),
           # ('is_expired', '=', False),
        ])
        if not exists:
            raise NotFound()

        request.session['shop_offer_import'] = normalized
        request.session.pop('shop_brand_id', None)

        return super().shop(page=page, search=search,
                            min_price=min_price, max_price=max_price, **post)

    # ─── Route: /shop (پاک‌سازی session) ─────────────────────────────────────

    @http.route([
        '/shop',
        '/shop/page/<int:page>',
        '/shop/category/<model("product.public.category"):category>',
        '/shop/category/<model("product.public.category"):category>/page/<int:page>',
    ], type='http', auth='public', website=True, sitemap=True)
    def shop(self, page=0, category=None, search='',
             min_price=0.0, max_price=0.0, **post):
        # وقتی کاربر مستقیم به /shop می‌آید، فیلترهای قبلی پاک می‌شوند
        request.session.pop('shop_brand_id', None)
        request.session.pop('shop_offer_import', None)
        return super().shop(page=page, category=category, search=search,
                            min_price=min_price, max_price=max_price, **post)

    # ─── تزریق به options ─────────────────────────────────────────────────────

    def _shop_lookup_products(self, options, post, search, website):
        brand_id = request.session.get('shop_brand_id')
        offer_import = request.session.get('shop_offer_import')

        if brand_id:
            options['brand_id'] = int(brand_id)
        if offer_import:
            options['offer_import'] = offer_import

        return super()._shop_lookup_products(options, post, search, website)


    #-----
    def _get_shop_domain(self, search, category, attribute_value_dict, search_in_description=True):

        """اعمال فیلتر برند به domain محصولات"""
        domain = super()._get_shop_domain( search, category, attribute_value_dict, search_in_description=True )
        
        brand_id = request.session.get('shop_brand_id')
        if brand_id:
            domain += [('brand_id', '=', int(brand_id))]
        
        return domain


    def _get_additional_shop_values(self, values, **kwargs):
        """تزریق لیست برندها و برند انتخاب‌شده به template"""
        result = super()._get_additional_shop_values(values, **kwargs)
        
        brand_id = request.session.get('shop_brand_id')
        
        all_brands = request.env['product.brand'].sudo().search(
            [('active', '=', True)],
            order='name'
        )
        
        selected_brand_ids = [brand_id] if brand_id else []
        
        result.update({
            'brands': all_brands,
            'selected_brand_ids': selected_brand_ids,
        })
        
        return result


    #______________________________________________________________
    @http.route(
        '/shop/brands',
        type='http',
        auth='public',
        website=True,
    )
    def product_brands(self, search='', letter='', **post):
        from collections import defaultdict

        # ─── برندهایی که آفر فعال دارند ───
        sbs_records = request.env['sbs.data'].sudo().search([
            ('brand_id', '!=', False),
            ('is_expired', '=', False),
        ])

        # تعداد آفر هر برند
        brand_offer_count = {}
        for rec in sbs_records:
            bid = rec.brand_id.id
            brand_offer_count[bid] = brand_offer_count.get(bid, 0) + 1

        sbs_brand_ids = list(brand_offer_count.keys())

        if not sbs_brand_ids:
            return request.render(
                'oe_custom_website.product_brands',
                {
                    'brands_by_letter': {},
                    'alphabet'        : list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
                    'active_letters'  : set(),
                    'brand_offer_count': {},
                    'current_letter'  : letter,
                    'search'          : search,
                }
            )

        domain = [
            ('id', 'in', sbs_brand_ids),
            ('active', '=', True),
        ]
        if search:
            domain += [('name', 'ilike', search)]

        all_brands = request.env['product.brand'].sudo().search(
            domain, order='name asc'
        )

        # ─── گروه‌بندی بر اساس حرف اول ───
        brands_by_letter = defaultdict(list)
        for brand in all_brands:
            first_char = (brand.name or '#')[0].upper()
            key = first_char if first_char.isalpha() else '0-9'
            brands_by_letter[key].append(brand)

        # تعداد محصولات هر برند از product.template
        brand_product_count = {}
        if all_brands:
            product_data = request.env['product.template'].sudo().read_group(
                domain=[
                    ('brand_id', 'in', all_brands.ids),
                    ('active', '=', True),
                ],
                fields=['brand_id'],
                groupby=['brand_id'],
            )
            for row in product_data:
                bid = row['brand_id'][0]
                brand_product_count[bid] = row['brand_id_count']

        values = {
            'brands_by_letter'  : dict(brands_by_letter),
            'alphabet'          : list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
            'active_letters'    : set(brands_by_letter.keys()),
            'brand_offer_count' : brand_offer_count,
            'brand_product_count': brand_product_count,
            'current_letter'    : letter,
            'search'            : search,
        }

        return request.render(
            'oe_custom_website.product_brands', values
        )

    @http.route([
        '/shop/brand/<int:brand_id>/offers',
    ], type='http', auth='public', website=True)
    def brand_offers(self, brand_id, **kw):
        Brand = request.env['product.brand'].sudo()
        brand = Brand.browse(brand_id)
        if not brand.exists():
            raise request.not_found()

        today = date.today()

        # واکشی آفرهای فعال این برند - بدون supplier
        offers = request.env['sbs.data'].sudo().search([
            ('brand_id', '=', brand_id),
            ('is_expired', '=', False),
        ], order='import_date desc')

        # گروه‌بندی بر اساس import_number (هر import_number = یک آفر)
        offers_by_import = {}
        for offer in offers:
            key = offer.import_number
            if key not in offers_by_import:
                offers_by_import[key] = {
                    'import_number': offer.import_number,
                    'import_date': offer.import_date,
                    'end_date': offer.end_date,
                    'moq': offer.moq,
                    'mov': offer.mov,
                    'incoterms': offer.incoterms,
                    't1_t2': offer.t1_t2,
                    'payment_term': offer.payment_term,
                    'lead_time': offer.lead_time,
                    'product_count': 0,
                    # id اولین رکورد برای لینک
                    'offer_id': offer.id,
                }
            offers_by_import[key]['product_count'] += 1

        grouped_offers = list(offers_by_import.values())

        return request.render('oe_custom_website.brand_offers', {
            'brand': brand,
            'grouped_offers': grouped_offers,
            'today': date.today(),
        })
