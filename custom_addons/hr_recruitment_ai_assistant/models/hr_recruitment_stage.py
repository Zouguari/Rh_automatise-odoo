# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


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

    @api.constrains('is_interview_stage', 'is_refusal_stage', 'is_contract_signed_stage')
    def _check_single_automatic_role(self):
        """Empêche de cocher plusieurs rôles automatiques contradictoires sur
        la même étape (ex: une étape marquée à la fois 'Entretien' et
        'Contrat signé' déclencherait planification d'entretien ET
        signature de contrat au même moment, ce qui n'a pas de sens
        métier). Chaque étape ne doit avoir qu'un seul rôle automatique
        actif à la fois."""
        for stage in self:
            active_roles = sum([
                stage.is_interview_stage,
                stage.is_refusal_stage,
                stage.is_contract_signed_stage,
            ])
            if active_roles > 1:
                raise ValidationError(
                    f"L'étape « {stage.name} » ne peut pas cumuler plusieurs "
                    "rôles automatiques (Entretien / Refus / Contrat signé). "
                    "Choisis-en un seul par étape pour éviter des "
                    "déclenchements contradictoires (ex: envoi d'une "
                    "convocation d'entretien ET signature de contrat en "
                    "même temps)."
                )