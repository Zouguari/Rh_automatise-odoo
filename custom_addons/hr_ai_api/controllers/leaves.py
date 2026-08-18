# -*- coding: utf-8 -*-
import json
import logging

from odoo import http, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from ..utils.auth_decorator import require_auth

_logger = logging.getLogger(__name__)


class HrAiApiLeavesController(http.Controller):

    @http.route('/api/v1/leaves', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['leaves:read'])
    def list_leaves(self, **kwargs):
        payload = request.jwt_payload
        Leave = request.env['hr.leave'].sudo()

        if payload.get('role') == 'employee':
            domain = [('employee_id', '=', payload.get('employee_id'))]
        else:
            employee = request.env['hr.employee'].sudo().browse(payload.get('employee_id'))
            domain = [
                '|',
                ('employee_id', '=', employee.id),
                ('department_id', '=', employee.department_id.id),
            ]

        leaves = Leave.search(domain, order='date_from desc', limit=100)
        return request.make_json_response([_serialize_leave(l) for l in leaves])

    @http.route('/api/v1/leaves', type='http', auth='none', methods=['POST'], csrf=False)
    @require_auth(['leaves:write'])
    def create_leave(self, **kwargs):
        payload = request.jwt_payload
        data = _get_json_body()
        if data is None:
            return _error(400, 'invalid_request', "Corps de requête JSON invalide.")

        required_fields = ('holiday_status_id', 'date_from', 'date_to')
        if not all(data.get(f) for f in required_fields):
            return _error(
                400, 'invalid_request',
                "Champs requis : holiday_status_id, date_from, date_to.",
            )

        employee_id = payload.get('employee_id')
        if not employee_id:
            return _error(400, 'no_employee_linked', "Aucun profil employé associé à ce compte.")

        try:
            # Execute with SUPERUSER_ID to ensure mail thread / env.user is valid
            leave = request.env['hr.leave'].with_user(SUPERUSER_ID).create({
                'employee_id': employee_id,
                'holiday_status_id': int(data['holiday_status_id']),
                'request_date_from': data['date_from'],
                'request_date_to': data['date_to'],
                'name': data.get('reason', ''),
            })
        except (ValidationError, UserError) as exc:
            msg = str(exc)
            if 'overlaps' in msg.lower() or 'chevauche' in msg.lower():
                msg = "Une demande de congé existe déjà sur cette période (chevauchement de dates)."
            elif 'allocation' in msg.lower() or 'solde' in msg.lower():
                msg = "Solde de congés insuffisant pour ce type d'absence."
            return _error(400, 'business_rule_violation', msg)
        except Exception as exc:
            _logger.exception("Erreur lors de la création de la demande de congé: %s", str(exc))
            return _error(500, 'server_error', "Erreur lors de la création de la demande.")

        return request.make_json_response(_serialize_leave(leave, detailed=True), status=201)

    @http.route('/api/v1/leaves/<int:leave_id>', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['leaves:read'])
    def get_leave(self, leave_id, **kwargs):
        payload = request.jwt_payload
        leave = request.env['hr.leave'].sudo().browse(leave_id)

        if not leave.exists():
            return _error(404, 'not_found', "Demande introuvable.")

        if payload.get('role') == 'employee' and leave.employee_id.id != payload.get('employee_id'):
            return _error(403, 'forbidden', "Accès non autorisé à cette demande.")

        return request.make_json_response(_serialize_leave(leave, detailed=True))


def _serialize_leave(leave, detailed=False):
    data = {
        'id': leave.id,
        'employee': leave.employee_id.name,
        'employee_id': leave.employee_id.id,
        'holiday_status': leave.holiday_status_id.name,
        'date_from': leave.date_from.isoformat() if leave.date_from else None,
        'date_to': leave.date_to.isoformat() if leave.date_to else None,
        'number_of_days': leave.number_of_days,
        'state': leave.state,
    }
    if detailed:
        data.update({
            'ai_recommendation': leave.ai_recommendation if hasattr(leave, 'ai_recommendation') else None,
            'ai_justification': leave.ai_justification if hasattr(leave, 'ai_justification') else None,
        })
    return data


def _get_json_body():
    raw = request.httprequest.get_data()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None


def _error(status, code, message):
    return request.make_json_response({'error': code, 'message': message}, status=status)
