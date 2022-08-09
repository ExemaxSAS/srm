# -*- coding: utf-8 -*-

import logging
import threading
from datetime import date, datetime, timedelta
from psycopg2 import sql

from odoo import api, fields, models, tools, SUPERUSER_ID
from odoo.osv import expression
from odoo.tools.translate import _
from odoo.tools import email_re, email_split
from odoo.exceptions import UserError, AccessError
from odoo.addons.phone_validation.tools import phone_validation
from collections import OrderedDict, defaultdict

from . import srm_stage

_logger = logging.getLogger(__name__)

class Srm(models.Model):
    _name = 'srm.lead'
    _description = "SRM Lead/Opportunity"
    _order = "priority desc, id desc"
    _inherit = ['mail.thread.cc',
                'mail.thread.blacklist',
                'mail.thread.phone',
                'mail.activity.mixin',
                'utm.mixin',
                'format.address.mixin',
                'phone.validation.mixin']
    _primary_email = 'email_from'

    # Description
    name = fields.Char(
        'Oportunidad', index=True, required=True, readonly=False, store=True)
    user_id = fields.Many2one('res.users', string='Encargado de compras', index=True, tracking=True, default=lambda self: self.env.user)
    user_email = fields.Char('Correo del usuario', related='user_id.email', readonly=True)
    user_login = fields.Char('Usuario registrado', related='user_id.login', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañia', index=True, default=lambda self: self.env.company.id)
    referred = fields.Char('Referido por')
    description = fields.Text('Notas')
    active = fields.Boolean('Active', default=True, tracking=True)
    type = fields.Selection([
        ('lead', 'Lead'), ('opportunity', 'Opportunity')],
        index=True, required=True, tracking=15,
        default='lead')
    priority = fields.Selection(
        srm_stage.AVAILABLE_PRIORITIES, string='Prioridad', index=True,
        default=srm_stage.AVAILABLE_PRIORITIES[0][0])
    #team_id = fields.Many2one(
    #    'crm.team', string='Sales Team', index=True, tracking=True,
    #    compute='_compute_team_id', readonly=False, store=True)
    stage_id = fields.Many2one(
        'srm.stage', string='Etapa', index=True, tracking=True, readonly=False, store=True,
        copy=False, group_expand='_read_group_stage_ids', ondelete='restrict')
    kanban_state = fields.Selection([
        ('grey', 'No next activity planned'),
        ('red', 'Next activity late'),
        ('green', 'Next activity is planned')], string='Kanban State')
    activity_date_deadline_my = fields.Date(
        'My Activities Deadline', compute='_compute_activity_date_deadline_my',
        search='_search_activity_date_deadline_my', compute_sudo=False,
        readonly=True, store=False, groups="base.group_user")
    tag_ids = fields.Many2many(
       'srm.tag', 'srm_tag_rel', 'lead_id', 'tag_id', string='Etiquetas',
       help="Clasificar y analizar sus categorías de oportunidad como: Servicio, capacitación.")
    color = fields.Integer('Color', default=0)
    # Opportunity specific
    expected_revenue = fields.Monetary('Ingreso esperado', currency_field='company_currency', tracking=True)
    prorated_revenue = fields.Monetary('Ingreso prorrateado', currency_field='company_currency', store=True)
    recurring_revenue = fields.Monetary('Ingreso Recurrente', currency_field='company_currency')

    company_currency = fields.Many2one("res.currency", string='Moneda', related='company_id.currency_id', readonly=True)
    # Dates
    date_closed = fields.Datetime('Fecha de cierre', readonly=True, copy=False)
    date_action_last = fields.Datetime('Última Acción', readonly=True)
    date_open = fields.Datetime(
        'Assignment Date', readonly=True, store=True)
    day_open = fields.Float('Days to Assign', store=True)
    day_close = fields.Float('Days to Close', store=True)
    date_last_stage_update = fields.Datetime(
        'Last Stage Update', index=True, readonly=True, store=True)
    date_conversion = fields.Datetime('Conversion Date', readonly=True)
    date_deadline = fields.Date('Expectativa de cierre', help="Estimate of the date on which the opportunity will be won.")
    # Supplier / contact
    partner_id = fields.Many2one(
        'res.partner', string='Proveedor', index=True, tracking=10,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="Linked partner (optional). Usually created when converting the lead. You can find a partner by its Name, TIN, Email or Internal Reference.")
    partner_is_blacklisted = fields.Boolean('Partner is blacklisted', related='partner_id.is_blacklisted', readonly=True)
    contact_name = fields.Char(
        'Nombre de contacto', tracking=30, readonly=False, store=True)
    partner_name = fields.Char(
        'Nombre de compañia', tracking=20, index=True, readonly=False, store=True,
        help='The name of the future partner company that will be created while converting the lead into opportunity')
    function = fields.Char('Puesto de trabajo', readonly=False, store=True)
    title = fields.Many2one('res.partner.title', string='Titulo', readonly=False, store=True)
    email_from = fields.Char(
        'Correo electrónico', tracking=40, index=True, inverse='_inverse_email_from', readonly=False, store=True)
    phone = fields.Char(
        'Teléfono', tracking=50,
        compute='_compute_phone', inverse='_inverse_phone', readonly=False, store=True)
    mobile = fields.Char('Móvil', readonly=False, store=True)
    phone_mobile_search = fields.Char('Phone/Mobile', store=False, search='_search_phone_mobile_search')
    phone_state = fields.Selection([
        ('correct', 'Correct'),
        ('incorrect', 'Incorrect')], string='Phone Quality', store=True)
    email_state = fields.Selection([
        ('correct', 'Correct'),
        ('incorrect', 'Incorrect')], string='Email Quality', store=True)
    website = fields.Char('Sitio Web', index=True, help="Website of the contact", readonly=False, store=True)
    lang_id = fields.Many2one('res.lang', string='Idioma')
    # Address fields
    street = fields.Char('Calle', readonly=False, store=True)
    street2 = fields.Char('Calle 2', readonly=False, store=True)
    zip = fields.Char('Codigo postal', change_default=True, readonly=False, store=True)
    city = fields.Char('Ciudad', readonly=False, store=True)
    state_id = fields.Many2one(
        "res.country.state", string='Provincia', readonly=False, store=True,
        domain="[('country_id', '=?', country_id)]")
    country_id = fields.Many2one(
        'res.country', string='Pais', readonly=False, store=True)
    # Probability (Opportunity only)
    probability = fields.Float(
        'Probabilidad', group_operator="avg", copy=False, readonly=False, store=True)
    automated_probability = fields.Float('Automated Probability', readonly=True, store=True)
    is_automated_probability = fields.Boolean('Is automated probability?')
    # External records
    meeting_count = fields.Integer('# Meetings')
    #lost_reason = fields.Many2one(
    #    'crm.lost.reason', string='Lost Reason',
    #    index=True, ondelete='restrict', tracking=True)
    ribbon_message = fields.Char('Ribbon message')

    _sql_constraints = [
        ('check_probability', 'check(probability >= 0 and probability <= 100)', 'The probability of closing the deal should be between 0% and 100%!')
    ]


    @api.depends('partner_id.phone')
    def _compute_phone(self):
        for lead in self:
            if lead.partner_id.phone and lead._get_partner_phone_update():
                lead.phone = lead.partner_id.phone

    def _inverse_phone(self):
        for lead in self:
            if lead._get_partner_phone_update():
                lead.partner_id.phone = lead.phone

    def _inverse_email_from(self):
        for lead in self:
            if lead._get_partner_email_update():
                lead.partner_id.email = lead.email_from

    def _get_partner_email_update(self):
        """Calculate if we should write the email on the related partner. When
        the email of the lead / partner is an empty string, we force it to False
        to not propagate a False on an empty string.

        Done in a separate method so it can be used in both ribbon and inverse
        and compute of email update methods.
        """
        self.ensure_one()
        if self.partner_id and self.email_from != self.partner_id.email:
            lead_email_normalized = tools.email_normalize(self.email_from) or self.email_from or False
            partner_email_normalized = tools.email_normalize(self.partner_id.email) or self.partner_id.email or False
            return lead_email_normalized != partner_email_normalized
        return False

    def _get_partner_phone_update(self):
        """Calculate if we should write the phone on the related partner. When
        the phone of the lead / partner is an empty string, we force it to False
        to not propagate a False on an empty string.

        Done in a separate method so it can be used in both ribbon and inverse
        and compute of phone update methods.
        """
        self.ensure_one()
        if self.partner_id and self.phone != self.partner_id.phone:
            lead_phone_formatted = self.phone_format(self.phone) if self.phone else False or self.phone or False
            partner_phone_formatted = self.phone_format(self.partner_id.phone) if self.partner_id.phone else False or self.partner_id.phone or False
            return lead_phone_formatted != partner_phone_formatted
        return False

    def _search_phone_mobile_search(self, operator, value):
        if len(value) <= 2:
            raise UserError(_('Please enter at least 3 digits when searching on phone / mobile.'))

        query = f"""
                SELECT model.id
                FROM {self._table} model
                WHERE REGEXP_REPLACE(model.phone, '[^\d+]+', '', 'g') SIMILAR TO CONCAT(%s, REGEXP_REPLACE(%s, '\D+', '', 'g'), '%%')
                  OR REGEXP_REPLACE(model.mobile, '[^\d+]+', '', 'g') SIMILAR TO CONCAT(%s, REGEXP_REPLACE(%s, '\D+', '', 'g'), '%%')
            """

        # searching on +32485112233 should also finds 00485112233 (00 / + prefix are both valid)
        # we therefore remove it from input value and search for both of them in db
        if value.startswith('+') or value.startswith('00'):
            if value.startswith('00'):
                value = value[2:]
            starts_with = '00|\+'
        else:
            starts_with = '%'

        self._cr.execute(query, (starts_with, value, starts_with, value))
        res = self._cr.fetchall()
        if not res:
            return [(0, '=', 1)]
        return [('id', 'in', [r[0] for r in res])]

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def toggle_active(self):
        """ When archiving: mark probability as 0. When re-activating
        update probability again, for leads and opportunities. """
        res = super(Lead, self).toggle_active()
        activated = self.filtered(lambda lead: lead.active)
        archived = self.filtered(lambda lead: not lead.active)
        if activated:
            activated.write({'lost_reason': False})
            activated._compute_probabilities()
        if archived:
            archived.write({'probability': 0, 'automated_probability': 0})
        return res

    def action_set_lost(self, **additional_values):
        """ Lost semantic: probability = 0 or active = False """
        res = self.action_archive()
        if additional_values:
            self.write(dict(additional_values))
        return res

    def action_set_won(self):
        """ Won semantic: probability = 100 (active untouched) """
        self.action_unarchive()
        # group the leads by team_id, in order to write once by values couple (each write leads to frequency increment)
        leads_by_won_stage = {}
        for lead in self:
            stage_id = lead._stage_find(domain=[('is_won', '=', True)])
            if stage_id in leads_by_won_stage:
                leads_by_won_stage[stage_id] |= lead
            else:
                leads_by_won_stage[stage_id] = lead
        for won_stage_id, leads in leads_by_won_stage.items():
            leads.write({'stage_id': won_stage_id.id, 'probability': 100})
        return True

    def action_set_automated_probability(self):
        self.write({'probability': self.automated_probability})

    def action_set_won_rainbowman(self):
        self.ensure_one()
        self.action_set_won()

        message = self._get_rainbowman_message()
        if message:
            return {
                'effect': {
                    'fadeout': 'slow',
                    'message': message,
                    'img_url': '/web/image/%s/%s/image_1024' % (self.team_id.user_id._name, self.team_id.user_id.id) if self.team_id.user_id.image_1024 else '/web/static/src/img/smile.svg',
                    'type': 'rainbow_man',
                }
            }
        return True

    def get_rainbowman_message(self):
        self.ensure_one()
        if self.stage_id.is_won:
            return self._get_rainbowman_message()
        return False

    def _get_rainbowman_message(self):
        message = False
        if self.user_id and self.team_id and self.expected_revenue:
            self.flush()  # flush fields to make sure DB is up to date
            query = """
                SELECT
                    SUM(CASE WHEN user_id = %(user_id)s THEN 1 ELSE 0 END) as total_won,
                    MAX(CASE WHEN date_closed >= CURRENT_DATE - INTERVAL '30 days' AND user_id = %(user_id)s THEN expected_revenue ELSE 0 END) as max_user_30,
                    MAX(CASE WHEN date_closed >= CURRENT_DATE - INTERVAL '7 days' AND user_id = %(user_id)s THEN expected_revenue ELSE 0 END) as max_user_7,
                    MAX(CASE WHEN date_closed >= CURRENT_DATE - INTERVAL '30 days' AND team_id = %(team_id)s THEN expected_revenue ELSE 0 END) as max_team_30,
                    MAX(CASE WHEN date_closed >= CURRENT_DATE - INTERVAL '7 days' AND team_id = %(team_id)s THEN expected_revenue ELSE 0 END) as max_team_7
                FROM crm_lead
                WHERE
                    type = 'opportunity'
                AND
                    active = True
                AND
                    probability = 100
                AND
                    DATE_TRUNC('year', date_closed) = DATE_TRUNC('year', CURRENT_DATE)
                AND
                    (user_id = %(user_id)s OR team_id = %(team_id)s)
            """
            self.env.cr.execute(query, {'user_id': self.user_id.id,
                                        'team_id': self.team_id.id})
            query_result = self.env.cr.dictfetchone()

            if query_result['total_won'] == 1:
                message = _('Go, go, go! Congrats for your first deal.')
            elif query_result['max_team_30'] == self.expected_revenue:
                message = _('Boom! Team record for the past 30 days.')
            elif query_result['max_team_7'] == self.expected_revenue:
                message = _('Yeah! Deal of the last 7 days for the team.')
            elif query_result['max_user_30'] == self.expected_revenue:
                message = _('You just beat your personal record for the past 30 days.')
            elif query_result['max_user_7'] == self.expected_revenue:
                message = _('You just beat your personal record for the past 7 days.')
        return message

    def action_schedule_meeting(self):
        """ Open meeting's calendar view to schedule meeting on current opportunity.
            :return dict: dictionary value for created Meeting view
        """
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("calendar.action_calendar_event")
        partner_ids = self.env.user.partner_id.ids
        if self.partner_id:
            partner_ids.append(self.partner_id.id)
        current_opportunity_id = self.id if self.type == 'opportunity' else False
        action['context'] = {
            'search_default_opportunity_id': current_opportunity_id,
            'default_opportunity_id': current_opportunity_id,
            'default_partner_id': self.partner_id.id,
            'default_partner_ids': partner_ids,
            'default_attendee_ids': [(0, 0, {'partner_id': pid}) for pid in partner_ids],
            'default_team_id': self.team_id.id,
            'default_name': self.name,
        }
        return action

    def action_snooze(self):
        self.ensure_one()
        today = date.today()
        my_next_activity = self.activity_ids.filtered(lambda activity: activity.user_id == self.env.user)[:1]
        if my_next_activity:
            if my_next_activity.date_deadline < today:
                date_deadline = today + timedelta(days=7)
            else:
                date_deadline = my_next_activity.date_deadline + timedelta(days=7)
            my_next_activity.write({
                'date_deadline': date_deadline
            })
        return True

    # TODO verificar lista de etapas necesarias
    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        # retrieve team_id from the context and write the domain
        # - ('id', 'in', stages.ids): add columns that should be present
        # - OR ('fold', '=', False): add default columns that are not folded
        # - OR ('team_ids', '=', team_id), ('fold', '=', False) if team_id: add team columns that are not folded

        # team_id = self._context.get('default_team_id')
        # if team_id:
        #     search_domain = ['|', ('id', 'in', stages.ids), '|', ('team_id', '=', False), ('team_id', '=', team_id)]
        # else:
        #     search_domain = ['|', ('id', 'in', stages.ids), ('team_id', '=', False)]

        search_domain=[]
        # perform search
        stage_ids = stages._search(search_domain, order=order, access_rights_uid=SUPERUSER_ID)
        return stages.browse(stage_ids)


    def action_sale_quotations_new(self):
        if not self.partner_id:
            return self.env["ir.actions.actions"]._for_xml_id("srm.srm_quotation_partner_action")
        else:
            return self.action_new_quotation()


    def action_new_quotation(self):
        action = self.env["ir.actions.actions"]._for_xml_id("srm.purchase_action_quotations_new")
        action['context'] = {
        #     'search_default_opportunity_id': self.id,
        #     'default_opportunity_id': self.id,
        #     'search_default_partner_id': self.partner_id.id,
            'default_partner_id': self.partner_id.id,
            'default_campaign_id': self.campaign_id.id,
        #     'default_medium_id': self.medium_id.id,
            'default_origin': self.name,
            'default_source_id': self.source_id.id,
            'default_company_id': self.company_id.id or self.env.company.id,
            'default_tag_ids': [(6, 0, self.tag_ids.ids)]
        }
    #     if self.team_id:
    #         action['context']['default_team_id'] = self.team_id.id,
        if self.user_id:
            action['context']['default_user_id'] = self.user_id.id
        return action

    def _find_matching_partner(self, email_only=False):
        """ Try to find a matching partner with available information on the
        lead, using notably customer's name, email, ...

        :param email_only: Only find a matching based on the email. To use
            for automatic process where ilike based on name can be too dangerous
        :return: partner browse record
        """
        self.ensure_one()
        partner = self.partner_id

        if not partner and self.email_from:
            partner = self.env['res.partner'].search([('email', '=', self.email_from)], limit=1)

        if not partner and not email_only:
            # search through the existing partners based on the lead's partner or contact name
            # to be aligned with _create_customer, search on lead's name as last possibility
            for customer_potential_name in [self[field_name] for field_name in ['partner_name', 'contact_name', 'name'] if self[field_name]]:
                partner = self.env['res.partner'].search([('name', 'ilike', '%' + customer_potential_name + '%')], limit=1)
                if partner:
                    break

        return partner

    def handle_partner_assignment(self, force_partner_id=False, create_missing=True):
        """ Update customer (partner_id) of leads. Purpose is to set the same
        partner on most leads; either through a newly created partner either
        through a given partner_id.

        :param int force_partner_id: if set, update all leads to that customer;
        :param create_missing: for leads without customer, create a new one
          based on lead information;
        """
        for lead in self:
            if force_partner_id:
                lead.partner_id = force_partner_id
            if not lead.partner_id and create_missing:
                partner = lead._create_customer()
                lead.partner_id = partner.id

    def _create_customer(self):
        """ Create a partner from lead data and link it to the lead.

        :return: newly-created partner browse record
        """
        Partner = self.env['res.partner']
        contact_name = self.contact_name
        if not contact_name:
            contact_name = Partner._parse_partner_name(self.email_from)[0] if self.email_from else False

        if self.partner_name:
            partner_company = Partner.create(self._prepare_customer_values(self.partner_name, is_company=True))
        elif self.partner_id:
            partner_company = self.partner_id
        else:
            partner_company = None

        if contact_name:
            return Partner.create(self._prepare_customer_values(contact_name, is_company=False, parent_id=partner_company.id if partner_company else False))

        if partner_company:
            return partner_company
        return Partner.create(self._prepare_customer_values(self.name, is_company=False))

    def _prepare_customer_values(self, partner_name, is_company=False, parent_id=False):
        """ Extract data from lead to create a partner.

        :param name : furtur name of the partner
        :param is_company : True if the partner is a company
        :param parent_id : id of the parent partner (False if no parent)

        :return: dictionary of values to give at res_partner.create()
        """
        email_split = tools.email_split(self.email_from)
        res = {
            'name': partner_name,
            'user_id': self.env.context.get('default_user_id') or self.user_id.id,
            'comment': self.description,
            # 'team_id': self.team_id.id, TODO ver si implementar equipos de compras
            'parent_id': parent_id,
            'phone': self.phone,
            'mobile': self.mobile,
            'email': email_split[0] if email_split else False,
            'title': self.title.id,
            'function': self.function,
            'street': self.street,
            'street2': self.street2,
            'zip': self.zip,
            'city': self.city,
            'country_id': self.country_id.id,
            'state_id': self.state_id.id,
            'website': self.website,
            'is_company': is_company,
            'type': 'contact'
        }
        if self.lang_id:
            res['lang'] = self.lang_id.code
        return res