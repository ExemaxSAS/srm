# -*- coding: utf-8 -*-
# from odoo import http


# class Srm(http.Controller):
#     @http.route('/srm/srm/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/srm/srm/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('srm.listing', {
#             'root': '/srm/srm',
#             'objects': http.request.env['srm.srm'].search([]),
#         })

#     @http.route('/srm/srm/objects/<model("srm.srm"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('srm.object', {
#             'object': obj
#         })
