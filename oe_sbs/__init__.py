import pytz
from datetime import datetime, time

from odoo import fields

from . import models
from . import wizard
from . import controllers


def _sbs_post_init_set_start_date(env):
    """
    On install, default BOTH the auto-import cutoff and the email-intake cutoff
    to the START OF TODAY, so the first cron run never sweeps in historical
    files and no backlog email is ingested, while everything from today onward
    is processed normally.

    The cutoffs are stored as UTC datetimes (matching how create_date / the
    email Date header are stored). We take local midnight in the admin's
    timezone and convert it to UTC, so 'today' means the admin's today, not
    UTC's. Only sets each when unset, so a reinstall/upgrade won't clobber an
    admin's chosen value.
    """
    ICP = env['ir.config_parameter'].sudo()

    tz_name = env.context.get('tz') or env.user.tz or 'UTC'
    try:
        local_tz = pytz.timezone(tz_name)
    except Exception:
        local_tz = pytz.UTC

    today = fields.Date.context_today(env['res.config.settings'])
    local_midnight = local_tz.localize(datetime.combine(today, time.min))
    start_utc = fields.Datetime.to_string(
        local_midnight.astimezone(pytz.UTC).replace(tzinfo=None))

    # Both cutoffs default to the start of install-day, and only when unset so a
    # reinstall/upgrade never clobbers an admin's chosen value.
    for param in ('oe_sbs.auto_import_start_date',
                  'oe_sbs.email_intake_start_date'):
        if not ICP.get_param(param):
            ICP.set_param(param, start_utc)
