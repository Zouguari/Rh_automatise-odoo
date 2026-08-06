# -*- coding: utf-8 -*-
import logging
import re
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    applicant_id = fields.Many2one(
        'hr.applicant',
        string="Candidature IA d'origine",
        readonly=True,
        copy=False,
        ondelete='set null',
        help="Lien permanent vers la candidature ayant donné naissance à cet employé."
    )
    ai_recruitment_score = fields.Float(
        string="Score IA Recrutement",
        readonly=True,
        copy=False,
        help="Score global calculé par l'IA lors du recrutement."
    )
    ai_recruitment_summary = fields.Text(
        string="Synthèse IA Recrutement",
        readonly=True,
        copy=False,
        help="Résumé du profil et du CV issu du recrutement IA."
    )
    ai_extracted_skills = fields.Text(
        string="Compétences (IA Recrutement)",
        readonly=True,
        copy=False,
    )
    ai_extracted_technologies = fields.Text(
        string="Technologies (IA Recrutement)",
        readonly=True,
        copy=False,
    )
    ai_extracted_soft_skills = fields.Text(
        string="Soft Skills (IA Recrutement)",
        readonly=True,
        copy=False,
    )
    ai_extracted_languages = fields.Text(
        string="Langues (IA Recrutement)",
        readonly=True,
        copy=False,
    )
    ai_extracted_certifications = fields.Text(
        string="Certifications (IA Recrutement)",
        readonly=True,
        copy=False,
    )
    onboarding_ai_completed = fields.Boolean(
        string="Onboarding IA Effectué",
        default=False,
        readonly=True,
        copy=False,
    )
    onboarding_ai_date = fields.Datetime(
        string="Date Onboarding IA",
        readonly=True,
        copy=False,
    )

    # Smart Buttons Counters
    applicant_count = fields.Integer(
        string="Candidatures",
        compute='_compute_lifecycle_counts',
    )
    appraisal_count = fields.Integer(
        string="Évaluations IA",
        compute='_compute_lifecycle_counts',
    )
    recommended_training_count = fields.Integer(
        string="Formations Recommandées",
        compute='_compute_lifecycle_counts',
    )
    leave_ai_count = fields.Integer(
        string="Demandes de Congés",
        compute='_compute_lifecycle_counts',
    )
    attendance_anomaly_count = fields.Integer(
        string="Anomalies de Présence",
        compute='_compute_lifecycle_counts',
    )

    def _compute_lifecycle_counts(self):
        for emp in self:
            emp.applicant_count = 1 if emp.applicant_id else 0

            # Évaluations IA
            if 'hr.appraisal' in self.env:
                emp.appraisal_count = self.env['hr.appraisal'].sudo().search_count([
                    ('employee_id', '=', emp.id)
                ])
            else:
                emp.appraisal_count = 0

            # Formations recommandées via Skills Gap
            if hasattr(emp, 'get_skill_gap_analysis'):
                try:
                    analysis = emp.get_skill_gap_analysis()
                    emp.recommended_training_count = len(analysis.get('recommended_courses', []))
                except Exception:
                    emp.recommended_training_count = 0
            else:
                emp.recommended_training_count = 0

            # Congés
            if 'hr.leave' in self.env:
                emp.leave_ai_count = self.env['hr.leave'].sudo().search_count([
                    ('employee_id', '=', emp.id)
                ])
            else:
                emp.leave_ai_count = 0

            # Anomalies de présence
            if 'hr.attendance.anomaly' in self.env:
                emp.attendance_anomaly_count = self.env['hr.attendance.anomaly'].sudo().search_count([
                    ('employee_id', '=', emp.id)
                ])
            else:
                emp.attendance_anomaly_count = 0

    # Navigation Actions for Smart Buttons
    def action_view_origin_applicant(self):
        self.ensure_one()
        if not self.applicant_id:
            return {}
        return {
            'name': "Candidature d'origine",
            'type': 'ir.actions.act_window',
            'res_model': 'hr.applicant',
            'res_id': self.applicant_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_appraisals(self):
        self.ensure_one()
        action = self.env.ref('hr_appraisal_ai.action_hr_appraisal_ai').read()[0]
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_view_recommended_trainings(self):
        self.ensure_one()
        analysis = self.get_skill_gap_analysis() if hasattr(self, 'get_skill_gap_analysis') else {}
        course_ids = [c['id'] for c in analysis.get('recommended_courses', []) if c.get('id')]
        action = self.env.ref('hr_skills_ai.action_hr_training_course').read()[0]
        if course_ids:
            action['domain'] = [('id', 'in', course_ids)]
        return action

    def action_view_skills_gap(self):
        self.ensure_one()
        return {
            'name': f"Analyse des Compétences & Lacunes — {self.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'hr.skills.gap.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_employee_id': self.id},
        }

    def action_view_leaves(self):
        self.ensure_one()
        action = self.env.ref('hr_leaves_ai.action_hr_leave_ai').read()[0]
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_view_attendance_anomalies(self):
        self.ensure_one()
        action = self.env.ref('hr_attendance_ai.action_hr_attendance_anomaly').read()[0]
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    # Reusable Automatic AI Onboarding Service Method
    def action_run_ai_onboarding(self):
        """Service métier d'intégration automatique (Onboarding IA).
        Alimente le profil compétences Odoo, génère l'évaluation initiale,
        évalue les besoins de formation et consigne l'opération."""
        for emp in self:
            try:
                # 1. Populate Odoo Skills Engine from CV Extraction
                emp._populate_employee_skills_from_ai()

                # 2. Automatic Initial AI Appraisal
                if 'hr.appraisal' in self.env:
                    appraisal = self.env['hr.appraisal'].sudo().search([
                        ('employee_id', '=', emp.id),
                        ('state', '=', 'draft')
                    ], limit=1)
                    if not appraisal:
                        appraisal = self.env['hr.appraisal'].sudo().create({
                            'employee_id': emp.id,
                            'manager_id': emp.parent_id.id or (emp.department_id.manager_id.id if emp.department_id else False),
                            'state': 'draft',
                        })
                    appraisal.action_generate_ai_appraisal()

                # 3. Check Skill Gap & Ensure Training Availability
                if hasattr(emp, 'get_skill_gap_analysis'):
                    analysis = emp.get_skill_gap_analysis()
                    missing = analysis.get('missing_skills', [])
                    for skill_name in missing:
                        skill = self.env['hr.skill'].sudo().search([('name', '=ilike', skill_name)], limit=1)
                        if skill:
                            course = self.env['hr.training.course'].sudo().search([('skill_id', '=', skill.id)], limit=1)
                            if not course:
                                self.env['hr.training.course'].sudo().create({
                                    'name': f"Formation {skill.name} - Niveau Requis",
                                    'skill_id': skill.id,
                                    'duration_hours': 14.0,
                                    'description': f"Formation automatique suggérée par Smart HR AI pour combler la lacune d'onboarding sur {skill.name}.",
                                })

                # 4. Mark Onboarding Completion
                emp.sudo().write({
                    'onboarding_ai_completed': True,
                    'onboarding_ai_date': fields.Datetime.now(),
                })

                # Log chatter notification
                score_display = f"{emp.ai_recruitment_score:.1f}" if emp.ai_recruitment_score else "N/A"
                emp.message_post(
                    body=(
                        f"🚀 <strong>Onboarding IA finalisé automatiquement</strong><br/>"
                        f"• Transfert des données candidat effectué (Score IA Recrutement: {score_display}/100).<br/>"
                        f"• Compétences de base enregistrées dans le profil.<br/>"
                        f"• Évaluation initiale de performance générée.<br/>"
                        f"• Plan de compétences et formations recommandées prêts."
                    )
                )
            except Exception as e:
                _logger.error("Erreur lors de l'Onboarding IA pour l'employé %s : %s", emp.name, e, exc_info=True)

    def _populate_employee_skills_from_ai(self):
        """Extrait les noms de compétences depuis ai_extracted_skills et ai_extracted_technologies
        et crée les enregistrements hr.employee.skill correspondants."""
        self.ensure_one()
        if 'hr.skill' not in self.env or 'hr.employee.skill' not in self.env:
            return

        raw_texts = [self.ai_extracted_skills or '', self.ai_extracted_technologies or '']
        skill_names = set()
        for text in raw_texts:
            items = re.split(r'[,;\n•\-]+', text)
            for item in items:
                cleaned = item.strip()
                if cleaned and len(cleaned) <= 60:
                    skill_names.add(cleaned)

        if not skill_names:
            return

        skill_type = self.env['hr.skill.type'].sudo().search([('name', '=', 'Technique')], limit=1)
        if not skill_type:
            skill_type = self.env['hr.skill.type'].sudo().search([], limit=1)
        if not skill_type:
            skill_type = self.env['hr.skill.type'].sudo().create({'name': 'Technique'})

        skill_level = self.env['hr.skill.level'].sudo().search([('skill_type_id', '=', skill_type.id)], order='level_progress asc', limit=1)
        if not skill_level:
            skill_level = self.env['hr.skill.level'].sudo().create({
                'name': 'Intermédiaire',
                'skill_type_id': skill_type.id,
                'level_progress': 50,
            })

        existing_skills = self.env['hr.employee.skill'].sudo().search([('employee_id', '=', self.id)])
        existing_skill_ids = existing_skills.mapped('skill_id.id')

        for name in skill_names:
            skill = self.env['hr.skill'].sudo().search([('name', '=ilike', name)], limit=1)
            if not skill:
                skill = self.env['hr.skill'].sudo().create({
                    'name': name,
                    'skill_type_id': skill_type.id,
                })
            if skill.id not in existing_skill_ids:
                try:
                    self.env['hr.employee.skill'].sudo().create({
                        'employee_id': self.id,
                        'skill_id': skill.id,
                        'skill_level_id': skill_level.id,
                        'skill_type_id': skill_type.id,
                    })
                except Exception as e:
                    _logger.warning("Impossible de lier la compétence %s à l'employé %s : %s", name, self.name, e)
