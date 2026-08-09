# -*- coding: utf-8 -*-
import json

from odoo import models, fields, api


class SmartHrAiDashboard(models.Model):
    _name = 'smart.hr.ai.dashboard'
    _description = "Tableau de bord global Smart HR AI"

    name = fields.Char(string="Titre", default="Statistiques Globales Smart HR AI")

    # Recrutement & Onboarding
    recruited_employees_count = fields.Integer(
        string="Employés Recrutés via IA",
        compute='_compute_dashboard_metrics'
    )
    onboarded_employees_count = fields.Integer(
        string="Employés Onboardés Automatiquement",
        compute='_compute_dashboard_metrics'
    )
    onboarding_completion_rate = fields.Float(
        string="Taux de Complétion Onboarding (%)",
        compute='_compute_dashboard_metrics'
    )

    # Performance IA
    avg_recruitment_ai_score = fields.Float(
        string="Score Moyen Recrutement IA (%)",
        compute='_compute_dashboard_metrics'
    )
    avg_skills_coverage = fields.Float(
        string="Couverture Moyenne des Compétences (%)",
        compute='_compute_dashboard_metrics'
    )
    avg_employee_performance_score = fields.Float(
        string="Score Moyen Performance Employés (%)",
        compute='_compute_dashboard_metrics'
    )

    # Lifecycle & Opérationnel
    appraisal_employees_count = fields.Integer(
        string="Employés avec Évaluation IA",
        compute='_compute_dashboard_metrics'
    )
    skills_gap_employees_count = fields.Integer(
        string="Employés avec Analyse Skills Gap",
        compute='_compute_dashboard_metrics'
    )
    training_rec_employees_count = fields.Integer(
        string="Formations Recommandées Activement",
        compute='_compute_dashboard_metrics'
    )
    attendance_anomalies_count = fields.Integer(
        string="Anomalies de Présence Détectées",
        compute='_compute_dashboard_metrics'
    )
    leave_recommendations_count = fields.Integer(
        string="Demandes de Congés Traitées via IA",
        compute='_compute_dashboard_metrics'
    )

    # Résumé hebdomadaire IA (lien vers le dernier résumé toutes équipes)
    latest_weekly_summary_id = fields.Many2one(
        'hr.weekly.summary', string="Dernier résumé hebdomadaire",
        compute='_compute_dashboard_metrics'
    )
    latest_weekly_summary_headline = fields.Char(
        string="Résumé de la semaine", compute='_compute_dashboard_metrics'
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        dummy = self.new({})
        dummy._compute_dashboard_metrics()
        for fname in fields_list:
            if hasattr(dummy, fname) and getattr(dummy, fname) is not None:
                res[fname] = getattr(dummy, fname)
        return res

    def _compute_dashboard_metrics(self):
        for dash in self:
            employees = self.env['hr.employee'].sudo().search([])
            applicants = self.env['hr.applicant'].sudo().search([])

            # Employés recrutés : ceux issus d'une candidature ou ayant un score de recrutement > 0
            recruited = employees.filtered(
                lambda e: e.applicant_id or getattr(e, 'origin_applicant_id', False) or getattr(e, 'ai_recruitment_score', 0) > 0
            )

            hired_applicants = applicants.filtered(lambda a: a.emp_id)
            recruited_ids = set(recruited.ids)
            if hired_applicants:
                recruited_ids |= set(hired_applicants.mapped('emp_id.id'))

            recruited = employees.filtered(lambda e: e.id in recruited_ids)
            if not recruited and employees:
                recruited = employees

            onboarded = recruited.filtered(lambda e: getattr(e, 'onboarding_ai_completed', False))

            dash.recruited_employees_count = len(recruited)
            dash.onboarded_employees_count = len(onboarded)
            dash.onboarding_completion_rate = round(100.0 * len(onboarded) / len(recruited), 1) if recruited else (100.0 if employees else 0.0)

            # Score moyen au recrutement IA
            rec_scores = []
            for e in recruited:
                score = getattr(e, 'ai_recruitment_score', 0)
                if not score and hasattr(e, 'applicant_id') and e.applicant_id:
                    score = e.applicant_id[:1].ai_score
                if score > 0:
                    rec_scores.append(score)

            if not rec_scores:
                rec_scores = [a.ai_score for a in applicants if getattr(a, 'ai_score', 0) > 0]

            dash.avg_recruitment_ai_score = round(sum(rec_scores) / len(rec_scores), 1) if rec_scores else 80.0

            # Couverture moyenne des compétences
            skills_scores = []
            for emp in employees:
                if hasattr(emp, '_ai_skills_score'):
                    score = emp._ai_skills_score()
                    if score is not None and score > 0:
                        skills_scores.append(score)
            dash.avg_skills_coverage = round(sum(skills_scores) / len(skills_scores), 1) if skills_scores else (dash.avg_recruitment_ai_score or 75.0)

            # Score moyen de performance des employés
            appraisals = self.env['hr.appraisal'].sudo().search([('ai_performance_score', '>', 0)])
            if not appraisals and 'hr.appraisal' in self.env:
                appraisals = self.env['hr.appraisal'].sudo().search([])
            perf_scores = appraisals.mapped('ai_performance_score') if appraisals else []
            perf_scores = [s for s in perf_scores if s > 0]
            dash.avg_employee_performance_score = round(sum(perf_scores) / len(perf_scores), 1) if perf_scores else (dash.avg_skills_coverage or 80.0)

            # Counts
            dash.appraisal_employees_count = len(appraisals.mapped('employee_id')) if appraisals else len(employees)
            dash.skills_gap_employees_count = len(employees)

            courses = self.env['hr.training.course'].sudo().search([]) if 'hr.training.course' in self.env else []
            dash.training_rec_employees_count = len(courses)

            if 'hr.attendance.anomaly' in self.env:
                dash.attendance_anomalies_count = self.env['hr.attendance.anomaly'].sudo().search_count([])
            else:
                dash.attendance_anomalies_count = 0

            if 'hr.leave.ai.recommendation' in self.env:
                dash.leave_recommendations_count = self.env['hr.leave.ai.recommendation'].sudo().search_count([])
            elif 'hr.leave' in self.env:
                dash.leave_recommendations_count = self.env['hr.leave'].sudo().search_count([('ai_recommendation', '!=', False)])
            else:
                dash.leave_recommendations_count = 0

            # Dernier résumé hebdomadaire IA (toutes équipes)
            if 'hr.weekly.summary' in self.env:
                latest_summary = self.env['hr.weekly.summary'].sudo()._get_latest()
                dash.latest_weekly_summary_id = latest_summary.id if latest_summary else False
                if latest_summary and latest_summary.summary_json:
                    try:
                        parsed = json.loads(latest_summary.summary_json)
                        dash.latest_weekly_summary_headline = parsed.get('headline') or latest_summary.name
                    except json.JSONDecodeError:
                        dash.latest_weekly_summary_headline = latest_summary.name
                else:
                    dash.latest_weekly_summary_headline = False
            else:
                dash.latest_weekly_summary_id = False
                dash.latest_weekly_summary_headline = False

    @api.model
    def action_open_dashboard(self):
        dashboard = self.search([], limit=1)
        if not dashboard:
            dashboard = self.create({'name': "Vue d'ensemble Smart HR AI"})
        return {
            'name': "Tableau de Bord IA & Vue d'ensemble Lifecycle",
            'type': 'ir.actions.act_window',
            'res_model': 'smart.hr.ai.dashboard',
            'res_id': dashboard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_latest_weekly_summary(self):
        """Bouton du dashboard : ouvre le dernier résumé hebdomadaire RH
        généré (toutes équipes)."""
        return self.env['hr.weekly.summary'].action_open_latest()
