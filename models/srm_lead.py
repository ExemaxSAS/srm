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
        'Opportunity', index=True, required=True, readonly=False, store=True)
    user_id = fields.Many2one('res.users', string='Salesperson', index=True, tracking=True, default=lambda self: self.env.user)
    user_email = fields.Char('User Email', related='user_id.email', readonly=True)
    user_login = fields.Char('User Login', related='user_id.login', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', index=True, default=lambda self: self.env.company.id)
    referred = fields.Char('Referred By')
    description = fields.Text('Notes')
    active = fields.Boolean('Active', default=True, tracking=True)
    type = fields.Selection([
        ('lead', 'Lead'), ('opportunity', 'Opportunity')],
        index=True, required=True, tracking=15,
        default='opportunity')
    priority = fields.Selection(
        srm_stage.AVAILABLE_PRIORITIES, string='Priority', index=True,
        default=srm_stage.AVAILABLE_PRIORITIES[0][0])
    #team_id = fields.Many2one(
    #    'crm.team', string='Sales Team', index=True, tracking=True,
    #    compute='_compute_team_id', readonly=False, store=True)
    stage_id = fields.Many2one(
        'srm.stage', string='Stage', index=True, tracking=True, readonly=False, store=True,
        copy=False, ondelete='restrict')
    kanban_state = fields.Selection([
        ('grey', 'No next activity planned'),
        ('red', 'Next activity late'),
        ('green', 'Next activity is planned')], string='Kanban State')
    activity_date_deadline_my = fields.Date(
        'My Activities Deadline', compute='_compute_activity_date_deadline_my',
        search='_search_activity_date_deadline_my', compute_sudo=False,
        readonly=True, store=False, groups="base.group_user")
    #tag_ids = fields.Many2many(
    #    'crm.tag', 'crm_tag_rel', 'lead_id', 'tag_id', string='Tags',
    #    help="Classify and analyze your lead/opportunity categories like: Training, Service")
    color = fields.Integer('Color Index', default=0)
    # Opportunity specific
    expected_revenue = fields.Monetary('Expected Revenue', currency_field='company_currency', tracking=True)
    prorated_revenue = fields.Monetary('Prorated Revenue', currency_field='company_currency', store=True)
    recurring_revenue = fields.Monetary('Recurring Revenues', currency_field='company_currency')
    #recurring_plan = fields.Many2one('crm.recurring.plan', string="Recurring Plan")
    #recurring_revenue_monthly = fields.Monetary('Expected MRR', currency_field='company_currency', store=True,
    #                                           compute="_compute_recurring_revenue_monthly")
    #recurring_revenue_monthly_prorated = fields.Monetary('Prorated MRR', currency_field='company_currency', store=True,
    #                                           compute="_compute_recurring_revenue_monthly_prorated")
    company_currency = fields.Many2one("res.currency", string='Currency', related='company_id.currency_id', readonly=True)
    # Dates
    date_closed = fields.Datetime('Closed Date', readonly=True, copy=False)
    date_action_last = fields.Datetime('Last Action', readonly=True)
    date_open = fields.Datetime(
        'Assignment Date', readonly=True, store=True)
    day_open = fields.Float('Days to Assign', store=True)
    day_close = fields.Float('Days to Close', store=True)
    date_last_stage_update = fields.Datetime(
        'Last Stage Update', index=True, readonly=True, store=True)
    date_conversion = fields.Datetime('Conversion Date', readonly=True)
    date_deadline = fields.Date('Expected Closing', help="Estimate of the date on which the opportunity will be won.")
    # Supplier / contact
    partner_id = fields.Many2one(
        'res.partner', string='Customer', index=True, tracking=10,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="Linked partner (optional). Usually created when converting the lead. You can find a partner by its Name, TIN, Email or Internal Reference.")
    partner_is_blacklisted = fields.Boolean('Partner is blacklisted', related='partner_id.is_blacklisted', readonly=True)
    contact_name = fields.Char(
        'Contact Name', tracking=30, readonly=False, store=True)
    partner_name = fields.Char(
        'Company Name', tracking=20, index=True, readonly=False, store=True,
        help='The name of the future partner company that will be created while converting the lead into opportunity')
    function = fields.Char('Job Position', readonly=False, store=True)
    title = fields.Many2one('res.partner.title', string='Title', readonly=False, store=True)
    email_from = fields.Char(
        'Email', tracking=40, index=True, inverse='_inverse_email_from', readonly=False, store=True)
    phone = fields.Char(
        'Phone', tracking=50,
        compute='_compute_phone', inverse='_inverse_phone', readonly=False, store=True)
    mobile = fields.Char('Mobile', readonly=False, store=True)
    phone_mobile_search = fields.Char('Phone/Mobile', store=False, search='_search_phone_mobile_search')
    phone_state = fields.Selection([
        ('correct', 'Correct'),
        ('incorrect', 'Incorrect')], string='Phone Quality', store=True)
    email_state = fields.Selection([
        ('correct', 'Correct'),
        ('incorrect', 'Incorrect')], string='Email Quality', store=True)
    website = fields.Char('Website', index=True, help="Website of the contact", readonly=False, store=True)
    lang_id = fields.Many2one('res.lang', string='Language')
    # Address fields
    street = fields.Char('Street', readonly=False, store=True)
    street2 = fields.Char('Street2', readonly=False, store=True)
    zip = fields.Char('Zip', change_default=True, readonly=False, store=True)
    city = fields.Char('City', readonly=False, store=True)
    state_id = fields.Many2one(
        "res.country.state", string='State', readonly=False, store=True,
        domain="[('country_id', '=?', country_id)]")
    country_id = fields.Many2one(
        'res.country', string='Country', readonly=False, store=True)
    # Probability (Opportunity only)
    probability = fields.Float(
        'Probability', group_operator="avg", copy=False, readonly=False, store=True)
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
