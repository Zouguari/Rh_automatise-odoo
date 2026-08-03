# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models


class HrAttendanceAnomaly(models.Model):
    _name = 'hr.attendance.anomaly'
    _description = "Anomalie de présence détectée"
    _order = 'create_date desc'

    employee_id = fields.Many2one(
        'hr.employee', string="Employé", required=True, index=True, ondelete='cascade',
    )
    attendance_id = fields.Many2one('hr.attendance', string="Pointage concerné", ondelete='cascade')
    anomaly_type = fields.Selection(
        [
            ('missing_checkout', "Pointage de sortie manquant"),
            ('repeated_lateness', "Retards répétés"),
        ],
        required=True,
    )
    detected_on = fields.Datetime(string="Détectée le", default=fields.Datetime.now)
    notes = fields.Text()
    resolved = fields.Boolean(string="Résolue", default=False)

    @api.model
    def _cron_detect_attendance_anomalies(self):
        """Point d'entrée du cron quotidien (voir data/ir_cron_data.xml)."""
        self._detect_missing_checkouts()
        self._detect_repeated_lateness()

    @api.model
    def _detect_missing_checkouts(self):
        today = fields.Date.context_today(self)
        open_attendances = self.env['hr.attendance'].sudo().search([('check_out', '=', False)])

        for att in open_attendances:
            if not att.check_in or att.check_in.date() >= today:
                continue  # journée en cours, pas encore une anomalie

            already_logged = self.sudo().search_count([
                ('attendance_id', '=', att.id),
                ('anomaly_type', '=', 'missing_checkout'),
            ])
            if already_logged:
                continue

            self.sudo().create({
                'employee_id': att.employee_id.id,
                'attendance_id': att.id,
                'anomaly_type': 'missing_checkout',
                'notes': "Pointage d'arrivée du %s sans pointage de sortie associé." % att.check_in,
            })

    @api.model
    def _detect_repeated_lateness(self):
        threshold = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'hr_attendance_ai.repeated_lateness_threshold', default=3
            )
        )
        since = fields.Datetime.now() - timedelta(days=7)
        late_attendances = self.env['hr.attendance'].sudo().search([
            ('is_late', '=', True),
            ('check_in', '>=', since),
        ])

        by_employee = {}
        for att in late_attendances:
            by_employee.setdefault(att.employee_id, self.env['hr.attendance'].sudo())
            by_employee[att.employee_id] |= att

        today_start = fields.Datetime.to_string(fields.Date.context_today(self))
        for employee, attendances in by_employee.items():
            if len(attendances) < threshold:
                continue

            already_logged_today = self.sudo().search_count([
                ('employee_id', '=', employee.id),
                ('anomaly_type', '=', 'repeated_lateness'),
                ('detected_on', '>=', today_start),
            ])
            if already_logged_today:
                continue

            self.sudo().create({
                'employee_id': employee.id,
                'anomaly_type': 'repeated_lateness',
                'notes': "%d retard(s) détecté(s) sur les 7 derniers jours." % len(attendances),
            })
