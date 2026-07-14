# -*- coding: utf-8 -*-

from odoo import models, fields
from odoo.exceptions import UserError

class HrJob(models.Model):
    _inherit = 'hr.job'

    required_skills = fields.Text(
        string="Compétences requises",
        help="Liste des compétences attendues pour ce poste, une par ligne."
    )
    required_experience_years = fields.Integer(
        string="Années d'expérience requises",
        default=0
    )
    required_education_level = fields.Char(
        string="Niveau d'études requis"
    )

    def action_generate_job_description_ai(self):
        """Génère la description du poste en utilisant Gemini et remplit le champ natif d'Odoo."""
        for job in self:
            if not job.name:
                raise UserError("Le titre du poste doit être spécifié avant de générer la description.")
            
            # Rassembler les prérequis pour guider l'IA
            requirements = []
            if job.required_skills:
                requirements.append(job.required_skills)
            if job.required_experience_years:
                requirements.append(f"Expérience requise : {job.required_experience_years} ans")
            if job.required_education_level:
                requirements.append(f"Diplôme requis : {job.required_education_level}")
            
            key_skills = "\n".join(requirements) if requirements else "Non spécifiées"

            # Créer un enregistrement de génération temporaire
            generator = self.env['hr.recruitment.ai.generator'].create({
                'name': job.name,
                'key_skills': key_skills,
            })
            
            # Lancer la génération IA réelle
            generator.action_generate_description()

            # Mettre à jour la description native d'Odoo
            job.write({
                'description': generator.generated_description
            })

