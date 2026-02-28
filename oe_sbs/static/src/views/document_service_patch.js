import { patch } from "@web/core/utils/patch";
import { DocumentService } from "@documents/core/document_service";
import { _t } from "@web/core/l10n/translation";

patch(DocumentService.prototype, {
    async moveToTrash(documentIds) {
        // دریافت state اسناد
        const documents = await this.orm.call(
            "documents.document",
            "read",
            [documentIds, ["id", "state", "display_name", "name"]]
        );

        const allowedIds = documents
            .filter((doc) => doc.state !== "sent_to_sbs")
            .map((doc) => doc.id);

        const blockedDocs = documents.filter((doc) => doc.state === "sent_to_sbs");

        // نمایش هشدار برای اسناد مسدود شده
        if (blockedDocs.length > 0) {
            const blockedNames = blockedDocs.map(
                (doc) => doc.display_name || doc.name || doc.id
            );
            this.notification.add(
                _t(
                    "⚠️ The following document(s) were not moved to trash because their state is 'sent_to_sbs':\n%s",
                    blockedNames.join("\n")
                ),
                { type: "warning", sticky: true }
            );
        }

        // اگر هیچ سند مجازی نباشد
        if (allowedIds.length === 0) {
            return false;
        }

        // فراخوانی منطق اصلی با اسناد مجاز
        return await super.moveToTrash(allowedIds);
    },
});
