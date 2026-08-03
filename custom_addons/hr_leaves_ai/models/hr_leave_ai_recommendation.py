# -*- coding: utf-8 -*-
from odoo import fields, models


class HrLeaveAiRecommendation(models.Model):
    _name = 'hr.leave.ai.recommendation'
    _description = "Historique des recommandations IA sur les demandes de congés"
    _order = 'create_date desc'

    leave_id = fields.Many2one(
        'hr.leave', string="Demande de congé", required=True,
        ondelete='cascade', index=True,
    )
    recommendation = fields.Selection(
        [
            ('approve', "Approuver"),
            ('caution', "Vigilance"),
            ('refuse', "Refuser"),
        ],
        required=True,
    )
    justification = fields.Text()
    conflict_count = fields.Integer()
