# -*- coding: utf-8 -*-
{
    'name': "SRM",

    'summary': """
        Supplier Relationship Management. Like CRM but for Supplier.""",

    'description': """
        SRM - Supplier Relationship Management. Like CRM but for Supplier.
    """,

    'author': "Exemax",
    'website': "https://www.exemax.com.ar",

    'category': 'Purchase',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'purchase', 'mail', 'utm'],

    # always loaded
    'data': [
        'data/srm_stage_data.xml',
        'views/srm_lead.xml',
        'views/srm_stage.xml',
        'views/srm_tag.xml',
        'security/ir.model.access.csv',
        'views/purchase_srm.xml',
        'views/srm_quotation_partner.xml',
    ],
    # only loaded in demonstration mode
    'demo': [],
}
