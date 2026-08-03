from odoo import models, fields, api
import re
import logging

_logger = logging.getLogger(__name__)


# The set of mappable target fields. Keep this in sync with the *_col fields
# on sbs.import.template. The label is what a user sees in the dictionary.
SBS_FIELD_KEYS = [
    ('ean_col',             'EAN'),
    ('hs_code_col',         'HS Code'),
    ('cover_language_col',  'Language'),
    ('product_name_col',    'Product Name'),
    ('price_col',           'Price'),
    ('supplier_code_col',   'Supplier Code'),
    ('brand_col',           'Brand'),
    ('size_col',            'Size'),
    ('case_size_col',       'Unit/Case'),
    ('layer_col',           'Case/Layer'),
    ('pallet_col',          'Case/Pallet'),
    ('available_qty_col',   'Available Unit'),
    ('unit_per_layer_col',  'Unit/Layer'),
    ('unit_per_pallet_col', 'Unit/Pallet'),
    ('moq_col',             'MOQ'),
    ('mov_col',             'MOV'),
    ('payment_terms_col',   'Payment Terms'),
    ('incoterms_col',       'Incoterms'),
    ('batch_code_col',      'Batch Code'),
    ('coo_col',             'COO'),
    ('lead_time_col',       'Lead Time'),
    ('note_col',            'Note'),
]


def normalize_synonym(text):
    """
    Lowercase + collapse whitespace, and tighten spaces around a slash so
    'Case/ Layer', 'Case /Layer', 'Case / Layer' all become 'case/layer'.
    Mirrors the client/template _norm().
    """
    s = re.sub(r'\s+', ' ', str(text or '').strip().lower())
    s = re.sub(r'\s*/\s*', '/', s)   # "case/ layer" -> "case/layer"
    return s


