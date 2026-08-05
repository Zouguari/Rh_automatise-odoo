# -*- coding: utf-8 -*-
import json

from odoo import http
from odoo.http import request

from ..utils.auth_decorator import require_auth


class HrAiApiAppraisalsController(http.Controller):

    @http.route('/api/v1/appraisals/<int:employee_id>', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['appraisals:read'])
    def list_appraisals(self, employee_id, **kwargs):
        payload = request.jwt_payload
        if payload.get('role') == 'employee' and payload.get('employee_id') != employee_id:
            return _error(403, 'forbidden', "Accès non autorisé aux évaluations de cet employé.")

        appraisals = request.env['hr.appraisal'].sudo().search(
            [('employee_id', '=', employee_id)], order='create_date desc', limit=50,
        )
        return request.make_json_response([_serialize_appraisal(a) for a in appraisals])

    @http.route('/api/v1/appraisals/generate', type='http', auth='none', methods=['POST'], csrf=False)
    @require_auth(['appraisals:write'])
    def generate_appraisal(self, **kwargs):
        """Body JSON attendu : {"employee_id": int} (optionnel — l'employé
        connecté par défaut). Crée une évaluation si aucune n'est en cours
        pour cet employé, puis calcule l'analyse IA dessus."""
        payload = request.jwt_payload
        data = _get_json_body()
        if data is None:
            return _error(400, 'invalid_request', "Corps de requête JSON invalide.")

        employee_id = data.get('employee_id') or payload.get('employee_id')
        if not employee_id:
            return _error(400, 'no_employee_linked', "Aucun employé lié à cet utilisateur, et aucun employee_id fourni.")

        if payload.get('role') == 'employee' and payload.get('employee_id') != employee_id:
            return _error(403, 'forbidden', "Accès non autorisé à générer une évaluation pour cet employé.")

        employee = request.env['hr.employee'].sudo().browse(employee_id)
        if not employee.exists():
            return _error(404, 'not_found', "Employé introuvable.")

        appraisal = request.env['hr.appraisal'].sudo().create({
            'employee_id': employee.id,
            'manager_id': employee.parent_id.id if employee.parent_id else False,
        })
        appraisal.action_generate_ai_appraisal()

        return request.make_json_response(_serialize_appraisal(appraisal, detailed=True), status=201)

    @http.route('/api/v1/appraisals/<int:appraisal_id>/analysis', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['appraisals:read'])
    def get_analysis(self, appraisal_id, **kwargs):
        payload = request.jwt_payload
        appraisal = request.env['hr.appraisal'].sudo().browse(appraisal_id)
        if not appraisal.exists():
            return _error(404, 'not_found', "Évaluation introuvable.")

        if payload.get('role') == 'employee' and payload.get('employee_id') != appraisal.employee_id.id:
            return _error(403, 'forbidden', "Accès non autorisé à cette évaluation.")

        if not appraisal.ai_computed_on:
            appraisal.action_generate_ai_appraisal()

        return request.make_json_response(_serialize_appraisal(appraisal, detailed=True))

    @http.route('/api/v1/appraisals/high-potentials', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['analytics:read'])
    def high_potentials(self, **kwargs):
        payload = request.jwt_payload
        employee = request.env['hr.employee'].sudo().browse(payload.get('employee_id'))

        domain = [('ai_high_potential', '=', True)]
        if payload.get('role') != 'rh' and employee.department_id:
            domain.append(('employee_id.department_id', '=', employee.department_id.id))

        appraisals = request.env['hr.appraisal'].sudo().search(domain, order='ai_performance_score desc')
        return request.make_json_response([_serialize_appraisal(a) for a in appraisals])


def _serialize_appraisal(appraisal, detailed=False):
    data = {
        'id': appraisal.id,
        'employee_id': appraisal.employee_id.id,
        'employee': appraisal.employee_id.name,
        'state': appraisal.state,
        'ai_performance_score': appraisal.ai_performance_score,
        'ai_high_potential': appraisal.ai_high_potential,
    }
    if detailed:
        data.update({
            'ai_summary': appraisal.ai_summary,
            'ai_computed_on': appraisal.ai_computed_on.isoformat() if appraisal.ai_computed_on else None,
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
