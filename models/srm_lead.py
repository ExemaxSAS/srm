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
    # Customer / contact
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
        'Phone', tracking=50, inverse='_inverse_phone', readonly=False, store=True)
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