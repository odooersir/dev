console.log(">>>DocumentsListController patch loaded!");

/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { DocumentsListController } from "@documents/views/list/documents_list_controller";
import { _t } from "@web/core/l10n/translation";

console.log(">>> Patch DocumentsListController loaded!");

patch(DocumentsListController.prototype, {
        getStaticActionMenuItems() {
            const menuItems = super.getStaticActionMenuItems();
            const selectionCount = this.targetRecords.length;
            const userIsInternal = this.documentService.userIsInternal;
            return {
                
                export_to_sbs: {
                    isAvailable: () => userIsInternal && selectionCount > 0,
                    sequence: 20,
                    description: _t("Export to SBS"),
                    icon: "fa fa-upload",
                    callback: () => this.model.onSendToSBS(),
                    groupNumber: 1,
                },
                delete_from_sbs: {
                    isAvailable: () => userIsInternal && selectionCount > 0,
                    sequence: 30,
                    description: _t("Delete from SBS"),
                    icon: "fa fa-trash",
                    callback: () => this.model.onDeleteFromSBS(),
                    groupNumber: 1,
                },
                create_template: {
                    isAvailable: () => userIsInternal && selectionCount > 0,
                    sequence: 40,
                    description: _t("Create Mapping"),
                    icon: "fa fa-upload",
                    callback: () => this.model.onCreateTemplate(),
                    groupNumber: 1,
                },
                ...menuItems,
            };
        }
    }
);
