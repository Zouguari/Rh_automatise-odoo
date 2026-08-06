# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrAppraisal(models.Model):
    _name = 'hr.appraisal'
    _description = "Évaluation de performance"
    _order = 'create_date desc'

    name = fields.Char(string="Référence", compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string="Employé", required=True, index=True, ondelete='cascade',
    )
    manager_id = fields.Many2one(
        'hr.employee', string="Manager", ondelete='set null',
    )
    state = fields.Selection(
        selection=[('draft', 'Brouillon'), ('done', 'Terminée')],
        string="État", default='draft', required=True,
    )
    company_id = fields.Many2one(
        'res.company', string="Société",
        related='employee_id.company_id', store=True, readonly=True,
    )
    ai_performance_score = fields.Float(string="Score de performance IA (0-100)", readonly=True, copy=False)
    ai_high_potential = fields.Boolean(string="Haut potentiel (IA)", readonly=True, copy=False)
    ai_summary = fields.Text(string="Synthèse IA", readonly=True, copy=False)
    ai_computed_on = fields.Datetime(string="Analysée le", readonly=True, copy=False)

    @api.depends('employee_id')
    def _compute_name(self):
        for appraisal in self:
            appraisal.name = appraisal.employee_id.name if appraisal.employee_id else "Évaluation"

    def action_mark_done(self):
        self.write({'state': 'done'})

    def action_generate_ai_appraisal(self):
        """Calcule (ou recalcule) l'analyse IA de chaque évaluation.

        NOTE : contrairement à hr_leaves_ai (calcul automatique à la
        création), ce calcul est déclenché à la demande — une évaluation
        de performance n'a de sens qu'une fois une période de travail
        écoulée, pas au moment de sa simple création."""
        threshold = float(
            self.env['ir.config_parameter'].sudo().get_param(
                'hr_appraisal_ai.high_potential_threshold', default=75
            )
        )

        for appraisal in self:
            employee = appraisal.employee_id
            attendance_score = employee._ai_attendance_score()
            skills_score = employee._ai_skills_score()

            components = [s for s in (attendance_score, skills_score) if s is not None]
            overall_score = round(sum(components) / len(components), 1) if components else 0.0
            high_potential = overall_score >= threshold and bool(components)

            summary_parts = []
            if attendance_score is not None:
                summary_parts.append("Ponctualité : %.0f/100." % attendance_score)
            else:
                summary_parts.append("Ponctualité : pas assez de données de présence pour évaluer.")
            if skills_score is not None:
                summary_parts.append("Couverture des compétences requises : %.0f/100." % skills_score)
            else:
                summary_parts.append("Compétences : aucune exigence définie pour ce poste.")
            if high_potential:
                summary_parts.append("Profil identifié comme à haut potentiel.")

            appraisal.write({
                'ai_performance_score': overall_score,
                'ai_high_potential': high_potential,
                'ai_summary': " ".join(summary_parts),
                'ai_computed_on': fields.Datetime.now(),
            })

            self.env['hr.appraisal.ai.analysis'].sudo().create({
                'appraisal_id': appraisal.id,
                'employee_id': employee.id,
                'performance_score': overall_score,
                'high_potential': high_potential,
                'summary': appraisal.ai_summary,
            })
        return True
