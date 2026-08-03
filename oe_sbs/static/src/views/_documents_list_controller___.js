/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { DocumentsListController } from "@documents/views/list/documents_list_controller";
import { _t } from "@web/core/l10n/translation";

patch(DocumentsListController.prototype,  {
    
   
    async onDeleteSelectedRecords() {
        alert(4);
        if (!(await openDeleteConfirmationDialog(this.model, true))) {
            return;
        }
        const root = this.model.root;
        await root.deleteRecords(root.records.filter((record) => record.selected));
        await this.model.notify();
        await this.model.env.documentsView.bus.trigger("documents-close-preview");
    },

    async onArchiveSelectedRecords() {
        alert(5);
        if (!(await openDeleteConfirmationDialog(this.model, false))) {
            return;
        }
        await this.toggleArchiveState(true);
        await this.model.env.documentsView.bus.trigger("documents-close-preview");
    }



});
