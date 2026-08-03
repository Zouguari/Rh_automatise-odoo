# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from ..utils.auth_decorator import require_auth


class HrAiApiAttendanceController(http.Controller):

    @http.route('/api/v1/attendance/<int:employee_id>', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['attendance:read'])
    def get_attendance(self, employee_id, **kwargs):
        payload = request.jwt_payload
        if payload.get('role') == 'employee' and payload.get('employee_id') != employee_id:
            return _error(403, 'forbidden', "Accès non autorisé à ces données de présence.")

        attendances = request.env['hr.attendance'].sudo().search(
            [('employee_id', '=', employee_id)], order='check_in desc', limit=100,
        )
        return request.make_json_response([_serialize_attendance(a) for a in attendances])

    @http.route('/api/v1/attendance/check-in', type='http', auth='none', methods=['POST'], csrf=False)
    @require_auth(['attendance:write'])
    def check_in(self, **kwargs):
        payload = request.jwt_payload
        employee_id = payload.get('employee_id')
        if not employee_id:
            return _error(400, 'no_employee_linked', "Aucun employé lié à cet utilisateur.")

        open_attendance = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee_id),
            ('check_out', '=', False),
        ], limit=1)
        if open_attendance:
            return _error(
                409, 'already_checked_in',
                "Un pointage d'arrivée est déjà ouvert depuis %s." % open_attendance.check_in,
            )

        try:
            attendance = request.env['hr.attendance'].sudo().create({
                'employee_id': employee_id,
                'check_in': fields.Datetime.now(),
            })
        except (ValidationError, UserError) as exc:
            return _error(400, 'business_rule_violation', str(exc))

        return request.make_json_response(_serialize_attendance(attendance), status=201)

    @http.route('/api/v1/attendance/check-out', type='http', auth='none', methods=['POST'], csrf=False)
    @require_auth(['attendance:write'])
    def check_out(self, **kwargs):
        payload = request.jwt_payload
        employee_id = payload.get('employee_id')
        if not employee_id:
            return _error(400, 'no_employee_linked', "Aucun employé lié à cet utilisateur.")

        open_attendance = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee_id),
            ('check_out', '=', False),
        ], limit=1, order='check_in desc')
        if not open_attendance:
            return _error(404, 'no_open_checkin', "Aucun pointage d'arrivée ouvert à clôturer.")

        try:
            open_attendance.write({'check_out': fields.Datetime.now()})
        except (ValidationError, UserError) as exc:
            return _error(400, 'business_rule_violation', str(exc))

        return request.make_json_response(_serialize_attendance(open_attendance))

    @http.route('/api/v1/attendance/anomalies', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['attendance:team_read'])
    def list_anomalies(self, **kwargs):
        payload = request.jwt_payload
        employee = request.env['hr.employee'].sudo().browse(payload.get('employee_id'))

        domain = [('resolved', '=', False)]
        if payload.get('role') != 'rh' and employee.department_id:
            domain.append(('employee_id.department_id', '=', employee.department_id.id))

        anomalies = request.env['hr.attendance.anomaly'].sudo().search(
            domain, order='detected_on desc', limit=100,
        )
        return request.make_json_response([{
            'id': a.id,
            'employee': a.employee_id.name,
            'employee_id': a.employee_id.id,
            'anomaly_type': a.anomaly_type,
            'detected_on': a.detected_on.isoformat() if a.detected_on else None,
            'notes': a.notes,
        } for a in anomalies])

    @http.route('/api/v1/attendance/<int:employee_id>/habits', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['attendance:read'])
    def get_habits(self, employee_id, **kwargs):
        """Synthèse simple (MVP) des habitudes de présence sur 30 jours :
        proportion de retards et retard moyen en minutes."""
        payload = request.jwt_payload
        if payload.get('role') == 'employee' and payload.get('employee_id') != employee_id:
            return _error(403, 'forbidden', "Accès non autorisé à ces données de présence.")

        since = fields.Datetime.now() - timedelta(days=30)
        attendances = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee_id),
            ('check_in', '>=', since),
        ])

        total = len(attendances)
        late_attendances = attendances.filtered('is_late')
        late_count = len(late_attendances)
        avg_late_minutes = (
            sum(late_attendances.mapped('late_minutes')) / late_count if late_count else 0.0
        )

        return request.make_json_response({
            'employee_id': employee_id,
            'period_days': 30,
            'total_attendances': total,
            'late_count': late_count,
            'late_ratio': round(late_count / total, 2) if total else 0.0,
            'average_late_minutes': round(avg_late_minutes, 1),
        })


def _serialize_attendance(attendance):
    return {
        'id': attendance.id,
        'employee_id': attendance.employee_id.id,
        'employee': attendance.employee_id.name,
        'check_in': attendance.check_in.isoformat() if attendance.check_in else None,
        'check_out': attendance.check_out.isoformat() if attendance.check_out else None,
        'worked_hours': attendance.worked_hours,
        'is_late': attendance.is_late,
        'late_minutes': round(attendance.late_minutes, 1),
        'anomaly_type': attendance.anomaly_type,
    }


def _error(status, code, message):
    return request.make_json_response({'error': code, 'message': message}, status=status)
