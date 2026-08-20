# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)

MOBILE_APP_DESCRIPTION = """
<p><strong>Smart HR AI</strong> est votre espace RH personnel sur mobile. Depuis
l'application, vous pouvez notamment :</p>
<ul>
    <li>Consulter votre fiche employé et vos informations de poste</li>
    <li>Soumettre et suivre vos demandes de congés</li>
    <li>Consulter vos pointages et signaler vos présences</li>
    <li>Visualiser vos compétences et les formations recommandées</li>
    <li>Accéder à vos évaluations de performance</li>
    <li>Demander et télécharger vos documents RH</li>
</ul>
"""


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    def _send_acceptance_email(self):
        """Envoie l'email de félicitations, puis les identifiants mobile."""
        super()._send_acceptance_email()
        for applicant in self:
            applicant._send_mobile_access_email()

    def _send_mobile_access_email(self):
        """Crée l'accès mobile et envoie les identifiants au nouvel employé.

        Déclenché automatiquement juste après l'email de félicitations, lorsque
        le contrat passe à l'état « En cours » (contrat signé).
        """
        self.ensure_one()

        if not self.emp_id:
            _logger.warning(
                "Accès mobile non envoyé pour %s : aucun employé rattaché.",
                self.partner_name,
            )
            return False

        if not self.email_from:
            _logger.warning(
                "Accès mobile non envoyé pour %s : aucune adresse e-mail sur la candidature.",
                self.partner_name,
            )
            return False

        employee = self.emp_id
        login = self.email_from.strip().lower()

        if not employee.work_email:
            employee.sudo().write({'work_email': login})

        try:
            _cred, temp_password = self.env['hr.employee.credentials'].sudo().provision_for_employee(
                employee, login=login,
            )
        except Exception as e:
            _logger.error(
                "Création de l'accès mobile impossible pour %s : %s",
                self.partner_name, e,
            )
            self.message_post(
                body=(
                    "⚠️ Impossible de créer automatiquement l'accès mobile : "
                    f"{e}\nÀ finaliser manuellement depuis Employés → Accès Mobile Employés."
                )
            )
            return False

        icp = self.env['ir.config_parameter'].sudo()
        app_url = icp.get_param('hr_ai_api.mobile_app_url', '').strip()
        app_name = icp.get_param('hr_ai_api.mobile_app_name', 'Smart HR AI').strip() or 'Smart HR AI'

        job_name = self.job_id.name if self.job_id else "notre entreprise"
        subject = f"Bienvenue sur {app_name} — Vos identifiants d'accès mobile"

        app_link_block = (
            f'<p><strong>Lien de l\'application :</strong> '
            f'<a href="{app_url}">{app_url}</a></p>'
            if app_url else
            '<p><em>Le lien de téléchargement de l\'application vous sera '
            'communiqué prochainement par votre service RH.</em></p>'
        )

        body_html = f"""
            <p>Bonjour {self.partner_name or ''},</p>
            <p>Félicitations encore pour votre intégration
            {"au poste de " + job_name if self.job_id else ""} !
            Votre contrat est validé — voici vos identifiants pour accéder à
            l'application mobile <strong>{app_name}</strong>.</p>
            {MOBILE_APP_DESCRIPTION}
            {app_link_block}
            <p><strong>Vos identifiants de première connexion :</strong></p>
            <ul>
                <li><strong>Identifiant :</strong> {login}</li>
                <li><strong>Mot de passe temporaire :</strong> {temp_password}</li>
            </ul>
            <p><strong>Important :</strong> lors de votre première connexion,
            l'application vous demandera de <strong>choisir un nouveau mot de
            passe</strong> personnel. Conservez ce message jusqu'à ce que vous
            l'ayez changé.</p>
            <p>En cas de difficulté, contactez votre service RH.</p>
            <p>Cordialement,<br/>L'équipe RH</p>
        """

        sent = self._send_email_safely(
            subject=subject,
            body_html=body_html,
            log_success=(
                f"Email d'accès mobile envoyé au candidat (identifiant : {login})."
            ),
            log_failure_prefix="Échec de l'envoi de l'email d'accès mobile",
        )

        if sent:
            employee.message_post(
                body=(
                    "📱 Accès mobile Smart HR AI créé automatiquement "
                    f"(identifiant : {login}). Les identifiants temporaires "
                    "ont été envoyés par e-mail au collaborateur."
                ),
                subject="Accès mobile créé",
            )

        return sent
