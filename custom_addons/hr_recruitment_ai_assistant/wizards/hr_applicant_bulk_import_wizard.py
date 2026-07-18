# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrApplicantBulkImportWizard(models.TransientModel):
    _name = 'hr.applicant.bulk.import.wizard'
    _description = "Import automatique de plusieurs CV"

    job_id = fields.Many2one(
        'hr.job', string="Poste concerné", required=True,
        help="Tous les CV importés seront créés comme candidatures sur ce poste."
    )
    cv_attachment_ids = fields.Many2many(
        'ir.attachment', string="Fichiers CV (PDF/DOCX)",
        help="Sélectionne plusieurs fichiers en une fois. Un candidat sera "
             "créé automatiquement pour chaque fichier."
    )
    run_pipeline_automatically = fields.Boolean(
        string="Lancer l'analyse IA automatiquement après import",
        default=True,
        help="Si coché : extraction du CV, analyse IA, scoring et questions "
             "d'entretien sont enchaînés automatiquement pour chaque candidat "
             "créé (comme le bouton 'Pipeline IA complet', mais en masse)."
    )

    def action_import(self):
        self.ensure_one()
        if not self.cv_attachment_ids:
            raise UserError("Sélectionne au moins un fichier CV à importer.")

        invalid = self.cv_attachment_ids.filtered(
            lambda a: not a.name.lower().endswith(('.pdf', '.docx'))
        )
        if invalid:
            raise UserError(
                "Ces fichiers ne sont ni des PDF ni des DOCX, retire-les avant "
                f"d'importer : {', '.join(invalid.mapped('name'))}"
            )

        created = self.env['hr.applicant']
        pipeline_ok, pipeline_failed = [], []

        for attachment in self.cv_attachment_ids:
            # Nom de candidat provisoire à partir du nom de fichier
            # (ex: "jean_dupont_cv.pdf" -> "Jean Dupont Cv") ; l'analyse IA
            # remplira ensuite le vrai profil (résumé, compétences...), mais
            # 'Sujet / Candidature' doit être rempli dès la création.
            base_name = attachment.name.rsplit('.', 1)[0].replace('_', ' ').replace('-', ' ')
            display_name = base_name.title()

            applicant = self.env['hr.applicant'].create({
                'name': f"{self.job_id.name} - {display_name}",
                'partner_name': display_name,
                'job_id': self.job_id.id,
            })
            attachment.copy({'res_model': 'hr.applicant', 'res_id': applicant.id})
            created |= applicant

            if self.run_pipeline_automatically:
                try:
                    applicant.action_run_full_ai_pipeline()
                    pipeline_ok.append(display_name)
                except UserError as e:
                    # On continue l'import des autres CV même si l'un d'eux
                    # échoue à l'analyse IA : le candidat existe quand même,
                    # juste sans analyse (il pourra être relancé manuellement).
                    _logger.warning(
                        "Pipeline IA échoué pour %s (import en masse) : %s",
                        display_name, e,
                    )
                    pipeline_failed.append(display_name)

        message_parts = [f"{len(created)} candidat(s) créé(s) sur '{self.job_id.name}'."]
        if self.run_pipeline_automatically:
            message_parts.append(f"Analyse IA réussie : {len(pipeline_ok)}.")
            if pipeline_failed:
                message_parts.append(
                    f"Analyse IA échouée pour : {', '.join(pipeline_failed)} "
                    "(à relancer manuellement sur chaque fiche)."
                )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Import terminé",
                'message': " ".join(message_parts),
                'type': 'warning' if pipeline_failed else 'success',
                'sticky': bool(pipeline_failed),
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': "Candidats importés",
                    'res_model': 'hr.applicant',
                    'view_mode': 'tree,form',
                    'views': [(False, 'tree'), (False, 'form')],
                    'domain': [('id', 'in', created.ids)],
                    'target': 'current',
                },
            },
        }