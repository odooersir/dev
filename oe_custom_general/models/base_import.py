from odoo import models, _
from odoo.exceptions import UserError
import logging
import psycopg2
import contextlib

from odoo.addons.base_import.models.base_import import ImportValidationError

_logger = logging.getLogger(__name__)


class Import(models.TransientModel):
    _inherit = "base_import.import"

        

  