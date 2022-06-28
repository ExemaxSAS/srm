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
    'depends': ['base', 'purchase', 'mail', 'utm', 'phone', 'format'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/views.xml',
        'views/templates.xml',
    ],
    # only loaded in demonstration mode
    'demo': [],
}
