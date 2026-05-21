# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.website.controllers.main import Website


class CliimaxWebsite(Website):
    
    @http.route('/', type='http', auth='public', website=True, sitemap=True)
    def index(self, **kw):
        return request.render('oe_custom_website.cliimax_homepage')
