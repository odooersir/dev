from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    sbs_default_profit_margin = fields.Float(
        string="Default Profit Margin (%)",
        default=8.0,
        config_parameter='oe_sbs.default_profit_margin')
    
    sbs_min_profit_margin = fields.Float(
        string="Min Profit Margin (%)",
        default=7.0,
        config_parameter='oe_sbs.min_profit_margin')
    
    sbs_auto_rank = fields.Boolean(
        string="Auto Rank After Import",
        config_parameter='oe_sbs.auto_rank')
    
    
    sbs_auto_cleanup_old_lists = fields.Boolean(
        string="Auto Cleanup Old Lists",
        config_parameter='oe_sbs.auto_cleanup_old_lists')
    
    sbs_overlap_threshold_large = fields.Float(
        string="Overlap Threshold - Large Lists (≥100 items) %",
        default=50.0,
        config_parameter='oe_sbs.overlap_threshold_large')
    
    sbs_overlap_threshold_medium = fields.Float(
        string="Overlap Threshold - Medium Lists (50-99 items) %",
        default=45.0,
        config_parameter='oe_sbs.overlap_threshold_medium')
    
    sbs_overlap_threshold_small = fields.Float(
        string="Overlap Threshold - Small Lists (20-49 items) %",
        default=40.0,
        config_parameter='oe_sbs.overlap_threshold_small')
    
    sbs_overlap_threshold_tiny = fields.Float(
        string="Overlap Threshold - Tiny Lists (<20 items) %",
        default=35.0,
        config_parameter='oe_sbs.overlap_threshold_tiny')
    
    
    
    company_currency_id = fields.Many2one(
        'res.currency',
        string='Company Currency',
        readonly=True,
        compute='_compute_company_currency')
    
    @api.depends('company_id')
    def _compute_company_currency(self):
        for record in self:
            record.company_currency_id = record.company_id.currency_id