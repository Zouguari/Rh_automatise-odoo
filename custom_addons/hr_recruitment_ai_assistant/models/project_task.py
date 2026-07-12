# -*- coding: utf-8 -*-

from odoo import models, fields


class ProjectTask(models.Model):
    _inherit = 'project.task'

    applicant_origin_id = fields.Many2one(
        'hr.applicant', string="Candidature d'origine"
    )
