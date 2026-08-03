# -*- coding: utf-8 -*-
import pytz

from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    is_late = fields.Boolean(string="En retard", compute='_compute_ai_lateness', store=True)
    late_minutes = fields.Float(string="Minutes de retard", compute='_compute_ai_lateness', store=True)
    anomaly_type = fields.Selection(
        [
            ('none', "Aucune"),
            ('late', "Retard"),
            ('missing_checkout', "Pointage de sortie manquant"),
        ],
        string="Anomalie", compute='_compute_ai_lateness', store=True,
    )

    @api.depends('check_in', 'check_out', 'employee_id')
    def _compute_ai_lateness(self):
        grace_minutes = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'hr_attendance_ai.grace_minutes', default=10
            )
        )
        today = fields.Date.context_today(self)

        for att in self:
            att.is_late = False
            att.late_minutes = 0.0
            att.anomaly_type = 'none'

            if not att.check_in:
                continue

            expected_hour = att._ai_get_expected_start_hour()
            if expected_hour is not None:
                local_hour, _weekday = att._ai_get_local_checkin_hour()
                delta_minutes = (local_hour - expected_hour) * 60
                if delta_minutes > grace_minutes:
                    att.is_late = True
                    att.late_minutes = delta_minutes
                    att.anomaly_type = 'late'

            if not att.check_out and att.check_in.date() < today:
                att.anomaly_type = 'missing_checkout'

    def _ai_get_local_checkin_hour(self):
        """Convertit check_in (stocké en UTC) vers l'heure locale de
        l'employé, et renvoie (heure décimale, jour de semaine 0=lundi)."""
        self.ensure_one()
        tz_name = self.employee_id.tz or self.env.user.tz or 'UTC'
        tz = pytz.timezone(tz_name)
        local_dt = pytz.utc.localize(self.check_in).astimezone(tz)
        return local_dt.hour + local_dt.minute / 60.0, local_dt.weekday()

    def _ai_get_expected_start_hour(self):
        """Heure d'arrivée attendue (float, ex: 9.0 pour 9h00) selon le
        calendrier de travail de l'employé et le jour de la semaine du
        pointage. None si aucun calendrier n'est configuré pour ce jour.

        NOTE : simplification MVP — ne gère pas les demi-journées ni les
        plannings avec plusieurs plages le même jour ; prend la plage la
        plus matinale du jour concerné."""
        self.ensure_one()
        calendar = self.employee_id.resource_calendar_id
        if not calendar or not self.check_in:
            return None

        _local_hour, weekday = self._ai_get_local_checkin_hour()
        lines = calendar.attendance_ids.filtered(lambda l: l.dayofweek == str(weekday))
        if not lines:
            return None
        return min(lines.mapped('hour_from'))
