# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

# Champs IA à récupérer automatiquement depuis un doublon archivé si la
# candidature conservée ne les a pas déjà (on ne veut jamais écraser une
# donnée déjà présente, seulement compléter ce qui manque).
_AI_FIELDS_TO_FILL = [
    'ai_score', 'ai_summary', 'ai_recommendation', 'ai_score_explanation',
    'extracted_skills', 'extracted_skills_detailed', 'extracted_education',
    'extracted_education_level', 'extracted_experience', 'extracted_languages',
    'extracted_certifications', 'cv_raw_text',
]


class HrApplicantMergeWizard(models.TransientModel):
    _name = 'hr.applicant.merge.wizard'
    _description = "Assistant de fusion de candidatures en double"

    applicant_ids = fields.Many2many(
        'hr.applicant', string="Candidatures concernées"
    )
    keep_applicant_id = fields.Many2one(
        'hr.applicant', string="Candidature à conserver", required=True,
        domain="[('id', 'in', applicant_ids)]",
        help="Les autres candidatures ci-dessus seront archivées. Leurs "
             "données IA (CV, score, résumé...) seront récupérées "
             "automatiquement si la fiche conservée n'en a pas déjà."
    )

    def action_confirm_merge(self):
        self.ensure_one()
        keep = self.keep_applicant_id
        others = self.applicant_ids - keep
        if not others:
            raise UserError("Sélectionne au moins deux candidatures pour fusionner.")

        for other in others:
            # Complète les champs IA manquants sur la fiche conservée,
            # sans jamais écraser une donnée déjà présente.
            updates = {
                fname: other[fname]
                for fname in _AI_FIELDS_TO_FILL
                if not keep[fname] and other[fname]
            }
            if updates:
                keep.write(updates)

            # Recopie la pièce jointe CV si la fiche conservée n'en a pas.
            if not keep._get_cv_attachment():
                attachment = other._get_cv_attachment()
                if attachment:
                    attachment.copy({'res_model': 'hr.applicant', 'res_id': keep.id})

            other.message_post(
                body=(
                    f"Candidature archivée : fusionnée avec la candidature "
                    f"#{keep.id} ({keep.partner_name or ''}) — doublon détecté."
                )
            )
            other.active = False

        keep.write({
            'is_potential_duplicate': False,
            'duplicate_applicant_ids': [(5, 0, 0)],
        })
        keep.message_post(
            body=(
                f"Fusion effectuée avec {len(others)} candidature(s) en double "
                f"({', '.join(others.mapped('partner_name'))}), désormais archivée(s)."
            )
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.applicant',
            'res_id': keep.id,
            'view_mode': 'form',
            'target': 'current',
        }
