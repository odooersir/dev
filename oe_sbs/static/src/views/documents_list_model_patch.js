/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { DocumentsListModel } from "@documents/views/list/documents_list_model";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { WarningDialog } from "@web/core/errors/error_dialogs";
import { toggleArchive } from "@documents/views/hooks";


patch(DocumentsListModel.prototype, {

        async onSendToSBS() {
            const records = this.targetRecords.filter((r) => r.data.active);
            const recordIds = records.map((r) => r.data.id);

            if (!recordIds.length) {
                this.notification.add(_t("Please select at least one document."), { type: "warning" });
                return;
            }

            try {
                const result = await rpc("/oe_sbs/send_to_sbs", { document_ids: recordIds });

                if (result.status === "multi" && Array.isArray(result.results)) {
                    let successCount = 0;
                    let errorMessages = [];

                    for (const res of result.results) {
                        if (res.status === "ok") {
                            successCount++;
                            this.notification.add(
                                _t(`✅ ${res.document_name}: imported ${res.total_imported}, ref: ${res.import_number}`),
                                { type: "success" }
                            );
                        } else {
                            errorMessages.push(`❌ ${res.document_name}: ${res.error}`);
                        }
                    }

                    if (errorMessages.length) {
                        this.dialogService.add(WarningDialog, {
                            title: _t("Import Errors"),
                            message: errorMessages.join("\n"),
                        });
                    }
                    if (!successCount) {
                        this.notification.add(_t("No document was successfully imported."), { type: "warning" });
                  } else {
                      window.location.reload();

                    }

                } else {
                    this.notification.add(_t("Unexpected server response."), { type: "warning" });
                }
            } catch (error) {
                this.notification.add(_t("Connection error: could not reach the server."), {
                    type: "danger",
                    sticky: true,
                });
                console.error("RPC error:", error);
            }
        },

        async onDeleteFromSBS() {
            const records = this.targetRecords.filter((r) => r.data.active);
            const recordIds = records.map((r) => r.data.id);

            if (!recordIds.length) {
                this.notification.add(_t("Please select at least one document."), { type: "warning" });
                return;
            }

            this.dialogService.add(ConfirmationDialog, {
                body: _t("Are you sure you want to delete this document from SBS?"),
                confirmLabel: _t("Delete"),
                cancelLabel: _t("Cancel"),
                confirmClass: "btn-danger",
                confirm: async () => {
                    await this._deleteFromSBS(recordIds);
                },
            });
        },

        async _deleteFromSBS(recordIds) {
            try {
                const result = await rpc("/oe_sbs/delete_from_sbs", { document_ids: recordIds });

                if (result.status === "multi" && Array.isArray(result.results)) {
                    let successCount = 0;
                    let errorMessages = [];

                    for (const res of result.results) {
                        if (res.status === "ok") {
                            successCount++;
                            this.notification.add(
                                _t(`✅ ${res.document_name}: deleted ${res.total_deleted}, ref: ${res.import_number}`),
                                { type: "success" }
                            );
                        } else {
                            errorMessages.push(`❌ ${res.document_name}: ${res.error}`);
                        }
                    }

                    if (errorMessages.length) {
                        this.notification.add(errorMessages.join("\n"), { type: "danger", sticky: true });
                    }
                    if (!successCount) {
                        this.notification.add(_t("No document was successfully deleted."), { type: "warning" });
                   } else {
                    // ✅ اینجا لیست رو رفرش می‌کنیم
                    window.location.reload();

                }


                } else {
                    this.notification.add(_t("Unexpected server response."), { type: "warning" });
                }
            } catch (error) {
                this.notification.add(_t("Connection error: could not reach the server."), {
                    type: "danger",
                    sticky: true,
                });
                console.error("RPC error:", error);
            }
        },

        async onArchive() {
            const records = this.targetRecords.filter((r) => r.data.active && !r.data.lock_uid);


            const allowedRecords = records.filter((r) => r.data.state !== "sent_to_sbs");
            const blockedRecords = records.filter((r) => r.data.state === "sent_to_sbs");

            if (blockedRecords.length > 0) {
                const blockedNames = blockedRecords.map(
                    (r) => r.data.display_name || r.data.name || r.data.id
                );
                this.notification.add(
                    _t("⚠️ The following document(s) were not archived because their state is 'sent_to_sbs':\n") +
                        blockedNames.join("\n"),
                    { type: "warning", sticky: true }
                );
            }

            if (allowedRecords.length > 0) {
                const recordIds = allowedRecords.map((r) => r.data.id);
                await this.documentService.moveToTrash(recordIds);
                await this._notifyChange();
            }
        },
    }
);
