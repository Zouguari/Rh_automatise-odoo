# -*- coding: utf-8 -*-
import json
import logging
import urllib.request
import urllib.error
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


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
        """Calcule l'évaluation IA complète de chaque employé avec Gemini AI
        (ou fallback heuristique enrichi si l'API est indisponible)."""
        threshold = float(
            self.env['ir.config_parameter'].sudo().get_param(
                'hr_appraisal_ai.high_potential_threshold', default=75
            )
        )

        for appraisal in self:
            employee = appraisal.employee_id
            if not employee:
                continue

            result = appraisal._call_gemini_appraisal_evaluation(employee)

            perf_score = float(result.get('performance_score') or 75.0)
            high_pot = bool(result.get('high_potential', perf_score >= threshold))

            summary_parts = []
            if result.get('manager_summary'):
                summary_parts.append(result['manager_summary'])
            if result.get('strengths'):
                summary_parts.append("• Points forts : " + ", ".join(result['strengths']))
            if result.get('weaknesses'):
                summary_parts.append("• Axes d'amélioration : " + ", ".join(result['weaknesses']))
            if result.get('recommendations'):
                summary_parts.append("• Recommandations : " + ", ".join(result['recommendations']))

            final_summary = "\n".join(summary_parts) if summary_parts else "Évaluation IA générée avec succès."

            appraisal.write({
                'ai_performance_score': perf_score,
                'ai_high_potential': high_pot,
                'ai_summary': final_summary,
                'ai_computed_on': fields.Datetime.now(),
            })

            self.env['hr.appraisal.ai.analysis'].sudo().create({
                'appraisal_id': appraisal.id,
                'employee_id': employee.id,
                'performance_score': perf_score,
                'high_potential': high_pot,
                'summary': final_summary,
            })
        return True

    def _call_gemini_appraisal_evaluation(self, employee):
        """Service réutilisable effectuant l'évaluation IA de performance via Gemini API
        ou fallback heuristique en cas d'absence de clé ou problème réseau."""
        api_key = self.env['ir.config_parameter'].sudo().get_param('smart_hr_ai.gemini_api_key')

        recruitment_score = getattr(employee, 'ai_recruitment_score', 0) or 80.0
        recruitment_summary = getattr(employee, 'ai_recruitment_summary', '') or 'Profil recruté via Smart HR AI'
        extracted_skills = getattr(employee, 'ai_extracted_skills', '') or 'Non spécifiées'
        extracted_tech = getattr(employee, 'ai_extracted_technologies', '') or 'Non spécifiées'
        extracted_soft = getattr(employee, 'ai_extracted_soft_skills', '') or 'Non spécifiées'
        extracted_lang = getattr(employee, 'ai_extracted_languages', '') or 'Français, Anglais'
        extracted_certif = getattr(employee, 'ai_extracted_certifications', '') or 'Aucune'

        attendance_score = employee._ai_attendance_score()
        attendance_info = f"{attendance_score:.0f}/100" if attendance_score is not None else "Données de présence insuffisantes (nouvellement embauché)"

        skills_coverage = employee._ai_skills_score() or recruitment_score or 75.0
        onboarding_status = "Onboarding IA effectué" if getattr(employee, 'onboarding_ai_completed', False) else "Onboarding en cours"

        if api_key:
            prompt = f"""Tu es le sous-agent RH d'Intelligence Artificielle dédié à l'évaluation des performances et du potentiel des employés.
Analyse le profil RH complet de l'employé suivant et génère une évaluation de performance équilibrée, réaliste et constructive.

PROFIL EMPLOYÉ :
- Nom : {employee.name}
- Poste : {employee.job_id.name if employee.job_id else 'Non défini'}
- Département : {employee.department_id.name if employee.department_id else 'Non défini'}
- Score IA au Recrutement : {recruitment_score}/100
- Synthèse Recrutement : {recruitment_summary}
- Compétences extraites du CV : {extracted_skills}
- Technologies extraites : {extracted_tech}
- Soft Skills : {extracted_soft}
- Langues : {extracted_lang}
- Certifications : {extracted_certif}
- Couverture calculée des compétences du poste : {skills_coverage:.1f}%
- Ponctualité & Présences : {attendance_info}
- Statut d'Onboarding : {onboarding_status}

CONSIGNES IMPORTANTES :
1. Génère une évaluation complète, réaliste et encourageante pour cet employé.
2. Ne donne JAMAIS un score de 0. Si la ponctualité manque (nouvellement embauché), évalue d'après les compétences, le score de recrutement et l'onboarding.
3. Renvoie STRICTEMENT et UNIQUEMENT un objet JSON valide avec cette structure exacte :
{{
  "performance_score": float_entre_65_et_98,
  "skills_coverage": float_entre_50_et_100,
  "strengths": ["Point fort 1", "Point fort 2"],
  "weaknesses": ["Axe d'amélioration 1", "Axe d'amélioration 2"],
  "manager_summary": "Synthèse synthétique et professionnelle pour le manager...",
  "high_potential": boolean,
  "recommendations": ["Recommandation 1", "Recommandation 2"]
}}"""

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                    "thinkingConfig": {"thinkingBudget": 0}
                }
            }).encode('utf-8')

            try:
                req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=12) as response:
                    res_body = response.read().decode('utf-8')
                    res_json = json.loads(res_body)
                    candidates = res_json.get('candidates', [])
                    if candidates:
                        parts = candidates[0].get('content', {}).get('parts', [])
                        text_resp = "".join(p.get('text', '') for p in parts if not p.get('thought')).strip()
                        if text_resp.startswith('```'):
                            text_resp = text_resp.strip('`')
                            if text_resp.lower().startswith('json'):
                                text_resp = text_resp[4:]
                            text_resp = text_resp.strip()
                        parsed = json.loads(text_resp)
                        if isinstance(parsed, dict) and 'performance_score' in parsed:
                            return parsed
            except Exception as e:
                _logger.warning("Échec de l'appel Gemini pour l'évaluation de %s, basculement heuristique : %s", employee.name, e)

        # Fallback heuristique enrichi (sans score à 0)
        components = [s for s in (recruitment_score, skills_coverage, attendance_score) if s is not None]
        perf_score = round(sum(components) / len(components), 1) if components else 80.0

        summary = (
            f"Évaluation IA de bienvenue : Performance estimée à {perf_score:.1f}/100. "
            f"Basée sur le score de recrutement ({recruitment_score:.1f}/100), la couverture des compétences ({skills_coverage:.1f}%), "
            f"et l'état d'onboarding."
        )

        return {
            'performance_score': perf_score,
            'skills_coverage': skills_coverage,
            'strengths': [f"Solide bagage technique ({extracted_skills[:40]}...)" if len(extracted_skills) > 5 else "Bases techniques solides", "Intégration rapide via l'onboarding IA"],
            'weaknesses': ["Continuer l'acquisition des compétences cibles du poste"],
            'manager_summary': summary,
            'high_potential': perf_score >= 75.0,
            'recommendations': ["Suivre le parcours de formation recommandé", "Point d'étape à 30 jours"],
        }
