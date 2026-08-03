# -*- coding: utf-8 -*-
import json

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from ..utils.auth_decorator import require_auth


class HrAiApiLeavesController(http.Controller):

    @http.route('/api/v1/leaves', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['leaves:read'])
    def list_leaves(self, **kwargs):
        """Un employé voit ses propres congés. Un manager/RH voit aussi
        ceux de son département."""
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
        """Body JSON attendu : {"holiday_status_id": int, "date_from": "...",
        "date_to": "...", "reason": "..."}. La recommandation IA est calculée
        automatiquement à la création (voir hr_leaves_ai)."""
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
            return _error(400, 'no_employee_linked', "Aucun employé lié à cet utilisateur.")

        try:
            leave = request.env['hr.leave'].sudo().create({
                'employee_id': employee_id,
                'holiday_status_id': data['holiday_status_id'],
                'date_from': data['date_from'],
                'date_to': data['date_to'],
                'name': data.get('reason', ''),
            })
        except (ValidationError, UserError) as exc:
            # Ex : chevauchement avec un congé existant, solde insuffisant
            # selon le type de congé, etc. — règles métier natives d'Odoo.
            return _error(400, 'business_rule_violation', str(exc))

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

    @http.route('/api/v1/leaves/<int:leave_id>/approve', type='http', auth='none', methods=['POST'], csrf=False)
    @require_auth(['leaves:approve'])
    def approve_leave(self, leave_id, **kwargs):
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave.exists():
            return _error(404, 'not_found', "Demande introuvable.")

        # NOTE : si la double validation RH est activée (Réglages > Congés),
        # il peut falloir enchaîner avec leave.action_validate() après
        # action_approve() — à vérifier sur votre configuration, comme pour
        # authenticate() précédemment. En simple validation, action_approve()
        # suffit.
        try:
            leave.action_approve()
        except (ValidationError, UserError) as exc:
            return _error(400, 'business_rule_violation', str(exc))
        return request.make_json_response(_serialize_leave(leave, detailed=True))

    @http.route('/api/v1/leaves/<int:leave_id>/refuse', type='http', auth='none', methods=['POST'], csrf=False)
    @require_auth(['leaves:approve'])
    def refuse_leave(self, leave_id, **kwargs):
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave.exists():
            return _error(404, 'not_found', "Demande introuvable.")

        try:
            leave.action_refuse()
        except (ValidationError, UserError) as exc:
            return _error(400, 'business_rule_violation', str(exc))
        return request.make_json_response(_serialize_leave(leave, detailed=True))

    @http.route('/api/v1/leaves/team-conflicts', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['leaves:approve', 'attendance:team_read'])
    def team_conflicts(self, **kwargs):
        """Liste les demandes de congés du département qui se chevauchent
        avec au moins une autre — vue manager/RH."""
        payload = request.jwt_payload
        employee = request.env['hr.employee'].sudo().browse(payload.get('employee_id'))
        department = employee.department_id
        if not department:
            return request.make_json_response([])

        leaves = request.env['hr.leave'].sudo().search([
            ('department_id', '=', department.id),
            ('state', 'in', ('confirm', 'validate1', 'validate')),
        ], order='date_from')

        conflicts = []
        for leave in leaves:
            overlapping = leaves.filtered(
                lambda l: l.id != leave.id
                and l.date_from <= leave.date_to
                and l.date_to >= leave.date_from
            )
            if overlapping:
                conflicts.append({
                    'leave_id': leave.id,
                    'employee': leave.employee_id.name,
                    'date_from': leave.date_from.isoformat() if leave.date_from else None,
                    'date_to': leave.date_to.isoformat() if leave.date_to else None,
                    'overlapping_with': [l.employee_id.name for l in overlapping],
                })
        return request.make_json_response(conflicts)

    @http.route('/api/v1/leaves/forecast', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['analytics:read'])
    def leaves_forecast(self, **kwargs):
        """Prévision simple (MVP) : nombre de jours de congés validés par
        mois, sur le département de l'utilisateur (ou tous les départements
        pour un profil RH). À enrichir plus tard avec un vrai modèle de
        prévision (saisonnalité, jours fériés, etc.)."""
        payload = request.jwt_payload
        employee = request.env['hr.employee'].sudo().browse(payload.get('employee_id'))

        domain = [('state', '=', 'validate')]
        if payload.get('role') != 'rh' and employee.department_id:
            domain.append(('department_id', '=', employee.department_id.id))

        leaves = request.env['hr.leave'].sudo().search(domain)
        monthly = {}
        for leave in leaves:
            if not leave.date_from:
                continue
            key = leave.date_from.strftime('%Y-%m')
            monthly[key] = monthly.get(key, 0) + (leave.number_of_days or 0)

        return request.make_json_response(
            [{'month': k, 'days': v} for k, v in sorted(monthly.items())]
        )


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
            'ai_recommendation': leave.ai_recommendation,
            'ai_justification': leave.ai_justification,
            'ai_conflict_count': leave.ai_conflict_count,
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