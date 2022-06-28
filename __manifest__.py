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
        # 'security/ir.model.access.csv',
        'data/srm_stage_data.xml',
        'views/srm_lead.xml',
    ],
    # only loaded in demonstration mode
    'demo': [],
}
