/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { DocumentsControlPanel } from "@documents/views/search/documents_control_panel";
import { rpc } from "@web/core/network/rpc";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { WarningDialog } from "@web/core/errors/error_dialogs";
import { toggleArchive, openDeleteConfirmationDialog } from "@documents/views/hooks";






patch(DocumentsControlPanel.prototype, {
  
async onSendToSBS() {
    const records = this.targetRecords.filter((r) => r.data.active);
    const recordIds = records.map((r) => r.data.id);

    if (recordIds.length === 0) {
        this.env.services.notification.add(_t("Please select at least one document."), {
            type: "warning",
        });
        return;
    }

    try {
        const result = await rpc("/oe_sbs/send_to_sbs", {
            document_ids: recordIds,
        });

        if (result.status === "multi" && Array.isArray(result.results)) {
            let successCount = 0;
            let errorMessages = [];

            for (const res of result.results) {
                if (res.status === "ok") {
                    successCount++;
                   
                   
                    //this.env.services.notification.add(
                    //    _t(`✅ ${res.document_name}: imported ${res.total_imported}, ref: ${res.import_number}`),
                    //    { type: "success" }
                    //);

                    // ساخت پیام نوتیفیکیشن
                    let notificationMessage = _t(`✅ ${res.document_name}: imported ${res.total_imported}, ref: ${res.import_number}`);
                    
                    // اضافه کردن cleanup اگر موجود بود
                    if (res.cleanup_msg) {
                        notificationMessage += `\n${res.cleanup_msg}`;
                    }

                    this.env.services.notification.add(notificationMessage, {
                        type: "success",
                        sticky: res.cleanup_msg ? true : false  // اگر cleanup داره، چسبنده باشه
                    });
                                    

             setTimeout(() => {
            window.location.reload();
        }, 1000);





                } else {
                    errorMessages.push(`❌ ${res.document_name}: ${res.error}`);
                }
            }

           
            if (errorMessages.length > 0) {
                this.env.services.dialog.add(WarningDialog, {
                    title: _t("Import Errors"),
                    message: errorMessages.join("\n"),  // پیام‌ها به صورت رشته در body می‌روند
                });
            }






            if (successCount === 0) {
                this.env.services.notification.add(_t("No document was successfully imported."), {
                    type: "warning",
                });
            }

        } else {
            this.env.services.notification.add(
                _t("Unexpected server response."),
                { type: "warning" }
            );
        }

    } catch (error) {
        let message = _t("Connection error: could not reach the server.");

        // بررسی اینکه آیا UserError یا exception متن‌دار بوده
        if (error?.message && error?.message === "Odoo Server Error") {
            const errorData = error?.data || {};
            const detailedMessage = errorData?.message || errorData?.debug || null;

            if (detailedMessage) {
                message = _t("Server Error: ") + detailedMessage;
            }
        }

        this.env.services.notification.add(message, {
            type: "danger",
            sticky: true,
        });

        console.error("RPC error:", error);
    }
},

async onDeleteFromSBS() {
    const records = this.targetRecords.filter((r) => r.data.active);
    const recordIds = records.map((r) => r.data.id);

    if (recordIds.length === 0) {
        this.env.services.notification.add(_t("Please select at least one document."), {
            type: "warning",
        });
        return;
    }

    // نمایش دیالوگ تأیید
    return new Promise((resolve) => {
        this.env.services.dialog.add(ConfirmationDialog, {
            body: _t("Are you sure you want to delete this document from SBS?"),
            confirmLabel: _t("Delete"),
            cancelLabel: _t("Cancel"),
            confirmClass: "btn-danger",
            confirm: async () => {
                resolve(await this._deleteFromSBS(recordIds));
            },
            cancel: () => resolve(false),
        });
    });
},

// متد جدید برای اجرای کد اصلی حذف
async _deleteFromSBS(recordIds) {
    try {
        const result = await rpc("/oe_sbs/delete_from_sbs", {
            document_ids: recordIds,
        });

        if (result.status === "multi" && Array.isArray(result.results)) {
            let successCount = 0;
            let errorMessages = [];

            for (const res of result.results) {
                if (res.status === "ok") {
                    successCount++;
                    this.env.services.notification.add(
                        _t(`✅ ${res.document_name}: deleted ${res.total_deleted}, ref: ${res.import_number}`),
                        { type: "success" }
                    );
                    setTimeout(() => {
                        window.location.reload();
                    }, 1000);
                } else {
                    errorMessages.push(`❌ ${res.document_name}: ${res.error}`);
                }
            }

            if (errorMessages.length > 0) {
                this.env.services.notification.add(
                    errorMessages.join("\n"),
                    { type: "danger", sticky: true }
                );
            }

            if (successCount === 0) {
                this.env.services.notification.add(_t("No document was successfully deleted."), {
                    type: "warning",
                });
            }
        } else {
            this.env.services.notification.add(
                _t("Unexpected server response."),
                { type: "warning" }
            );
        }
    } catch (error) {
        let message = _t("Connection error: could not reach the server.");

        if (error?.message && error?.message === "Odoo Server Error") {
            const errorData = error?.data || {};
            const detailedMessage = errorData?.message || errorData?.debug || null;

            if (detailedMessage) {
                message = _t("Server Error: ") + detailedMessage;
            }
        }

        this.env.services.notification.add(message, {
            type: "danger",
            sticky: true,
        });

        console.error("RPC error:", error);
    }
},



async onArchive() {
    const records = this.targetRecords.filter((r) => r.data.active);

    const allowedRecords = records.filter((r) => r.data.state !== 'sent_to_sbs');
    const blockedRecords = records.filter((r) => r.data.state === 'sent_to_sbs');

    // نمایش پیغام رکوردهای مسدود شده
    if (blockedRecords.length > 0) {
        const blockedNames = blockedRecords.map(r => r.data.display_name || r.data.name || r.data.id);
        this.env.services.notification.add(
            `⚠️ The following record(s) were not archived because their state is 'sent_to_sbs':\n${blockedNames.join("\n")}`,
            { type: "warning", sticky: true }
        );
    }

    // آرشیو رکوردهای مجاز
    if (allowedRecords.length > 0) {
        
        const recordIds = allowedRecords.map((r) => r.data.id);
        await toggleArchive(allowedRecords[0].model, allowedRecords[0].resModel, recordIds, true);
        await this.notifyChange();


    }
},

async onDelete() {
    alert(6);
    const records = this.targetRecords;

    // رکوردهایی که در وضعیت sent_to_sbs هستند را جدا می‌کنیم
    const blockedRecords = records.filter(r => r.data.state === 'sent_to_sbs');
    const allowedRecords = records.filter(r => r.data.state !== 'sent_to_sbs');

    // اگر رکورد مسدود وجود دارد، حذف را متوقف می‌کنیم و هشدار می‌دهیم
    if (blockedRecords.length > 0) {
        const blockedNames = blockedRecords.map(
            r => r.data.display_name || r.data.name || r.data.id
        );
        this.env.services.notification.add(
            `🚫 The following record(s) cannot be deleted because their state is 'sent_to_sbs':\n${blockedNames.join("\n")}`,
            { type: "warning", sticky: true }
        );
        return; // هیچ دیالوگی نمایش داده نمی‌شود و حذف انجام نمی‌گیرد
    }

    // اگر هیچ رکورد مسدودی وجود ندارد، منطق اصلی حذف اجرا می‌شود
    if (!(await openDeleteConfirmationDialog(this.env.model, true))) {
        return;
    }

    const model = this.env.model;
    await model.root.deleteRecords(allowedRecords);
    await model.load(this.env.model.config);
    await this.notifyChange();
},



async onCreateTemplate() {
    const records = this.targetRecords.filter((r) => r.data.active);
    if (records.length !== 1) {
        this.env.services.notification.add(
            _t("Please select exactly one document to create a template from."),
            { type: "warning" }
        );
        return;
    }
    try {
        const action = await this.env.services.orm.call(
            "documents.document",
            "action_create_sbs_template",
            [[records[0].data.id]]
        );
        await this.env.services.action.doAction(action);
    } catch (error) {
        const detail = error?.data?.message || error?.message || _t("Unknown error");
        this.env.services.notification.add(_t("Could not create template: ") + detail, {
            type: "danger",
            sticky: true,
        });
        console.error("Create template error:", error);
    }
},

});
