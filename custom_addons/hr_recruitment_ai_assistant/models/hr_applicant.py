# -*- coding: utf-8 -*-

import base64
import io
import logging
import pdfplumber
from docx import Document as DocxDocument
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    # --- Champs IA / scoring ---
    ai_score = fields.Float(
        string="Score IA (%)",
        digits=(5, 2),
        help="Score de correspondance calculé automatiquement entre le CV et l'offre."
    )
    ai_summary = fields.Text(
        string="Résumé automatique du CV",
    )
    ai_recommendation = fields.Selection([
        ('highly_recommended', 'Fortement recommandé'),
        ('recommended', 'Recommandé'),
        ('neutral', 'Neutre'),
        ('not_recommended', 'Non recommandé'),
    ], string="Recommandation IA")

    # --- Données extraites du CV ---
    extracted_skills = fields.Text(string="Compétences extraites")
    extracted_education = fields.Text(string="Diplômes extraits")
    extracted_experience = fields.Text(string="Expériences extraites")
    extracted_languages = fields.Text(string="Langues extraites")
    extracted_certifications = fields.Text(string="Certifications extraites")

    # --- Statut de traitement IA ---
    ai_processing_state = fields.Selection([
        ('pending', 'En attente'),
        ('processing', 'En cours de traitement'),
        ('done', 'Traité'),
        ('error', 'Erreur'),
    ], string="Statut traitement IA", default='pending')

    # --- Doublons ---
    is_potential_duplicate = fields.Boolean(string="Doublon potentiel")
    duplicate_applicant_ids = fields.Many2many(
        'hr.applicant',
        'hr_applicant_duplicate_rel',
        'applicant_id',
        'duplicate_id',
        string="Candidatures similaires"
    )

    # --- Étape 2 : lecture du CV ---
    cv_raw_text = fields.Text(string="Texte brut extrait du CV")
    cv_extraction_state = fields.Selection([
        ('none', 'Aucun CV'),
        ('extracted', 'Texte extrait'),
        ('failed', 'Échec extraction'),
    ], string="État extraction", default='none')

    def action_reset_ai_processing(self):
        """Permet de relancer le traitement IA manuellement depuis la vue."""
        self.write({'ai_processing_state': 'pending'})

    def action_extract_cv_text(self):
        """Extrait le texte brut du CV attaché (PDF ou DOCX)."""
        for applicant in self:
            attachment = applicant._get_cv_attachment()
            if not attachment:
                applicant.cv_extraction_state = 'none'
                continue

            try:
                file_data = base64.b64decode(attachment.datas)
                text = ""

                if attachment.mimetype == 'application/pdf' or attachment.name.lower().endswith('.pdf'):
                    text = applicant._extract_text_from_pdf(file_data)
                elif attachment.name.lower().endswith('.docx'):
                    text = applicant._extract_text_from_docx(file_data)

                if text.strip():
                    applicant.cv_raw_text = text
                    applicant.cv_extraction_state = 'extracted'
                else:
                    applicant.cv_extraction_state = 'failed'

            except Exception as e:
                _logger.error("Erreur extraction CV pour %s: %s", applicant.partner_name, e)
                applicant.cv_extraction_state = 'failed'

    def _get_cv_attachment(self):
        """Récupère la première pièce jointe PDF/DOCX du candidat."""
        self.ensure_one()
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'hr.applicant'),
            ('res_id', '=', self.id),
        ], order='create_date desc')
        for att in attachments:
            if att.name.lower().endswith(('.pdf', '.docx')):
                return att
        return False

    def _extract_text_from_pdf(self, file_data):
        text = ""
        with pdfplumber.open(io.BytesIO(file_data)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        # Fallback OCR si le PDF est scanné (pas de texte natif)
        if not text.strip():
            text = self._ocr_pdf(file_data)

        return text

    def _extract_text_from_docx(self, file_data):
        doc = DocxDocument(io.BytesIO(file_data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    def _ocr_pdf(self, file_data):
        """OCR pour les CV scannés en image."""
        from pdf2image import convert_from_bytes
        import pytesseract

        text = ""
        images = convert_from_bytes(file_data)
        for image in images:
            text += pytesseract.image_to_string(image, lang='fra+eng') + "\n"
        return text

