# -*- coding: utf-8 -*-
import json
import logging
import re
from odoo import models, fields, api

from .hr_applicant import SKILL_LEVEL_TARGET_PROGRESS

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    origin_applicant_id = fields.Many2one(
        'hr.applicant',
        string="Candidature IA d'origine",
        compute='_compute_origin_applicant_id',
        store=True,
        readonly=True,
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
    ai_extracted_skills_detailed = fields.Text(
        string="Compétences (IA Recrutement) - détail niveaux (JSON)",
        readonly=True,
        copy=False,
        help="Détail structuré [{'name', 'level'}] transféré depuis la candidature "
             "d'origine (hr.applicant.extracted_skills_detailed). Utilisé par "
             "_populate_employee_skills_from_ai() pour attribuer à chaque compétence "
             "un niveau réaliste sur le profil de compétences Odoo, au lieu du niveau "
             "le plus bas du système appliqué uniformément (bug corrigé le 15/08/2026)."
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

    @api.depends('applicant_id')
    def _compute_origin_applicant_id(self):
        for emp in self:
            emp.origin_applicant_id = emp.applicant_id[:1] if emp.applicant_id else False

    def _compute_lifecycle_counts(self):
        for emp in self:
            emp.applicant_count = len(emp.applicant_id) if emp.applicant_id else 0

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
        applicant = self.origin_applicant_id or (self.applicant_id[:1] if self.applicant_id else False)
        if not applicant:
            return {}
        return {
            'name': "Candidature d'origine",
            'type': 'ir.actions.act_window',
            'res_model': 'hr.applicant',
            'res_id': applicant.id,
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
        """Crée les enregistrements hr.employee.skill correspondant aux
        compétences extraites du CV, avec pour chacune un NIVEAU RÉALISTE
        déduit par l'IA à l'extraction (débutant/intermédiaire/avancé/expert),
        plutôt que le niveau le plus bas configuré dans le système appliqué
        uniformément à toutes les compétences de tous les employés.

        Correctif du 15/08/2026 : un candidat avec 5 ans d'expérience Python
        (CV réel testé) se retrouvait avec "Python - Débutant (15%)" sur sa
        fiche employé après embauche, comme absolument toutes ses autres
        compétences — l'ancien code prenait systématiquement
        `hr.skill.level` avec le `level_progress` le plus bas du type de
        compétence, sans aucun lien avec le contenu réel du CV. Le niveau
        est maintenant choisi via _pick_skill_level_for(), à partir du
        niveau estimé par Gemini lors de l'extraction (voir hr_applicant.py
        ::EXTRACTION_PROMPT et ::_normalize_extracted_skills)."""
        self.ensure_one()
        if 'hr.skill' not in self.env or 'hr.employee.skill' not in self.env:
            return

        skills_detailed = self._parse_ai_skills_detailed()
        if not skills_detailed:
            return

        skill_type = self.env['hr.skill.type'].sudo().search([('name', '=', 'Technique')], limit=1)
        if not skill_type:
            skill_type = self.env['hr.skill.type'].sudo().search([], limit=1)
        if not skill_type:
            skill_type = self.env['hr.skill.type'].sudo().create({'name': 'Technique'})

        # Garantit une échelle d'AU MOINS 2 niveaux distincts pour ce type
        # de compétence : avec un seul niveau configuré (ancien fallback),
        # toute recherche du "niveau le plus proche" retombe forcément sur
        # ce niveau unique, ce qui reproduirait exactement le bug corrigé
        # ici. N'intervient que si le type n'a ENCORE AUCUN niveau
        # configuré — un type déjà configuré (même avec un seul niveau
        # volontaire) n'est jamais modifié.
        self._ensure_default_skill_levels(skill_type)

        existing_skills = self.env['hr.employee.skill'].sudo().search([('employee_id', '=', self.id)])
        existing_skill_ids = set(existing_skills.mapped('skill_id.id'))

        for item in skills_detailed:
            name = item['name']
            level = item['level']
            if not name or len(name) > 60:
                continue

            # Si la compétence existe déjà dans le système (catalogue
            # standard ou créée par un autre employé), on réutilise son
            # VRAI type de compétence plutôt que notre type de repli
            # "Technique" — sinon le niveau choisi ensuite pourrait
            # provenir d'une échelle qui ne correspond pas au type réel
            # de la compétence (ex: "Python" déjà classé dans un type
            # "Langages de programmation" avec sa propre échelle).
            skill = self.env['hr.skill'].sudo().search([('name', '=ilike', name)], limit=1)
            if skill:
                target_skill_type = skill.skill_type_id
            else:
                skill = self.env['hr.skill'].sudo().create({
                    'name': name,
                    'skill_type_id': skill_type.id,
                })
                target_skill_type = skill_type

            if skill.id in existing_skill_ids:
                continue

            skill_level = self._pick_skill_level_for(target_skill_type, level)
            if not skill_level:
                continue

            try:
                self.env['hr.employee.skill'].sudo().create({
                    'employee_id': self.id,
                    'skill_id': skill.id,
                    'skill_level_id': skill_level.id,
                    'skill_type_id': target_skill_type.id,
                })
            except Exception as e:
                _logger.warning(
                    "Impossible de lier la compétence %s (niveau estimé : %s) "
                    "à l'employé %s : %s", name, level, self.name, e,
                )

    def _parse_ai_skills_detailed(self):
        """Renvoie la liste [{'name', 'level'}] des compétences extraites du
        CV par l'IA au recrutement.

        Utilise en priorité le détail structuré transféré depuis la
        candidature d'origine (ai_extracted_skills_detailed, alimenté par
        hr.applicant.extracted_skills_detailed — voir _transfer_ai_
        recruitment_data_to_employee dans hr_applicant.py). Si ce détail
        est absent ou illisible (ex : employé créé avant ce correctif, ou
        sans passage par le pipeline IA de recrutement), on retombe sur un
        parsing basique du texte brut (ai_extracted_skills /
        ai_extracted_technologies), avec un niveau 'intermediaire' par
        défaut faute d'indice plus précis — mieux qu'un niveau bas
        systématique, sans pour autant inventer un niveau que rien ne
        justifie."""
        self.ensure_one()
        raw_json = self.ai_extracted_skills_detailed or ''
        if raw_json:
            try:
                parsed = json.loads(raw_json)
                result = []
                for entry in parsed:
                    name = (entry.get('name') or '').strip()
                    level = (entry.get('level') or 'intermediaire').strip().lower()
                    if level not in SKILL_LEVEL_TARGET_PROGRESS:
                        level = 'intermediaire'
                    if name:
                        result.append({'name': name, 'level': level})
                if result:
                    return result
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                _logger.warning(
                    "Détail JSON des compétences illisible pour %s (%s), "
                    "retour au parsing basique du texte brut.", self.name, e,
                )

        raw_texts = [self.ai_extracted_skills or '', self.ai_extracted_technologies or '']
        skill_names = set()
        for text in raw_texts:
            for chunk in re.split(r'[,;\n•\-]+', text):
                cleaned = chunk.strip(' -')
                if cleaned and len(cleaned) <= 60:
                    skill_names.add(cleaned)
        return [{'name': n, 'level': 'intermediaire'} for n in skill_names]

    def _ensure_default_skill_levels(self, skill_type):
        """Garantit qu'un type de compétence dispose d'au moins l'échelle
        standard à 4 niveaux (Débutant/Intermédiaire/Avancé/Expert),
        UNIQUEMENT s'il n'a actuellement AUCUN niveau configuré. N'écrase
        et ne complète jamais une échelle déjà définie par l'utilisateur,
        même partielle ou à un seul niveau."""
        self.ensure_one()
        has_levels = self.env['hr.skill.level'].sudo().search_count(
            [('skill_type_id', '=', skill_type.id)]
        )
        if has_levels:
            return
        for name, progress in (
            ("Débutant", 20), ("Intermédiaire", 50), ("Avancé", 75), ("Expert", 100),
        ):
            self.env['hr.skill.level'].sudo().create({
                'name': name,
                'skill_type_id': skill_type.id,
                'level_progress': progress,
            })

    def _pick_skill_level_for(self, skill_type, level_label):
        """Choisit, parmi les niveaux RÉELLEMENT configurés pour ce type de
        compétence, celui dont le level_progress est le plus proche de la
        cible associée au niveau estimé par l'IA (SKILL_LEVEL_TARGET_PROGRESS).
        S'adapte ainsi à n'importe quelle échelle définie par l'utilisateur
        (2, 3, 5 niveaux, valeurs personnalisées...) plutôt que de supposer
        une échelle fixe."""
        levels = self.env['hr.skill.level'].sudo().search(
            [('skill_type_id', '=', skill_type.id)], order='level_progress asc'
        )
        if not levels:
            return False
        target = SKILL_LEVEL_TARGET_PROGRESS.get(level_label, 50)
        return min(levels, key=lambda l: abs(l.level_progress - target))
