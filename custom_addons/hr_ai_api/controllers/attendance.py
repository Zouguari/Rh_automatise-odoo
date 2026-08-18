# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, date, timedelta
import calendar

from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from ..utils.auth_decorator import require_auth

_logger = logging.getLogger(__name__)


class HrAiApiAttendanceController(http.Controller):

    @http.route('/api/v1/attendance/<int:employee_id>', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['attendance:read'])
    def get_attendance(self, employee_id, **kwargs):
        payload = request.jwt_payload
        if payload.get('role') == 'employee' and payload.get('employee_id') != employee_id:
            return _error(403, 'forbidden', "Accès non autorisé à ces données de présence.")

        # Query params: month (1-12) & year (YYYY)
        try:
            month = int(kwargs.get('month', datetime.now().month))
            year = int(kwargs.get('year', datetime.now().year))
        except (ValueError, TypeError):
            month = datetime.now().month
            year = datetime.now().year

        # Start and end of the requested month
        _, last_day = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        # 1. Fetch raw attendances from Odoo
        attendances = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee_id),
            ('check_in', '>=', start_dt),
            ('check_in', '<=', end_dt),
        ], order='check_in asc')

        # 2. Fetch leaves for this month
        leaves = request.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
            ('date_from', '<=', end_dt),
            ('date_to', '>=', start_dt),
        ])

        # 3. Fetch user reported / detected anomalies for this employee
        anomalies = request.env['hr.attendance.anomaly'].sudo().search([
            ('employee_id', '=', employee_id),
        ], order='create_date desc', limit=50)

        # 4. Compute monthly statistics
        present_dates = set()
        late_days = 0
        total_worked_hours = 0.0

        for att in attendances:
            if att.check_in:
                dt_local = fields.Datetime.context_timestamp(request.env['hr.attendance'], att.check_in)
                present_dates.add(dt_local.date())
            if att.is_late:
                late_days += 1
            if att.worked_hours:
                total_worked_hours += att.worked_hours

        # Compute leave dates
        leave_dates = set()
        for l in leaves:
            if l.date_from and l.date_to:
                cur = l.date_from.date()
                end_l = l.date_to.date()
                while cur <= end_l:
                    if cur.month == month and cur.year == year:
                        leave_dates.add(cur)
                    cur += timedelta(days=1)

        # Compute working days (Mon-Fri) up to today
        today = date.today()
        absent_days = 0
        cur_d = start_date
        max_d = min(end_date, today)

        while cur_d <= max_d:
            if cur_d.weekday() < 5:  # Mon-Fri
                if cur_d not in present_dates and cur_d not in leave_dates:
                    absent_days += 1
            cur_d += timedelta(days=1)

        serialized_attendances = [_serialize_attendance(a) for a in attendances]
        serialized_leaves = [{
            'id': l.id,
            'leave_type': l.holiday_status_id.name,
            'date_from': l.date_from.isoformat() if l.date_from else None,
            'date_to': l.date_to.isoformat() if l.date_to else None,
            'number_of_days': l.number_of_days,
        } for l in leaves]

        serialized_anomalies = [_serialize_anomaly(a) for a in anomalies]

        return request.make_json_response({
            'employee_id': employee_id,
            'month': month,
            'year': year,
            'stats': {
                'present_days': len(present_dates),
                'late_days': late_days,
                'absent_days': absent_days,
                'leave_days': len(leave_dates),
                'total_worked_hours': round(total_worked_hours, 1),
            },
            'attendances': serialized_attendances,
            'leaves': serialized_leaves,
            'anomalies': serialized_anomalies,
        })

    @http.route('/api/v1/attendance/anomaly', type='http', auth='none', methods=['POST'], csrf=False)
    @require_auth(['attendance:read'])
    def submit_anomaly(self, **kwargs):
        """Soumission d'une réclamation / anomalie de présence par l'employé."""
        payload = request.jwt_payload
        employee_id = payload.get('employee_id')
        if not employee_id:
            return _error(400, 'no_employee_linked', "Aucun employé lié à cet utilisateur.")

        raw_body = request.httprequest.get_data()
        try:
            data = json.loads(raw_body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return _error(400, 'invalid_json', "Corps JSON invalide.")

        date_concerned_str = data.get('date')
        comment = data.get('comment', '').strip()
        attendance_id = data.get('attendance_id')
        attachment_base64 = data.get('attachment_base64')
        attachment_name = data.get('attachment_name')

        if not date_concerned_str or not comment:
            return _error(400, 'missing_fields', "La date et le commentaire sont obligatoires.")

        try:
            date_concerned = fields.Date.from_string(date_concerned_str)
        except Exception:
            return _error(400, 'invalid_date', "Format de date invalide (AAAA-MM-JJ attendu).")

        # Create anomaly record in hr.attendance.anomaly
        anomaly = request.env['hr.attendance.anomaly'].sudo().create({
            'employee_id': employee_id,
            'attendance_id': attendance_id or False,
            'anomaly_type': 'user_reported',
            'status': 'pending',
            'date_concerned': date_concerned,
            'comment': comment,
            'notes': "Réclamation formulée par l'employé : %s" % comment,
            'attachment_base64': attachment_base64 or False,
            'attachment_name': attachment_name or False,
            'detected_on': fields.Datetime.now(),
        })

        # Optionally log activity for HR
        employee = request.env['hr.employee'].sudo().browse(employee_id)
        if employee.user_id:
            try:
                request.env['mail.activity'].sudo().create({
                    'res_model_id': request.env['ir.model'].sudo().search([('model', '=', 'hr.attendance.anomaly')], limit=1).id,
                    'res_id': anomaly.id,
                    'activity_type_id': 1,
                    'summary': "Nouvelle réclamation de présence",
                    'note': "L'employé %s a signalé une erreur de présence pour le %s." % (employee.name, date_concerned_str),
                    'user_id': request.env.ref('base.user_admin').id,
                })
            except Exception as e:
                _logger.warning("Échec de création d'activité mail: %s", str(e))

        return request.make_json_response(_serialize_anomaly(anomaly), status=201)

    @http.route('/api/v1/attendance/anomalies/my', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['attendance:read'])
    def get_my_anomalies(self, **kwargs):
        """Liste des réclamations / anomalies de l'employé connecté."""
        payload = request.jwt_payload
        employee_id = payload.get('employee_id')
        if not employee_id:
            return _error(400, 'no_employee_linked', "Aucun employé lié.")

        anomalies = request.env['hr.attendance.anomaly'].sudo().search([
            ('employee_id', '=', employee_id),
        ], order='create_date desc', limit=100)

        return request.make_json_response([_serialize_anomaly(a) for a in anomalies])


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


def _serialize_anomaly(anomaly):
    return {
        'id': anomaly.id,
        'employee_id': anomaly.employee_id.id,
        'employee': anomaly.employee_id.name,
        'anomaly_type': anomaly.anomaly_type,
        'status': anomaly.status or 'pending',
        'date_concerned': anomaly.date_concerned.isoformat() if anomaly.date_concerned else None,
        'comment': anomaly.comment or anomaly.notes or '',
        'rh_comment': anomaly.rh_comment or '',
        'attachment_name': anomaly.attachment_name or None,
        'detected_on': anomaly.detected_on.isoformat() if anomaly.detected_on else None,
        'resolved': anomaly.resolved,
    }


def _error(status, code, message):
    return request.make_json_response({'error': code, 'message': message}, status=status)
