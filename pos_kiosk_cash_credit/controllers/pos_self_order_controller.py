import json
import logging
from odoo import http, _
from odoo.http import request
from odoo.addons.pos_self_order.controllers.orders import PosSelfOrderController 

_logger = logging.getLogger(__name__)

class PosSelfOrderControllerCashCredit(PosSelfOrderController):
    
    @http.route('/pos_self_order/process_cash_order', type='json', auth='public', methods=['POST'], csrf=False)
    def process_cash_order(self, order_data, access_token):
        """Process cash order without payment"""
        try:
            # Validate access token
            pos_config = self._get_pos_config_from_token(access_token)
            if not pos_config:
                return {'error': 'Invalid access token'}
            
            # Create order data
            order_data.update({
                'is_cash': True,
                'is_kiosk': True,
                'state': 'draft',  # Keep as draft until cash payment
                'amount_paid': 0.0,  # No payment yet
            })
            
            # Create the order
            order = self._create_pos_order(order_data, pos_config)
            
            if not order:
                return {'error': 'Failed to create order'}
            
            # Generate order reference if needed
            if not order.pos_reference:
                order.pos_reference = order._generate_pos_reference()
            
            return {
                'id': order.id,
                'name': order.name,
                'pos_reference': order.pos_reference,
                'order_number': order.pos_reference or order.name,
                'success': True
            }
            
        except Exception as e:
            _logger.error(f"Error processing cash order: {str(e)}")
            return {'error': str(e)}
    
    @http.route('/pos_self_order/process_card_order', type='json', auth='public', methods=['POST'], csrf=False)
    def process_card_order(self, order_data, access_token):
        """Process card order and prepare for payment"""
        try:
            # Validate access token
            pos_config = self._get_pos_config_from_token(access_token)
            if not pos_config:
                return {'error': 'Invalid access token'}
            
            # Create order data for card payment
            order_data.update({
                'is_cash': False,
                'is_kiosk': True,
                'state': 'draft',
            })
            
            # Use existing order creation logic
            return super().process_order(order_data, access_token)
            
        except Exception as e:
            _logger.error(f"Error processing card order: {str(e)}")
            return {'error': str(e)}
    
    def _get_pos_config_from_token(self, access_token):
        """Get POS config from access token"""
        try:
            pos_config = request.env['pos.config'].sudo().search([
                ('access_token', '=', access_token)
            ], limit=1)
            return pos_config
        except Exception as e:
            _logger.error(f"Error getting pos config: {str(e)}")
            return None
    
    def _create_pos_order(self, order_data, pos_config):
        """Create POS order"""
        try:
            # Prepare order values
            order_vals = {
                'config_id': pos_config.id,
                'session_id': pos_config.current_session_id.id,
                'partner_id': order_data.get('partner_id'),
                'is_cash': order_data.get('is_cash', False),
                'is_kiosk': order_data.get('is_kiosk', False),
                'state': order_data.get('state', 'draft'),
                'amount_paid': order_data.get('amount_paid', 0.0),
                'lines': [],
            }
            
            # Add order lines
            if 'lines' in order_data:
                for line_data in order_data['lines']:
                    line_vals = {
                        'product_id': line_data.get('product_id'),
                        'qty': line_data.get('qty', 1),
                        'price_unit': line_data.get('price_unit', 0),
                        'price_subtotal': line_data.get('price_subtotal', 0),
                        'price_subtotal_incl': line_data.get('price_subtotal_incl', 0),
                    }
                    order_vals['lines'].append((0, 0, line_vals))
            
            # Create order
            order = request.env['pos.order'].sudo().create(order_vals)
            
            # Generate sequence number
            if not order.pos_reference:
                order.pos_reference = pos_config.sequence_id._next() if pos_config.sequence_id else f"POS{order.id:04d}"
            
            return order
            
        except Exception as e:
            _logger.error(f"Error creating pos order: {str(e)}")
            return None
    
    @http.route('/pos_self_order/print_cash_slip', type='json', auth='public', methods=['POST'], csrf=False)
    def print_cash_slip(self, order_id):
        """Generate cash slip content for printing"""
        try:
            order = request.env['pos.order'].sudo().browse(order_id)
            if not order.exists():
                return {'error': 'Order not found'}
            
            # Generate slip content
            slip_content = self._generate_cash_slip_content(order)
            
            return {
                'success': True,
                'slip_content': slip_content,
                'order_number': order.pos_reference or order.name
            }
            
        except Exception as e:
            _logger.error(f"Error generating cash slip: {str(e)}")
            return {'error': str(e)}
    
    def _generate_cash_slip_content(self, order):
        """Generate HTML content for cash slip"""
        order_ref = order.pos_reference or order.name
        
        slip_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Cash Payment Slip</title>
            <style>
                @media print {{
                    @page {{ 
                        margin: 0; 
                        size: 58mm auto;
                    }}
                    body {{ margin: 0; padding: 0; }}
                }}
                body {{
                    width: 58mm;
                    font-family: 'Courier New', monospace;
                    font-size: 12px;
                    line-height: 1.3;
                    margin: 0;
                    padding: 2mm;
                    text-align: center;
                }}
                .header {{
                    font-size: 14px;
                    font-weight: bold;
                    margin-bottom: 8px;
                }}
                .order-number {{
                    font-size: 18px;
                    font-weight: bold;
                    margin: 15px 0;
                    padding: 8px;
                    border: 2px solid #000;
                    background: #f0f0f0;
                }}
                .message {{
                    font-size: 11px;
                    margin: 12px 0;
                    line-height: 1.4;
                }}
                .separator {{
                    border-bottom: 1px dashed #000;
                    margin: 8px 0;
                }}
                .timestamp {{
                    font-size: 10px;
                    margin-top: 15px;
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <div class="header">TICKET DE COMMANDE</div>
            <div class="separator"></div>
            
            <div class="order-number">{order_ref}</div>
            
            <div class="separator"></div>
            
            <div class="message">
                <strong>Veuillez vous rendre en caisse accompagné du ticket pour payer votre commande.</strong>
            </div>
            
            <div class="message">
                <em>Please go to the cashier with this ticket to pay for your order.</em>
            </div>
            
            <div class="separator"></div>
            <div class="timestamp">
                {order.create_date.strftime('%d/%m/%Y %H:%M')}
            </div>
        </body>
        </html>
        """
        
        return slip_html