# -*- coding: utf-8 -*-
from odoo import fields, models


class HrAppraisalAiAnalysis(models.Model):
    _name = 'hr.appraisal.ai.analysis'
    _description = "Historique des analyses IA d'évaluation de performance"
    _order = 'create_date desc'

    appraisal_id = fields.Many2one(
        'hr.appraisal', string="Évaluation", required=True, index=True, ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee', string="Employé", required=True, index=True, ondelete='cascade',
    )
    performance_score = fields.Float(string="Score de performance (0-100)")
    high_potential = fields.Boolean(string="Haut potentiel")
    summary = fields.Text()
