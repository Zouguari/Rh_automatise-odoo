# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

JOB_MATCHING_PROMPT = """Tu es un assistant de recrutement expert. Voici le
profil d'un candidat et une liste de postes actuellement ouverts dans
l'entreprise. Détermine quel poste correspond le MIEUX à ce profil.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, sans
markdown, avec exactement cette structure :
{{
  "best_job_id": 12,
  "reason": "explication en 2-3 phrases justifiant ce choix"
}}

"best_job_id" DOIT être l'un des identifiants numériques listés ci-dessous
dans "POSTES OUVERTS" — jamais un autre nombre, jamais inventé. Si vraiment
aucun poste ne correspond même approximativement, renvoie "best_job_id": null
et explique pourquoi dans "reason".

RÈGLE DE FORMAT JSON CRITIQUE : n'utilise JAMAIS de guillemets doubles (")
à l'intérieur du texte de "reason". Utilise des guillemets simples (') ou
des guillemets français (« ») si nécessaire.

--- PROFIL CANDIDAT ---
Résumé : {candidate_summary}
Compétences : {candidate_skills}
Expériences : {candidate_experience}
Niveau d'études : {candidate_education_level}

--- POSTES OUVERTS ---
{jobs_list}
"""


class HrApplicantJobMatching(models.Model):
    _inherit = 'hr.applicant'

    ai_suggested_job_id = fields.Many2one(
        'hr.job', string="Poste suggéré par l'IA",
        help="Poste jugé le plus pertinent par l'IA pour ce profil, à "
             "confirmer manuellement (jamais assigné automatiquement)."
    )
    ai_job_match_reason = fields.Text(
        string="Justification de la suggestion de poste"
    )

    def action_suggest_job(self):
        """Analyse le profil déjà extrait et suggère le poste ouvert le plus
        pertinent parmi ceux actuellement actifs, sans jamais l'assigner
        automatiquement — juste une recommandation à valider."""
        self.ensure_one()
        if not self.ai_summary:
            raise UserError(
                "Aucune analyse IA disponible pour ce candidat. Lance "
                "d'abord l'extraction/l'analyse (ou le Pipeline IA complet) "
                "avant de suggérer un poste."
            )

        open_jobs = self.env['hr.job'].search([('active', '=', True)])
        if self.job_id:
            open_jobs -= self.job_id
        if not open_jobs:
            raise UserError("Aucun autre poste ouvert disponible pour comparaison.")

        jobs_list = "\n".join(
            f"- id={job.id} | {job.name} | Compétences : "
            f"{job.required_skills or 'non spécifié'} | Expérience : "
            f"{job.required_experience_years or 0} ans | Niveau : "
            f"{job.required_education_level or 'non spécifié'}"
            for job in open_jobs
        )

        education_level_label = dict(
            self._fields['extracted_education_level'].selection
        ).get(self.extracted_education_level, "Non déterminé")

        prompt = JOB_MATCHING_PROMPT.format(
            candidate_summary=self.ai_summary or "",
            candidate_skills=self.extracted_skills or "Non renseigné",
            candidate_experience=self.extracted_experience or "Non renseigné",
            candidate_education_level=education_level_label,
            jobs_list=jobs_list,
        )

        result = self._call_gemini_json(prompt)
        best_job_id = result.get('best_job_id')
        reason = result.get('reason', '')

        # Sécurité : on ne fait JAMAIS confiance aveuglément à l'ID renvoyé
        # par l'IA. S'il ne correspond à aucun poste de la liste proposée,
        # on refuse plutôt que de risquer une suggestion incohérente.
        if best_job_id is not None and best_job_id not in open_jobs.ids:
            _logger.warning(
                "L'IA a suggéré un job_id (%s) hors de la liste proposée pour %s",
                best_job_id, self.partner_name,
            )
            raise UserError(
                "L'IA a renvoyé une suggestion incohérente (poste hors liste). "
                "Réessaie, ou assigne un poste manuellement."
            )

        self.write({
            'ai_suggested_job_id': best_job_id or False,
            'ai_job_match_reason': reason,
        })

        if not best_job_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': "Aucun poste correspondant",
                    'message': reason or "Aucun poste ouvert ne correspond à ce profil.",
                    'type': 'warning',
                    'sticky': True,
                },
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Poste suggéré",
                'message': f"L'IA suggère : {self.ai_suggested_job_id.name}. "
                           "Vérifie la justification puis confirme avec le "
                           "bouton 'Assigner ce poste' si tu es d'accord.",
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_assign_suggested_job(self):
        """Applique la suggestion de poste après validation humaine."""
        self.ensure_one()
        if not self.ai_suggested_job_id:
            raise UserError("Aucun poste suggéré à assigner.")
        self.write({
            'job_id': self.ai_suggested_job_id.id,
            'ai_suggested_job_id': False,
            'ai_job_match_reason': False,
        })
        self.message_post(
            body=f"Poste assigné suite à une suggestion IA : {self.job_id.name}."
        )
