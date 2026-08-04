# -*- coding: utf-8 -*-
from odoo import fields, models


class HrTrainingCourse(models.Model):
    _name = 'hr.training.course'
    _description = "Formation recommandée par compétence"
    _order = 'name'

    name = fields.Char(required=True)
    skill_id = fields.Many2one(
        'hr.skill', string="Compétence développée", required=True,
        ondelete='cascade', index=True,
    )
    description = fields.Text()
    duration_hours = fields.Float(string="Durée (heures)")
    url = fields.Char(string="Lien / ressource")
