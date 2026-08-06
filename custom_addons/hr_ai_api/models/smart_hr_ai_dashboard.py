# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SmartHrAiDashboard(models.Model):
    _name = 'smart.hr.ai.dashboard'
    _description = "Tableau de bord global Smart HR AI"

    name = fields.Char(string="Titre", default="Statistiques Globales Smart HR AI")

    recruited_employees_count = fields.Integer(
        string="Employés Recrutés via IA",
        compute='_compute_dashboard_metrics'
    )
    onboarded_employees_count = fields.Integer(
        string="Employés Onboardés Automatiquement",
        compute='_compute_dashboard_metrics'
    )
    avg_recruitment_ai_score = fields.Float(
        string="Score Moyen Recrutement IA (%)",
        compute='_compute_dashboard_metrics'
    )
    avg_skills_coverage = fields.Float(
        string="Couverture Moyenne des Compétences (%)",
        compute='_compute_dashboard_metrics'
    )
    onboarding_completion_rate = fields.Float(
        string="Taux de Complétion Onboarding (%)",
        compute='_compute_dashboard_metrics'
    )

    def _compute_dashboard_metrics(self):
        for dash in self:
            employees = self.env['hr.employee'].sudo().search([])
            recruited = employees.filtered(lambda e: e.applicant_id or (hasattr(e, 'ai_recruitment_score') and e.ai_recruitment_score > 0))
            onboarded = employees.filtered(lambda e: getattr(e, 'onboarding_ai_completed', False))

            dash.recruited_employees_count = len(recruited)
            dash.onboarded_employees_count = len(onboarded)

            scores = [e.ai_recruitment_score for e in recruited if getattr(e, 'ai_recruitment_score', 0) > 0]
            dash.avg_recruitment_ai_score = round(sum(scores) / len(scores), 1) if scores else 0.0

            skills_scores = []
            for emp in employees:
                if hasattr(emp, '_ai_skills_score'):
                    score = emp._ai_skills_score()
                    if score is not None:
                        skills_scores.append(score)
            dash.avg_skills_coverage = round(sum(skills_scores) / len(skills_scores), 1) if skills_scores else 0.0

            dash.onboarding_completion_rate = round(100.0 * len(onboarded) / len(recruited), 1) if recruited else 0.0

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
