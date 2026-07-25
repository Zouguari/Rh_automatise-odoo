# -*- coding: utf-8 -*-

import logging
from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

INTERVIEW_QUESTIONS_PROMPT_RH = """Tu es un recruteur RH expert. Génère une liste de questions pour un
ENTRETIEN RH (pas technique) — motivation, adéquation au poste et à l'entreprise,
parcours, soft skills, disponibilité — pour ce candidat, en te basant sur son profil
et le poste visé.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, sans markdown :
{{
  "questions": [
    "question 1",
    "question 2"
  ]
}}

Génère exactement 8 questions réparties ainsi :
- 2 questions sur la motivation et l'intérêt pour ce poste précis / cette entreprise
- 2 questions sur le parcours et les transitions de carrière du candidat
- 2 questions comportementales (gestion de conflit, travail d'équipe, autonomie...)
- 2 questions pratiques (disponibilité, prétentions salariales, mobilité, préavis)

Ne pose AUCUNE question technique pointue (langages, outils, algorithmes...) —
celles-ci seront couvertes lors d'un entretien technique séparé.

RÈGLE DE FORMAT JSON CRITIQUE : n'utilise JAMAIS de guillemets doubles (")
à l'intérieur du texte des questions, même pour citer un mot ou une
technologie. Utilise des guillemets simples (') ou des guillemets français
(« ») si nécessaire, jamais de guillemets doubles droits, car cela
casserait la structure du JSON.

--- OFFRE D'EMPLOI ---
Titre : {job_title}
Compétences requises : {required_skills}

--- PROFIL CANDIDAT ---
Résumé : {candidate_summary}
Compétences : {candidate_skills}
Expériences : {candidate_experience}
Compétences manquantes identifiées : {missing_skills}
"""

INTERVIEW_QUESTIONS_PROMPT_TECHNIQUE = """Tu es un recruteur technique expert (senior dans le domaine du poste).
Génère une liste de questions pour un ENTRETIEN TECHNIQUE — évaluation réelle des
compétences techniques et de la capacité à résoudre des problèmes — pour ce candidat,
en te basant sur son profil et le poste visé.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, sans markdown :
{{
  "questions": [
    "question 1",
    "question 2"
  ]
}}

Génère exactement 8 questions réparties ainsi :
- 3 questions techniques précises liées aux compétences déclarées du candidat
  (vérifier la profondeur réelle de sa maîtrise, pas juste la présence du mot-clé)
- 2 questions de mise en situation / résolution de problème concret liées au poste
- 2 questions ciblant spécifiquement les compétences manquantes ou faibles identifiées
- 1 question sur un projet technique concret tiré de son expérience (architecture,
  choix techniques, difficultés rencontrées)

Ne pose PAS de questions de motivation ou comportementales génériques — celles-ci
sont couvertes lors de l'entretien RH séparé.

RÈGLE DE FORMAT JSON CRITIQUE : n'utilise JAMAIS de guillemets doubles (")
à l'intérieur du texte des questions, même pour citer un mot ou une
technologie. Utilise des guillemets simples (') ou des guillemets français
(« ») si nécessaire, jamais de guillemets doubles droits, car cela
casserait la structure du JSON.

--- OFFRE D'EMPLOI ---
Titre : {job_title}
Compétences requises : {required_skills}

--- PROFIL CANDIDAT ---
Résumé : {candidate_summary}
Compétences : {candidate_skills}
Expériences : {candidate_experience}
Compétences manquantes identifiées : {missing_skills}
"""

# Prompt de repli : utilisé uniquement si les questions sont générées hors
# d'une étape d'entretien typée (interview_type vide) — ex: appel manuel de
# l'action avant tout passage en étape RH/Technique.
INTERVIEW_QUESTIONS_PROMPT_GENERIC = """Tu es un recruteur expert. Génère une liste de questions d'entretien pertinentes
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

RÈGLE DE FORMAT JSON CRITIQUE : n'utilise JAMAIS de guillemets doubles (")
à l'intérieur du texte des questions, même pour citer un mot ou une
technologie. Utilise des guillemets simples (') ou des guillemets français
(« ») si nécessaire, jamais de guillemets doubles droits, car cela
casserait la structure du JSON.

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
        interview_type = self.stage_id.interview_type
        if interview_type == 'rh':
            template = INTERVIEW_QUESTIONS_PROMPT_RH
        elif interview_type == 'technique':
            template = INTERVIEW_QUESTIONS_PROMPT_TECHNIQUE
        else:
            template = INTERVIEW_QUESTIONS_PROMPT_GENERIC
        return template.format(
            job_title=job.name or "",
            required_skills=job.required_skills or "Non spécifié",
            candidate_summary=self.ai_summary or "",
            candidate_skills=self.extracted_skills or "Non renseigné",
            candidate_experience=self.extracted_experience or "Non renseigné",
            missing_skills=self.ai_missing_skills or "Aucune identifiée",
        )