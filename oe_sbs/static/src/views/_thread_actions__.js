/** @odoo-module **/

import { threadActionsRegistry } from "@mail/core/common/thread_actions";
import { useComponent } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

threadActionsRegistry.add("expand-list-current", {
    condition(component) {
        return !!component.thread && component.props.chatWindow?.isOpen;
    },
    setup() {
        const component = useComponent();
        component.actionService = useService("action");
        component.orm = useService("orm"); // 🔹 این خط اضافه شد
    },
    icon: "fa fa-fw fa-list-ul",
    name: _t("Open List (Current Record)"),
    async open(component) {
        const model = component.thread.model;
        const recordId = component.thread.id;

        if (!model || !recordId) {
            return;
        }

        let listViewId = false;

       // try {
            const viewData = await component.orm.searchRead(
                "ir.ui.view",
                [
                  
                    [
                        "name",
                        "in",
                        [
                            model === "documents.document"
                                ? "documents.list.oe_custom"
                                : "",
                        ].filter(Boolean),
                    ],
                ],
                ["id"]
            );

            if (viewData.length > 0) {
                listViewId = viewData[0].id;
            }
        //} catch (e) {
         //   console.warn("Failed to get list view id:", e);
        //}

       // alert(model);
        //alert(listViewId);

        component.actionService.doAction({
            type: "ir.actions.act_window",
            name: `Open ${model} (Current Record)`,
            res_model: model,
            domain: [["id", "=", recordId]],
            views: [[listViewId || false, "list"]],
            target: "current",
        });

        component.props.chatWindow.close();
    },
    sequence: 41,
    sequenceGroup: 20,
});

threadActionsRegistry.add("expand-list-all", {
    condition(component) {
        return !!component.thread && component.props.chatWindow?.isOpen;
    },
    setup() {
        const component = useComponent();
        component.actionService = useService("action");
    },
    icon: "fa fa-fw fa-list",
    name: _t("Open Full List"),
    open(component) {
        const model = component.thread.model;
        let actionExternalId = null;

        switch (model) {
            case "documents.document":
                actionExternalId = "documents.document_action";
                break;
            // case "sale.order":
            //     actionExternalId = "sale.action_quotations";
            //     break;
            // case "project.task":
            //     actionExternalId = "project.action_view_task";
            //     break;
            default:
                actionExternalId = null;
        }

        if (actionExternalId) {
            component.actionService.doAction(actionExternalId);
        } else {
            component.actionService.doAction({
                name: `Open ${model} (All Record)`,
                type: "ir.actions.act_window",
                res_model: model,
                views: [[false, "list"]],
                target: "current",
            });
        }
        component.props.chatWindow.close();
    },
    sequence: 42,
    sequenceGroup: 20,
});
