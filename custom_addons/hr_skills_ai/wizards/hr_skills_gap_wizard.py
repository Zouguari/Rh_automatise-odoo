# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HrSkillsGapWizard(models.TransientModel):
    _name = 'hr.skills.gap.wizard'
    _description = "Assistant de Rapport Skills Gap"

    employee_id = fields.Many2one('hr.employee', string="Employé", required=True)
    job_id = fields.Many2one('hr.job', string="Poste Cible", compute='_compute_analysis')
    matched_skills = fields.Text(string="Compétences Valides", compute='_compute_analysis')
    missing_skills = fields.Text(string="Compétences Manquantes", compute='_compute_analysis')
    underleveled_skills = fields.Text(string="Compétences À Renforcer", compute='_compute_analysis')
    recommended_courses = fields.Text(string="Formations Recommandées", compute='_compute_analysis')

    @api.depends('employee_id')
    def _compute_analysis(self):
        for wizard in self:
            if not wizard.employee_id:
                wizard.job_id = False
                wizard.matched_skills = ""
                wizard.missing_skills = ""
                wizard.underleveled_skills = ""
                wizard.recommended_courses = ""
                continue

            analysis = wizard.employee_id.get_skill_gap_analysis()
            wizard.job_id = analysis.get('job_id')
            wizard.matched_skills = "\n".join(["• " + s for s in analysis.get('matched_skills', [])]) or "Aucune"
            wizard.missing_skills = "\n".join(["• " + s for s in analysis.get('missing_skills', [])]) or "Aucune lacune identifiée"

            underlevel_text = []
            for u in analysis.get('underleveled_skills', []):
                underlevel_text.append(f"• {u['skill']} : {u['current_level']} ➔ Niveau requis: {u['required_level']}")
            wizard.underleveled_skills = "\n".join(underlevel_text) or "Aucun sous-niveau"

            course_text = []
            for c in analysis.get('recommended_courses', []):
                course_text.append(f"• {c['name']} ({c['duration_hours']}h) - {c['skill']}")
            wizard.recommended_courses = "\n".join(course_text) or "Aucune formation nécessaire"
