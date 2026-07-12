# -*- coding: utf-8 -*-

import logging
from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

INTERVIEW_QUESTIONS_PROMPT = """Tu es un recruteur expert. Génère une liste de questions d'entretien pertinentes
et personnalisées pour ce candidat, en te basant sur son profil et le poste visé.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, sans markdown :
{{
  "questions": [
    "question 1",
    "question 2"
  ]
}}

Génère exactement 8 questions réparties ainsi :
- 2 questions techniques liées aux compétences du candidat
- 2 questions sur ses expériences passées les plus pertinentes pour le poste
- 2 questions sur les compétences manquantes ou les points à approfondir
- 2 questions comportementales/motivationnelles

--- OFFRE D'EMPLOI ---
Titre : {job_title}
Compétences requises : {required_skills}

--- PROFIL CANDIDAT ---
Résumé : {candidate_summary}
Compétences : {candidate_skills}
Expériences : {candidate_experience}
Compétences manquantes identifiées : {missing_skills}
"""


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    def action_generate_interview_questions(self):
        for applicant in self:
            if not applicant.ai_summary:
                raise UserError("Lance d'abord l'analyse IA du CV avant de générer les questions.")
            try:
                result = applicant._call_gemini_json(applicant._build_interview_prompt())
                questions = result.get('questions', [])
                applicant.ai_interview_questions = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
            except Exception as e:
                _logger.error("Erreur génération questions pour %s: %s", applicant.partner_name, e)
                raise UserError(f"Erreur lors de la génération des questions : {e}")

    def _build_interview_prompt(self):
        self.ensure_one()
        job = self.job_id
        return INTERVIEW_QUESTIONS_PROMPT.format(
            job_title=job.name or "",
            required_skills=job.required_skills or "Non spécifié",
            candidate_summary=self.ai_summary or "",
            candidate_skills=self.extracted_skills or "Non renseigné",
            candidate_experience=self.extracted_experience or "Non renseigné",
            missing_skills=self.ai_missing_skills or "Aucune identifiée",
        )
