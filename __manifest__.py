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

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/14.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Purchase',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'purchase'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/views.xml',
        'views/templates.xml',
    ],
    # only loaded in demonstration mode
    'demo': [],
}