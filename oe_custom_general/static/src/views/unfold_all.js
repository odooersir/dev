/** @odoo-module **/

import { RelationalModel } from "@web/model/relational_model/relational_model";

console.log(">>> unfold_all.js loaded!");


// Override the defaults
RelationalModel.DEFAULT_OPEN_GROUP_LIMIT = 999999;
RelationalModel.MAX_NUMBER_OPENED_GROUPS = 999999;
