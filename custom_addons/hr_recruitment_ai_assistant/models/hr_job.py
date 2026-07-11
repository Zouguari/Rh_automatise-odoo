# -*- coding: utf-8 -*-

from odoo import models, fields

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
