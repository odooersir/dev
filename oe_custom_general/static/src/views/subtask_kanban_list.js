/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { SubtaskKanbanList } from "@project/components/subtask_kanban_list/subtask_kanban_list";

patch(SubtaskKanbanList.prototype, {
    // می‌توانیم getter closedList را امن کنیم
    get closedList() {
        try {
            // دسترسی امن با optional chaining
            return this.list?.records?.filter((child) => {
                //return child?.data && !["1_done", "1_canceled"].includes(child.data.state);
                return child?.data && ![].includes(child.data.state);

            }) || [];
        } catch (err) {
            console.warn("⚠️ error accessing closedList for SubtaskKanbanList", err);
            return [];
        }
    },

   
});
