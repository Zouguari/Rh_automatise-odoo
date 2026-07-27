# -*- coding: utf-8 -*-

from odoo import models, fields


class HrApplicantInterview(models.Model):
    """Historique des entretiens planifiés pour un candidat. Séparé de
    hr.applicant (qui ne garde que interview_event_id / ai_interview_questions
    comme pointeurs vers le DERNIER entretien planifié, pour compatibilité
    avec le code existant) afin de garder une trace distincte de chaque
    entretien du pipeline (RH, Technique, ...), au lieu que le second
    entretien planifié écrase les informations du premier."""
    _name = 'hr.applicant.interview'
    _description = "Historique des entretiens candidat"
    _order = 'create_date asc'

    applicant_id = fields.Many2one(
        'hr.applicant', string="Candidat", required=True, ondelete='cascade'
    )
    stage_id = fields.Many2one(
        'hr.recruitment.stage', string="Étape"
    )
    interview_type = fields.Selection(
        related='stage_id.interview_type', store=True,
        string="Type d'entretien"
    )
    name = fields.Char(
        string="Titre", compute='_compute_name', store=True
    )
    calendar_event_id = fields.Many2one(
        'calendar.event', string="Événement calendrier"
    )
    questions = fields.Text(string="Questions générées")

    def _compute_name(self):
        for record in self:
            type_label = dict(
                record._fields['interview_type'].selection
            ).get(record.interview_type, "Entretien")
            record.name = f"{type_label} — {record.applicant_id.partner_name or ''}"