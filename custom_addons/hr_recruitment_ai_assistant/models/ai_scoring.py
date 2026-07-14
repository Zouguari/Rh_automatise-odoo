# -*- coding: utf-8 -*-

import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SCORING_PROMPT = """Tu es un assistant de recrutement expert. Compare le profil du candidat ci-dessous avec les exigences du poste, et évalue leur compatibilité.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, sans markdown, avec exactement cette structure :
{{
  "score": 75,
  "recommendation": "recommended",
  "explanation": "explication en 2-3 phrases justifiant le score",
  "matched_skills": ["compétence1", "compétence2"],
  "missing_skills": ["compétence3"]
}}

Règles :
- "score" est un entier de 0 à 100 représentant le pourcentage de correspondance globale.
- "recommendation" doit être une de ces valeurs exactes : "highly_recommended" (score >= 80), "recommended" (score 60-79), "neutral" (score 40-59), "not_recommended" (score < 40).
- Prends en compte les compétences équivalentes ou proches (ex: Django compte comme du Python), pas seulement les correspondances exactes de mots.
- Prends en compte l'expérience et le niveau d'études si pertinents.

RÈGLE DE FORMAT JSON CRITIQUE : n'utilise JAMAIS de guillemets doubles (")
à l'intérieur du texte des valeurs (explication, compétences...). Pour citer
un terme, utilise des guillemets simples (') ou des guillemets français
(« »), jamais de guillemets doubles droits, car cela casserait le JSON.

--- OFFRE D'EMPLOI ---
Titre : {job_title}
Compétences requises : {required_skills}
Expérience requise : {required_experience} ans
Niveau d'études requis : {required_education}

--- PROFIL CANDIDAT ---
Résumé : {candidate_summary}
Compétences : {candidate_skills}
Expériences : {candidate_experience}
Diplômes : {candidate_education}
"""


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    ai_matched_skills = fields.Text(string="Compétences correspondantes")
    ai_missing_skills = fields.Text(string="Compétences manquantes")
    ai_score_explanation = fields.Text(string="Justification du score")

    def action_compute_match_score(self):
        for applicant in self:
            if not applicant.ai_summary:
                raise UserError("Lance d'abord l'extraction IA du CV (étape 3) avant le scoring.")
            if not applicant.job_id:
                raise UserError("Ce candidat n'est associé à aucune offre d'emploi.")

            try:
                result = applicant._call_gemini_scoring()
                applicant._apply_scoring_result(result)
            except Exception as e:
                _logger.error("Erreur scoring pour %s: %s", applicant.partner_name, e)
                raise UserError(f"Erreur lors du scoring IA : {e}")

    def _call_gemini_scoring(self):
        self.ensure_one()
        job = self.job_id

        prompt = SCORING_PROMPT.format(
            job_title=job.name or "",
            required_skills=job.required_skills or "Non spécifié",
            required_experience=job.required_experience_years or 0,
            required_education=job.required_education_level or "Non spécifié",
            candidate_summary=self.ai_summary or "",
            candidate_skills=self.extracted_skills or "Non renseigné",
            candidate_experience=self.extracted_experience or "Non renseigné",
            candidate_education=self.extracted_education or "Non renseigné",
        )

        return self._call_gemini_json(prompt)

    def _apply_scoring_result(self, result):
        self.ensure_one()

        def _format_list(items):
            return "\n".join(f"- {item}" for item in items) if items else ""

        self.write({
            'ai_score': result.get('score', 0),
            'ai_recommendation': result.get('recommendation', 'neutral'),
            'ai_score_explanation': result.get('explanation', ''),
            'ai_matched_skills': _format_list(result.get('matched_skills', [])),
            'ai_missing_skills': _format_list(result.get('missing_skills', [])),
        })