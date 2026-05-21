# -*- coding: utf-8 -*-

from . import models
from . import wizard
from . import controllers



def _post_init_assign_partner_codes(env):
    env['res.partner']._generate_missing_partner_codes()