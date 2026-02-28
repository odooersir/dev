/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, xml } from "@odoo/owl";

class BlankDashboard extends Component {
    static template = xml`<div class="o_blank_dashboard" style="text-align:center"><h2>Welcome to Smart Business System</h2><p>Select a menu to continue.</p></div>`;
}

registry.category("actions").add("sbs.blank.dashboard", BlankDashboard);
