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
    is_refusal_stage = fields.Boolean(
        string="Étape de refus",
        help="Coche cette case sur l'étape 'Refusé' (ou équivalent) du pipeline. "
             "Quand un candidat est refusé via l'assistant de refus, il est "
             "déplacé automatiquement vers cette étape plutôt que simplement "
             "archivé, pour garder une trace visible dans le pipeline ATS. "
             "Si aucune étape n'est marquée ainsi, le candidat est archivé "
             "(comportement standard Odoo).",
    )
    is_contract_signed_stage = fields.Boolean(
        string="Étape de contrat signé",
        help="Coche cette case sur l'étape représentant un contrat réellement "
             "signé (ex: 'Contrat signé'). Dès qu'un candidat atteint cette "
             "étape, le module crée automatiquement son employé (si pas déjà "
             "fait), génère le contrat, et le fait passer à l'état 'En cours' "
             "— ce qui déclenche aussi l'email d'acceptation au candidat. "
             "Ne coche cette case que sur une étape que le recruteur ne "
             "déplace un candidat vers elle qu'une fois le contrat réellement "
             "signé côté RH : cette automatisation est irréversible en un "
             "clic (création employé + validation contrat)."
    )