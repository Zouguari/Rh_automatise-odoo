# -*- coding: utf-8 -*-

import base64
import io
import json
import logging
import requests
import pdfplumber
from docx import Document as DocxDocument
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

EXTRACTION_PROMPT = """Tu es un assistant RH spécialisé dans l'analyse de CV.
Analyse le texte de CV suivant et réponds UNIQUEMENT avec un objet JSON valide, sans aucun texte avant ou après, sans balises markdown.

Le JSON doit avoir exactement cette structure :
{
  "summary": "résumé du profil en 2-3 phrases",
  "skills": ["compétence1", "compétence2"],
  "education": ["diplôme - établissement - année"],
  "experience": ["poste - entreprise - période - description courte"],
  "languages": ["langue (niveau)"],
  "certifications": ["certification1"]
}

Si une section est absente du CV, renvoie une liste vide pour cette clé.
Ne traduis pas le contenu, garde la langue d'origine du CV.

Voici le texte du CV :
---
{cv_text}
---
"""


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

    # --- Étape 3 : intégration Gemini ---
    ai_extraction_raw = fields.Text(string="Réponse brute Gemini (debug)")

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

    def action_ai_extract_structured_data(self):
        """Appelle Gemini pour extraire les données structurées du CV."""
        for applicant in self:
            if not applicant.cv_raw_text:
                raise UserError("Aucun texte de CV disponible. Lance d'abord l'extraction du CV.")

            applicant.ai_processing_state = 'processing'
            try:
                result = applicant._call_gemini_extraction(applicant.cv_raw_text)
                applicant._apply_gemini_result(result)
                applicant.ai_processing_state = 'done'
            except Exception as e:
                _logger.error("Erreur extraction Gemini pour %s: %s", applicant.partner_name, e)
                applicant.ai_processing_state = 'error'
                raise UserError(f"Erreur lors de l'analyse IA : {e}")

    def _call_gemini_extraction(self, cv_text):
        api_key = self.env['ir.config_parameter'].sudo().get_param('smart_hr_ai.gemini_api_key')
        if not api_key:
            raise UserError("Clé API Gemini non configurée dans les paramètres système.")

        prompt = EXTRACTION_PROMPT.replace("{cv_text}", cv_text)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        }

        response = requests.post(
            f"{GEMINI_URL}?key={api_key}",
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        self.ai_extraction_raw = json.dumps(data, ensure_ascii=False, indent=2)

        text_response = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text_response)

    def _apply_gemini_result(self, result):
        self.ensure_one()

        def _format_list(items):
            if not items:
                return ""
            return "\n".join(f"- {item}" for item in items)

        self.write({
            'ai_summary': result.get('summary', ''),
            'extracted_skills': _format_list(result.get('skills', [])),
            'extracted_education': _format_list(result.get('education', [])),
            'extracted_experience': _format_list(result.get('experience', [])),
            'extracted_languages': _format_list(result.get('languages', [])),
            'extracted_certifications': _format_list(result.get('certifications', [])),
        })