class SBSFieldSynonym(models.Model):
    _name = 'sbs.field.synonym'
    _description = 'SBS Auto-Map Synonym'
    _order = 'field_key, synonym'

    field_key = fields.Selection(
        selection=SBS_FIELD_KEYS, string='Target Field', required=True, index=True)
    synonym = fields.Char(string='Synonym (header text)', required=True, index=True)
    source = fields.Selection([
        ('system', 'System'),
        ('learned', 'Learned'),
        ('manual', 'Manual'),
    ], string='Source', default='manual', required=True)
    seen_count = fields.Integer(string='Times Seen', default=1)
    # Templates that rely on this synonym. A synonym is shared knowledge: several
    # mappings can point at the same (field, header) pair. When a mapping is
    # deleted/deactivated it is removed from this list, and the synonym itself is
    # dropped only once no mapping references it any more (see _prune_orphans).
    mapping_ids = fields.Many2many(
        'sbs.import.template', 'sbs_synonym_template_rel',
        'synonym_id', 'template_id', string='Mappings')
    mapping_count = fields.Integer(string='# Mappings', compute='_compute_mapping_count')

    @api.depends('mapping_ids')
    def _compute_mapping_count(self):
        for rec in self:
            rec.mapping_count = len(rec.mapping_ids)

    @api.model
    def normalize_synonym(self, text):
        """Model-level wrapper so other models (e.g. the conflict wizard) can
        normalize header text without importing the module-level helper across
        packages (which fails as 'from oe_sbs...' in Odoo)."""
        return normalize_synonym(text)

    _sql_constraints = [
        ('uniq_field_synonym', 'unique(field_key, synonym)',
         'This synonym already exists for that field.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        # A row created directly by a user (not via learn_synonym) is 'manual'.
        for vals in vals_list:
            if 'synonym' in vals:
                vals['synonym'] = normalize_synonym(vals['synonym'])
            vals.setdefault('source', 'manual')
        return super().create(vals_list)

    def write(self, vals):
        if 'synonym' in vals:
            vals['synonym'] = normalize_synonym(vals['synonym'])
        return super().write(vals)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------
    @api.model
    def get_automap_dict(self, supplier_id=False):
        """
        Return {field_key: [synonym, ...]} for auto-mapping.

        A synonym is "supplier-specific" if any of its linked templates belongs
        to a supplier; it is "generic" if it has source='system' OR no linked
        template carries a supplier (mapping_ids empty / supplier-less).

        When supplier_id is given, the result is restricted to:
          * this supplier's own synonyms, PLUS
          * generic synonyms,
        with the SUPPLIER's entry winning when the same (field_key, synonym text)
        exists both for the supplier and generically (supplier-first priority).

        When supplier_id is falsy, every synonym is returned (legacy behaviour),
        so the template-builder path (where the supplier may be unknown yet)
        keeps working exactly as before.
        """
        recs = self.sudo().search([])

        def _suppliers_of(rec):
            # set of supplier ids attached to this synonym via its templates
            return {t.supplier_id.id for t in rec.mapping_ids if t.supplier_id}

        def _is_generic(rec):
            return rec.source == 'system' or not _suppliers_of(rec)

        # No supplier context: return everything (unchanged behaviour).
        if not supplier_id:
            result = {}
            for r in recs:
                result.setdefault(r.field_key, []).append(r.synonym)
            return result

        supplier_id = int(supplier_id)
        # Collect, per field_key, the supplier's own synonyms and generic ones.
        owned = {}          # field_key -> list of synonyms (supplier-first)
        owned_keys = set()  # (field_key, synonym_lower) - exact same mapping
        owned_headers = set()  # just the header text the supplier owns (any field)
        generic = {}        # field_key -> list of synonyms

        for r in recs:
            sups = _suppliers_of(r)
            if supplier_id in sups:
                owned.setdefault(r.field_key, []).append(r.synonym)
                key = (r.synonym or '').lower()
                owned_keys.add((r.field_key, key))
                owned_headers.add(key)

        for r in recs:
            if _is_generic(r):
                generic.setdefault(r.field_key, []).append(r.synonym)

        # Merge: supplier-owned first, then generics - but DROP any generic whose
        # header the supplier already owns on ANY field. This makes supplier
        # priority work at the HEADER level: if the supplier taught 'X -> Z',
        # a leftover generic 'X -> Y' (e.g. a seed) must not compete, otherwise
        # auto-map could still pick Y just because its field comes first.
        result = {}
        for fk, syns in owned.items():
            result.setdefault(fk, []).extend(syns)
        for fk, syns in generic.items():
            for s in syns:
                if (s or '').lower() in owned_headers:
                    continue   # supplier owns this header (on some field) -> skip generic
                result.setdefault(fk, []).append(s)
        return result

    @api.model
    def learn_synonym(self, field_key, header_text, source='learned', template_id=False):
        """
        Record a header for a field, linking it to the template that taught it.
        A synonym is shared knowledge: many templates can reference the same
        (field, header) pair.
          - (field, header) already exists -> add template to mapping_ids, bump count
          - otherwise                       -> create it and link the template
        Conflict handling (same header on a DIFFERENT field) is NOT auto-resolved
        here; the caller is expected to have asked the user first via
        detect_conflicts. Returns a short status string.
        """
        norm = normalize_synonym(header_text)
        if not field_key or not norm:
            return 'skipped'
        valid_keys = {k for k, _ in SBS_FIELD_KEYS}
        if field_key not in valid_keys:
            return 'skipped'

        existing = self.sudo().search(
            [('field_key', '=', field_key), ('synonym', '=', norm)], limit=1)
        if existing:
            existing.seen_count += 1
            if template_id:
                existing.mapping_ids = [(4, template_id)]   # add, deduped by ORM
            return 'bumped'

        vals = {
            'field_key': field_key,
            'synonym': norm,
            'source': source,
            'seen_count': 1,
        }
        if template_id:
            vals['mapping_ids'] = [(4, template_id)]
        self.sudo().create(vals)
        return 'created'

    @api.model
    def detect_conflicts(self, pairs, template_id=False):
        """
        Given [(field_key, header_text), ...], return conflicts where the same
        header is already attached to a DIFFERENT field FOR THE SAME SUPPLIER.

        Supplier rule (per the agreed table): the same header may map to two
        different fields as long as the suppliers differ. A collision is a real
        conflict ONLY when the existing synonym and the new mapping belong to the
        same supplier (or both are generic / supplier-less). Different suppliers,
        or one supplier-specific vs one generic, are allowed.

        template_id is the template being confirmed; its supplier defines the
        "new" side. Output:
          [{'header': 'qty/plt', 'new_field': 'unit_per_pallet_col',
            'existing_field': 'case_pallet_col'}, ...]
        """
        # supplier of the template we're confirming (the "new" side)
        new_supplier = False
        if template_id:
            tmpl = self.env['sbs.import.template'].sudo().browse(template_id)
            new_supplier = tmpl.supplier_id.id if tmpl.supplier_id else False

        def _suppliers_of(syn):
            return {t.supplier_id.id for t in syn.mapping_ids if t.supplier_id}

        conflicts = []
        for field_key, header_text in pairs:
            norm = normalize_synonym(header_text)
            if not norm or not field_key:
                continue
            others = self.sudo().search([
                ('synonym', '=', norm), ('field_key', '!=', field_key)])
            for o in others:
                existing_suppliers = _suppliers_of(o)
                # Decide if the existing synonym clashes with the new mapping:
                #  - both generic (no supplier on either side) -> clash
                #  - new supplier is among the existing synonym's suppliers -> clash
                #  - otherwise (different suppliers, or generic-vs-specific) -> OK
                if not existing_suppliers and not new_supplier:
                    same = True                      # both generic
                elif new_supplier and new_supplier in existing_suppliers:
                    same = True                      # same supplier
                else:
                    same = False                     # different / generic-vs-specific
                if same:
                    conflicts.append({
                        'header': norm,
                        'new_field': field_key,
                        'existing_field': o.field_key,
                    })
        return conflicts

    @api.model
    def prune_orphans(self, synonym_ids=None):
        """
        Delete learned synonyms that no longer belong to any mapping. System
        seeds (source='system') are never pruned. Called after a template is
        removed from synonyms' mapping_ids.
        """
        domain = [('mapping_ids', '=', False), ('source', '!=', 'system')]
        if synonym_ids:
            domain.append(('id', 'in', synonym_ids))
        orphans = self.sudo().search(domain)
        n = len(orphans)
        if n:
            orphans.unlink()
            _logger.info("[SBS] pruned %s orphan synonym(s) with no mapping.", n)
        return n
