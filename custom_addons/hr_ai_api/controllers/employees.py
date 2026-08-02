# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from ..utils.auth_decorator import require_auth


class HrAiApiEmployeesController(http.Controller):

    @http.route('/api/v1/employees/<int:employee_id>', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['profile:read', 'employees:write'])
    def get_employee(self, employee_id, **kwargs):
        """Retourne la fiche d'un employé.

        Un employé « simple » ne peut consulter que sa propre fiche.
        Un manager ou un profil RH peut consulter n'importe quelle fiche
        (le filtrage fin par équipe pourra être affiné plus tard, une fois
        le module Congés en place, en s'appuyant sur parent_id/department_id).
        """
        payload = request.jwt_payload
        employee = request.env['hr.employee'].sudo().browse(employee_id)

        if not employee.exists():
            return request.make_json_response(
                {'error': 'not_found', 'message': "Employé introuvable."}, status=404
            )

        if payload.get('role') == 'employee' and payload.get('employee_id') != employee.id:
            return request.make_json_response(
                {'error': 'forbidden', 'message': "Accès non autorisé à cette fiche employé."},
                status=403,
            )

        return request.make_json_response({
            'id': employee.id,
            'name': employee.name,
            'job_title': employee.job_title,
            'department': employee.department_id.name or None,
            'manager': employee.parent_id.name or None,
            'work_email': employee.work_email,
            'work_phone': employee.work_phone,
            'has_avatar': bool(employee.image_128),
        })
