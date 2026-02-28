# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SbsCleanupLog(models.Model):
    _name = 'sbs.cleanup.log'
    _description = 'SBS Import Lists Cleanup Log'
    _order = 'cleanup_date desc'
    
    cleanup_date = fields.Datetime(
        string='Cleanup Date',
        required=True,
        default=fields.Datetime.now,
        readonly=True
    )
    
    deleted_import_number = fields.Char(
        string='Deleted Import Number',
        required=True,
        readonly=True,
        index=True
    )
    
    new_import_number = fields.Char(
        string='New Import Number',
        required=True,
        readonly=True,
        index=True
    )
    
    supplier_name = fields.Char(
        string='Supplier',
        required=True,
        readonly=True,
        index=True
    )
    
    deleted_count = fields.Integer(
        string='Records Deleted',
        required=True,
        readonly=True
    )
    
    overlap_percentage = fields.Float(
        string='Overlap %',
        digits=(5, 2),
        readonly=True,
        help='Percentage of common EANs between old and new lists'
    )
    
    threshold_used = fields.Float(
        string='Threshold Used %',
        digits=(5, 2),
        readonly=True,
        help='The threshold percentage that was applied'
    )
    
    deletion_reason = fields.Text(
        string='Reason',
        readonly=True
    )
    
    @api.model
    def cleanup_old_logs(self, days=90):
        """حذف لاگ‌های قدیمی‌تر از X روز"""
        cutoff_date = fields.Datetime.now() - timedelta(days=days)
        old_logs = self.search([('cleanup_date', '<', cutoff_date)])
        return old_logs.unlink()
