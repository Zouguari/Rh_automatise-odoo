# -*- coding: utf-8 -*-
from odoo import fields, models


class HrJobSkill(models.Model):
    _name = 'hr.job.skill'
    _description = "Compétence requise pour un poste"
    _order = 'job_id, skill_id'

    job_id = fields.Many2one('hr.job', string="Poste", required=True, ondelete='cascade', index=True)
    skill_id = fields.Many2one('hr.skill', string="Compétence", required=True, ondelete='cascade')
    skill_type_id = fields.Many2one(
        'hr.skill.type', string="Type de compétence",
        related='skill_id.skill_type_id', store=True, readonly=True,
    )
    required_level_id = fields.Many2one(
        'hr.skill.level', string="Niveau requis", required=True,
        domain="[('skill_type_id', '=', skill_type_id)]",
    )

    _sql_constraints = [
        ('job_skill_uniq', 'unique(job_id, skill_id)',
         "Une compétence ne peut être requise qu'une seule fois par poste."),
    ]
