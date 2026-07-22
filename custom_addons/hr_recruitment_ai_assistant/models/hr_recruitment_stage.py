# -*- coding: utf-8 -*-

from odoo import models, fields


class HrRecruitmentStage(models.Model):
    _inherit = 'hr.recruitment.stage'

    auto_email_template_id = fields.Many2one(
        'mail.template',
        string="Template email automatique",
        help="Email envoyé automatiquement quand un candidat atteint cette étape."
    )
    is_interview_stage = fields.Boolean(
        string="Étape d'entretien",
        help="Coche cette case si atteindre cette étape doit déclencher automatiquement "
             "la génération de questions IA et la planification d'un entretien. "
             "Remplace une ancienne logique basée sur le nom de l'étape (peu fiable "
             "si l'étape est renommée ou si Odoo est utilisé dans une autre langue)."
    )
    interview_type = fields.Selection([
        ('rh', 'Entretien RH'),
        ('technique', 'Entretien Technique'),
    ], string="Type d'entretien",
        help="Précise la nature de l'entretien pour cette étape (utilisé dans "
             "l'email de convocation envoyé au candidat, et pour adapter le "
             "contenu généré par l'IA). Laisse vide si cette étape n'est pas "
             "un entretien.")