from odoo import api, fields, models, _



class Currency(models.Model):
    _inherit = 'res.currency'


    def write(self, vals):
        res = super().write(vals)
        
        print ("curencccccccccccyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy")
        print (vals)
     
            
        if 'rate_ids' in vals:
            print(">>> Currency rates changed, recomputing selling prices...")
            self.env['sbs.data'].sudo().compute_selling_prices()
            self.env.cr.flush()  # خیلی مهم: sync ORM با DB
            self.env['sbs.data'].sudo().action_rank_products()


        return res
	