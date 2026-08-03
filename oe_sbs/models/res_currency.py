# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class Currency(models.Model):
    _inherit = 'res.currency'

    def write(self, vals):
        res = super().write(vals)
        # Rates edited through the currency FORM arrive here as rate_ids.
        if 'rate_ids' in vals:
            self._sbs_refresh_converted(self)
        return res

    @api.model
    def _sbs_refresh_converted(self, currencies):
        """
        Re-price every SBS row quoted in these currencies.

        converted_price / converted_rate / selling_price / MOV are all stored,
        not computed, so nothing refreshes them on its own - a rate change has
        to push. Only the affected currencies are touched: recomputing the whole
        table on every rate edit is needlessly expensive, and rates are edited
        one currency at a time.
        """
        currencies = currencies.exists()
        if not currencies:
            return
        SBSData = self.env['sbs.data'].sudo()
        records = SBSData.search([('currency_id', 'in', currencies.ids)])
        if not records:
            return
        _logger.info("[SBS] currency rate changed for %s - re-pricing %s row(s).",
                     ', '.join(currencies.mapped('name')), len(records))
        records.compute_selling_prices()
        # Ranking runs raw SQL, so the ORM writes above must reach the database
        # first, and the cache must be dropped afterwards (see _nightly_rank).
        SBSData._nightly_rank()


class CurrencyRate(models.Model):
    _inherit = 'res.currency.rate'

    # A rate lives on res.currency.rate, and the Currencies > Rates list edits
    # it directly - so does Odoo's own automatic rate-update cron. Neither path
    # goes through res.currency.write, which is why prices could silently keep
    # yesterday's rate after the rate itself had already changed. Hooking the
    # rate model covers every path.

    def _sbs_touched_currencies(self):
        return self.mapped('currency_id')

    @api.model_create_multi
    def create(self, vals_list):
        rates = super().create(vals_list)
        self.env['res.currency']._sbs_refresh_converted(
            rates._sbs_touched_currencies())
        return rates

    def write(self, vals):
        res = super().write(vals)
        if 'rate' in vals or 'inverse_company_rate' in vals or 'company_rate' in vals:
            self.env['res.currency']._sbs_refresh_converted(
                self._sbs_touched_currencies())
        return res

    def unlink(self):
        currencies = self._sbs_touched_currencies()
        res = super().unlink()
        self.env['res.currency']._sbs_refresh_converted(currencies)
        return res
