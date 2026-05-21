/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { ProjectTaskRecord } from "@project/views/project_task_kanban/project_task_kanban_model";

const originalSetup = ProjectTaskRecord.prototype.setup;

patch(ProjectTaskRecord.prototype, {
    setup() {
        try {
            originalSetup.call(this, ...arguments);
            console.log("🔥 setup for task", this.data.display_name);

            if (!this._initialSubtasksCallStarted) {
                this._initialSubtasksCallStarted = true;

                // فقط اگر toggleSubtasksList موجود باشد و subtasks داشته باشیم
                if (this.toggleSubtasksList) {
                    this.toggleSubtasksList()
                        .then(() => {
                            console.log("✅ subtasks opened for", this.data.display_name);
                        })
                        .catch((err) => {
                            console.warn("⚠️ failed to open subtasks for", this.data.display_name, err);
                            this.displaySubtasks = false;
                        });
                } else {
                    console.log("ℹ️ no subtasks or toggle not ready for", this.data.display_name);
                }
            }
        } catch (err) {
            console.error("❌ error in ProjectTaskRecord.setup:", err);
        }
    },
});
