# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from ..utils.auth_decorator import require_auth


class HrAiApiSkillsController(http.Controller):

    @http.route('/api/v1/employees/<int:employee_id>/skills', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['skills:read'])
    def get_skills(self, employee_id, **kwargs):
        payload = request.jwt_payload
        if payload.get('role') == 'employee' and payload.get('employee_id') != employee_id:
            return _error(403, 'forbidden', "Accès non autorisé à ces données.")

        employee = request.env['hr.employee'].sudo().browse(employee_id)
        if not employee.exists():
            return _error(404, 'not_found', "Employé introuvable.")

        skills = [{
            'skill': s.skill_id.name,
            'skill_type': s.skill_type_id.name,
            'level': s.skill_level_id.name,
        } for s in employee.employee_skill_ids]

        return request.make_json_response(skills)

    @http.route('/api/v1/employees/<int:employee_id>/skills-gap', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['skills:read'])
    def get_skills_gap(self, employee_id, **kwargs):
        """Query param optionnel : target_job_id (sinon, poste actuel de
        l'employé)."""
        payload = request.jwt_payload
        if payload.get('role') == 'employee' and payload.get('employee_id') != employee_id:
            return _error(403, 'forbidden', "Accès non autorisé à ces données.")

        employee = request.env['hr.employee'].sudo().browse(employee_id)
        if not employee.exists():
            return _error(404, 'not_found', "Employé introuvable.")

        target_job_id = kwargs.get('target_job_id')
        target_job_id = int(target_job_id) if target_job_id else None

        analysis = employee.get_skill_gap_analysis(target_job_id=target_job_id)
        return request.make_json_response(analysis)

    @http.route(
        '/api/v1/employees/<int:employee_id>/training-recommendations',
        type='http', auth='none', methods=['GET'], csrf=False,
    )
    @require_auth(['skills:read'])
    def get_training_recommendations(self, employee_id, **kwargs):
        payload = request.jwt_payload
        if payload.get('role') == 'employee' and payload.get('employee_id') != employee_id:
            return _error(403, 'forbidden', "Accès non autorisé à ces données.")

        employee = request.env['hr.employee'].sudo().browse(employee_id)
        if not employee.exists():
            return _error(404, 'not_found', "Employé introuvable.")

        target_job_id = kwargs.get('target_job_id')
        target_job_id = int(target_job_id) if target_job_id else None

        analysis = employee.get_skill_gap_analysis(target_job_id=target_job_id)
        return request.make_json_response(analysis['recommended_courses'])

    @http.route('/api/v1/employees/<int:employee_id>/career-path', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['skills:read'])
    def get_career_path(self, employee_id, **kwargs):
        """Query param requis : target_job_id (le poste visé)."""
        payload = request.jwt_payload
        if payload.get('role') == 'employee' and payload.get('employee_id') != employee_id:
            return _error(403, 'forbidden', "Accès non autorisé à ces données.")

        employee = request.env['hr.employee'].sudo().browse(employee_id)
        if not employee.exists():
            return _error(404, 'not_found', "Employé introuvable.")

        target_job_id = kwargs.get('target_job_id')
        if not target_job_id:
            return _error(400, 'invalid_request', "Le paramètre target_job_id est requis (poste visé).")

        path = employee.get_career_path(int(target_job_id))
        return request.make_json_response(path)


def _error(status, code, message):
    return request.make_json_response({'error': code, 'message': message}, status=status)
