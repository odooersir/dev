/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProjectTaskStateSelection } from "@project/components/project_task_state_selection/project_task_state_selection";

patch(ProjectTaskStateSelection.prototype, {
    setup() {
        // اجرای setup اصلی
        super.setup();

        // افزودن وضعیت جدید به آیکون‌ها، رنگ‌ها، و دکمه‌ها
        this.icons["manager_approved"] = "fa fa-lg fa-thumbs-o-up";
        this.colorIcons["manager_approved"] = "text-primary";
        this.colorButton["manager_approved"] = "btn-outline-primary";
    },

    // 🔹 افزودن وضعیت جدید به لیست گزینه‌ها (dropdown)
    get options() {
        const labels = new Map(super.options);
        const states = ["1_canceled", "1_done", "manager_approved"];
        const currentState = this.props.record.data[this.props.name];
        if (currentState != "04_waiting_normal") {
            states.unshift("01_in_progress", "02_changes_requested", "03_approved");
        }
        return states.map((state) => [state, labels.get(state) || this.getLabel(state)]);
    },

    // 🔹 افزودن label برای وضعیت جدید
    getLabel(state) {
        const labels = {
            manager_approved: "Manager Approved",
        };
        return labels[state] || state;
    },
});
