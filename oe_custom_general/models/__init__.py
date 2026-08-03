# -*- coding: utf-8 -*-

from . import product_template
from . import  project_task
from . import  sale_order
from . import  stock_picking
from . import  stock_quant
from . import  res_partner
from . import  product_product
from . import  base_import
from . import  product_brand
from . import  crm_lead
from . import  res_country

def _post_init_assign_partner_codes(cr, registry):
    from odoo.api import Environment
    env = Environment(cr, SUPERUSER_ID, {})
    env['res.partner']._generate_missing_partner_codes()

