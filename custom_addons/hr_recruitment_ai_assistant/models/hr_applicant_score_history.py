# -*- coding: utf-8 -*-

from odoo import models, fields


class HrApplicantScoreHistory(models.Model):
    _name = 'hr.applicant.score.history'
    _description = "Historique des scores IA d'un candidat"
    _order = 'create_date desc'

    applicant_id = fields.Many2one(
        'hr.applicant', string="Candidat", required=True,
        ondelete='cascade', index=True
    )
    job_id = fields.Many2one(
        'hr.job', string="Poste évalué",
        help="Poste sur lequel portait ce calcul (peut différer du poste "
             "actuel du candidat si celui-ci a changé depuis)."
    )
    score = fields.Float(string="Score (%)", digits=(5, 2))
    recommendation = fields.Selection([
        ('highly_recommended', 'Fortement recommandé'),
        ('recommended', 'Recommandé'),
        ('neutral', 'Neutre'),
        ('not_recommended', 'Non recommandé'),
    ], string="Recommandation")
    explanation = fields.Text(string="Justification")
    matched_skills = fields.Text(string="Compétences correspondantes")
    missing_skills = fields.Text(string="Compétences manquantes")
    computed_by = fields.Many2one(
        'res.users', string="Calculé par", default=lambda self: self.env.user
    )
