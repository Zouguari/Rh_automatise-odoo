# -*- coding: utf-8 -*-
from odoo import models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def get_skill_gap_analysis(self, target_job_id=None):
        """Compare les compétences actuelles de l'employé à celles requises
        par un poste (son poste actuel par défaut, ou un poste cible donné),
        et renvoie lacunes + niveaux insuffisants + formations recommandées.

        Renvoie un dict Python (pas un champ stocké : le résultat dépend du
        poste choisi, donc calculé à la demande plutôt que persisté).

        NOTE : suppose que hr.employee.employee_skill_ids et
        hr.skill.level.level_progress existent tels quels dans votre version
        d'Odoo 17 (module hr_skills standard) — à vérifier si l'analyse
        renvoie des résultats vides de façon inattendue, comme pour
        d'autres champs déjà rencontrés sur ce projet."""
        self.ensure_one()
        job = self.env['hr.job'].browse(target_job_id) if target_job_id else self.job_id

        if not job:
            return {
                'employee_id': self.id,
                'job_id': None,
                'job_name': None,
                'missing_skills': [],
                'underleveled_skills': [],
                'matched_skills': [],
                'recommended_courses': [],
            }

        required = self.env['hr.job.skill'].sudo().search([('job_id', '=', job.id)])
        current_by_skill = {s.skill_id.id: s for s in getattr(self, 'employee_skill_ids', [])}

        extracted_text = (
            (getattr(self, 'ai_extracted_skills', '') or '') + " " +
            (getattr(self, 'ai_extracted_technologies', '') or '')
        ).lower()

        missing = []
        underleveled = []
        matched = []

        for req in required:
            current = current_by_skill.get(req.skill_id.id)
            if current:
                if current.skill_level_id.level_progress < req.required_level_id.level_progress:
                    underleveled.append({
                        'skill': req.skill_id.name,
                        'current_level': current.skill_level_id.name,
                        'required_level': req.required_level_id.name,
                    })
                else:
                    matched.append(req.skill_id.name)
            elif req.skill_id.name and req.skill_id.name.lower() in extracted_text:
                matched.append(req.skill_id.name)
            else:
                missing.append(req.skill_id.name)

        gap_skill_names = missing + [u['skill'] for u in underleveled]
        courses = self.env['hr.training.course'].sudo().search([
            ('skill_id.name', 'in', gap_skill_names),
        ]) if gap_skill_names else self.env['hr.training.course']

        return {
            'employee_id': self.id,
            'job_id': job.id,
            'job_name': job.name,
            'missing_skills': missing,
            'underleveled_skills': underleveled,
            'matched_skills': matched,
            'recommended_courses': [{
                'id': c.id,
                'name': c.name,
                'skill': c.skill_id.name,
                'duration_hours': c.duration_hours,
                'url': c.url,
            } for c in courses],
        }

    def get_career_path(self, target_job_id):
        """Suggestion de parcours de développement vers un poste cible :
        liste des compétences à acquérir ou renforcer, avec les formations
        associées quand elles existent au catalogue."""
        self.ensure_one()
        analysis = self.get_skill_gap_analysis(target_job_id=target_job_id)

        steps = [
            {'skill': s, 'action': "À acquérir (compétence non détenue)"}
            for s in analysis['missing_skills']
        ]
        steps += [
            {
                'skill': u['skill'],
                'action': "À renforcer : %s -> %s" % (u['current_level'], u['required_level']),
            }
            for u in analysis['underleveled_skills']
        ]

        return {
            'employee_id': self.id,
            'target_job_id': target_job_id,
            'target_job_name': analysis['job_name'],
            'steps': steps,
            'recommended_courses': analysis['recommended_courses'],
        }
