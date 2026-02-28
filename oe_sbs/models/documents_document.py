from odoo import models, api , fields, _
from odoo.exceptions import AccessError,UserError
import base64
import json





class Document(models.Model):
    _inherit = 'documents.document'
    _order = 'name, sequence, id desc'


    tag_ids = fields.Many2many('documents.tag', 'document_tag_rel', string="Tags", tracking=True)

    DOCUMENT_STATE = [
        ('draft', "Draft"),
        ('approve', "Approve"),
         ('sent_to_sbs', "Sent To SBS"),
        ('deleted_from_sbs', "Deleted From SBS"),
        ('auto_deleted', "Auto Deleted From SBS"),
        ('reject', "Reject"),
       
    ]

    state = fields.Selection(
        selection=DOCUMENT_STATE,
        string="Status",
        readonly=True, copy=False, index=True,
        tracking=True,
        default='draft')

    import_number = fields.Char(string='IN',help='Import Number',copy=False,  default=False)
    old_import_number = fields.Char(string='OIN',help='Old Import Number',copy=False,  default=False)
    

    is_tag_editor = fields.Boolean(compute='_compute_is_tag_editor')

    modifier=  fields.Many2one('res.users', string="Modifier")

       #            <field name="state" widget="statusbar" statusbar_visible="draft,approve,reject"/>
  

     # The compute does not get triggered without a depends on record creation
    # aka keep the 'useless' depends
    @api.depends_context('uid')
    @api.depends('tag_ids')

    def _compute_is_tag_editor(self):
        self.is_tag_editor = self.env.user.has_group("oe_sbs.group_tag_editor")


    def write(self, vals):
    
        if not self.env.su and 'tag_ids' in vals and not self.env.user.has_group('oe_sbs.group_tag_editor'):
            raise AccessError("Only members of Tag Editor group can modify tags.")
        
           
            # اگر تگی در حال اضافه شدن است
        if 'tag_ids' in vals:

            print ("tag_ids tag_ids tag_ids tag_ids tag_ids tag_ids tag_ids tag_ids")
            print (vals['tag_ids'])
            tag_cmds = vals['tag_ids']
            for cmd in tag_cmds:
                # فقط حالت (4, id) یعنی اضافه شدن تگ موجود
                if isinstance(cmd, (list, tuple)) and len(cmd) >= 2 and cmd[0] == 4:
                    tag = self.env['documents.tag'].browse(cmd[1])
                    if tag.state == 'reject':
                        vals['modifier'] = self.env.user.id
                        break  # لازم نیست ادامه بدیم
        
        #vals['modifier'] = False

        return super().write(vals)
    
    def export_final_xlsx(self):
            self.ensure_one()
            if self.mimetype != "application/o-spreadsheet":
                raise UserError(_("Not a spreadsheet"))

            snapshot = self._get_spreadsheet_serialized_snapshot()
           # print(snapshot)
            revisions = self.spreadsheet_revision_ids
           # print(revisions)

            final_data = self._apply_revisions(snapshot, revisions)
          #  print (final_data )
           # if "files" not in final_data:
            #    raise UserError(_("No files in final data"))
            #return self.env["spreadsheet.mixin"]._zip_xslx_files(final_data["sheets"])
            return final_data

            
    def _apply_revisions(self, snapshot, revisions):
        data = json.loads(json.dumps(snapshot))
        for rev in revisions:
            # Get commands from ORM object
            commands = rev.commands if hasattr(rev, 'commands') else []
            
            # Parse if it's a JSON string
            if isinstance(commands, str):
                try:
                    commands = json.loads(commands)
                except (json.JSONDecodeError, TypeError):
                    commands = []
            
            # Ensure commands is a list
            if not isinstance(commands, list):
                commands = []
            
            for cmd in commands:
                # Parse individual command if it's still a string
                if isinstance(cmd, str):
                    try:
                        cmd = json.loads(cmd)
                    except (json.JSONDecodeError, TypeError):
                        continue
                
                data = self._apply_command(data, cmd)
        return data

    def _apply_command(self, data, cmd):
        """
        Minimal server-side simulation of revision commands.
        Extend as needed (UPDATE_CELL, INSERT_ROW, DELETE_ROW, MERGE_CELLS, ...).
        """
        cmd_type = cmd.get("type")

        if cmd_type == "UPDATE_CELL":
            sheet_id = cmd.get("sheetId")
            row, col, value = cmd.get("row"), cmd.get("col"), cmd.get("value")
            for sheet in data.get("sheets", []):
                if sheet["id"] == sheet_id:
                    cells = sheet.setdefault("cells", {})
                    key = f"{row}:{col}"
                    cells[key] =  value
                    break

        elif cmd_type == "INSERT_ROW":
            sheet_id, row_index = cmd.get("sheetId"), cmd.get("row")
            for sheet in data.get("sheets", []):
                if sheet["id"] == sheet_id:
                    rows = sheet.setdefault("rows", [])
                    rows.insert(row_index, {})
                    break

        elif cmd_type == "DELETE_ROW":
            sheet_id, row_index = cmd.get("sheetId"), cmd.get("row")
            for sheet in data.get("sheets", []):
                if sheet["id"] == sheet_id:
                    rows = sheet.get("rows", [])
                    if 0 <= row_index < len(rows):
                        rows.pop(row_index)
                    break

        elif cmd_type == "MERGE_CELLS":
            sheet_id = cmd.get("sheetId")
            merge_range = cmd.get("range")
            for sheet in data.get("sheets", []):
                if sheet["id"] == sheet_id:
                    merges = sheet.setdefault("merges", [])
                    merges.append(merge_range)
                    break

        # TODO: دستورات بیشتری مثل INSERT_COLUMN, DELETE_COLUMN, RENAME_SHEET, ... اضافه شود.

        return data
  
class Tags(models.Model):
    _inherit = "documents.tag"



    def write(self, vals):
     
        if not self.env.su and 'tag_ids' in vals and not self.env.user.has_group('oe_sbs.group_tag_editor'):
            raise AccessError("Only members of Tag Editor group can modify tags.")
        
        return super().write(vals)


    