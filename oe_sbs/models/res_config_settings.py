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

    sbs_auto_import_start_date = fields.Datetime(
        string="Auto-import Start Date",
        config_parameter='oe_sbs.auto_import_start_date',
        help="The auto-send cron only imports documents created ON OR AFTER "
             "this moment. Files that arrived earlier are ignored. Leave empty "
             "to pause auto-import entirely.")

    sbs_email_intake_start_date = fields.Datetime(
        string="Email Intake Start Date",
        config_parameter='oe_sbs.email_intake_start_date',
        help="Emails sent BEFORE this moment are ignored - no document is "
             "created from them. Uses the email's own Date header. Leave empty "
             "to accept all incoming emails.")
    
    
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

    # ---- AI assist (Ollama local now, cloud later) ----------------------
    # Master switch. When off, import behaves exactly as before (regex only).
    sbs_ai_enabled = fields.Boolean(
        string="Enable AI Assist",
        config_parameter='oe_sbs.ai_enabled')
    # Ollama exposes an Anthropic-compatible endpoint, so the same anthropic
    # SDK works for both local and cloud - only base_url / key / model change.
    sbs_ai_base_url = fields.Char(
        string="AI Base URL",
        default="http://localhost:11434",
        help="Ollama endpoint (e.g. http://localhost:11434) or a cloud API base "
             "URL. Uses the Anthropic-compatible Messages API.",
        config_parameter='oe_sbs.ai_base_url')
    sbs_ai_model = fields.Char(
        string="AI Model",
        default="qwen2.5:3b",
        help="Model name as known to the provider, e.g. 'qwen2.5:3b' for Ollama.",
        config_parameter='oe_sbs.ai_model')
    sbs_ai_api_key = fields.Char(
        string="AI API Key",
        default="ollama",
        help="For Ollama any non-empty value works (e.g. 'ollama'). For a cloud "
             "provider, put the real key here.",
        config_parameter='oe_sbs.ai_api_key')
    sbs_ai_timeout = fields.Integer(
        string="AI Timeout (seconds)",
        default=15,
        help="If the model doesn't answer within this time, the import falls "
             "back to the regex result and moves on.",
        config_parameter='oe_sbs.ai_timeout')
    # Fine-grained toggles: use AI for the hard free-text metadata, and/or for
    # suggesting a column mapping. Either can be turned off independently.
    sbs_ai_for_metadata = fields.Boolean(
        string="AI for Metadata Extraction",
        help="Let the model read hard free-text metadata (MOV/MOQ/EXW ...) that "
             "the regex rules couldn't parse.",
        config_parameter='oe_sbs.ai_for_metadata')
    sbs_ai_for_mapping = fields.Boolean(
        string="AI for Mapping Suggestion",
        help="Let the model suggest a column mapping for a new file's headers.",
        config_parameter='oe_sbs.ai_for_mapping')

    # Which cells count as metadata during import (global, not per template).
    sbs_metadata_scan_mode = fields.Selection(
        [('outside', 'Outside table only'), ('full', 'Full sheet')],
        string="Metadata Scan Mode",
        default='outside',
        help="Which cells are read as metadata (MOV/MOQ/EXW ...). "
             "'Outside table only' skips the product rows/columns and is the "
             "safe default; 'Full sheet' also scans inside the table (use only "
             "if metadata is scattered among the data).",
        config_parameter='oe_sbs.metadata_scan_mode')
    
    
    
    company_currency_id = fields.Many2one(
        'res.currency',
        string='Company Currency',
        readonly=True,
        compute='_compute_company_currency')
    
    @api.depends('company_id')
    def _compute_company_currency(self):
        for record in self:
            record.company_currency_id = record.company_id.currency_id