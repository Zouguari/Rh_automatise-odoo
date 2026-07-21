# -*- coding: utf-8 -*-

import base64
import io
import json
import logging
import re
import requests
import time
import pdfplumber
from docx import Document as DocxDocument
from datetime import timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


class GeminiRetryableError(UserError):
    """Erreur Gemini pour laquelle relancer la génération a une vraie chance
    d'aboutir à un résultat différent (JSON mal formé, réponse vide...).
    À ne pas confondre avec UserError "classique" (clé API manquante, HTTP
    définitivement en échec, tokens dépassés) qui elle ne doit JAMAIS être
    retentée automatiquement : réessayer produirait le même échec, en pire
    (temps perdu, messages trompeurs)."""
    pass

EXTRACTION_PROMPT = """Tu es un assistant RH spécialisé dans l'analyse de CV.
Analyse le texte de CV suivant et réponds UNIQUEMENT avec un objet JSON valide, sans aucun texte avant ou après, sans balises markdown.

RÈGLE CRITIQUE : Tu dois extraire TOUTES les entrées présentes dans le CV, sans exception.
Ne résume pas, ne sélectionne pas les "plus importantes", ne fusionne pas plusieurs expériences en une seule.
Si le CV contient 6 expériences professionnelles, ta liste "experience" doit contenir exactement 6 éléments.
Si le CV contient 10 compétences listées, ta liste "skills" doit contenir exactement 10 éléments.

Le JSON doit avoir exactement cette structure :
{
  "summary": "résumé du profil en 2-3 phrases",
  "skills": ["compétence1", "compétence2"],
  "education": ["diplôme - établissement - année"],
  "education_level_normalized": "bac_5",
  "experience": ["poste - entreprise - période - description courte"],
  "languages": ["langue (niveau)"],
  "certifications": ["certification1"]
}

"education_level_normalized" doit être EXACTEMENT une de ces valeurs :
"bac", "bac_2", "bac_3", "bac_5", "doctorat", "autre".
Déduis cette valeur à partir du diplôme le PLUS ÉLEVÉ trouvé dans le CV, en
tenant compte des équivalences du système éducatif marocain (fréquent dans
les CV traités par ce module) :
- "bac" : Baccalauréat marocain (toutes filières)
- "bac_2" : DEUG, DEUST, DUT, Technicien Spécialisé (OFPPT/ISTA), BTS
- "bac_3" : Licence, Licence Professionnelle, Licence Fondamentale
- "bac_5" : Master, Master Spécialisé, Diplôme d'Ingénieur d'État (grandes
  écoles marocaines : EMI, ENSA, ENSAM, ENSIAS, INPT, EHTP, ENCG, ISCAE,
  FST, Al Akhawayn, UM6P...), MBA
- "doctorat" : Doctorat, PhD
- "autre" : diplôme non identifiable ou absent du CV
Reconnais aussi les entreprises marocaines courantes (OCP Group, Maroc
Telecom/IAM, Attijariwafa Bank, BMCE Bank of Africa, Bank Al-Maghrib, Royal
Air Maroc, ONCF, ONEE, Marjane, Label Vie, Managem, CIH Bank, Wafa
Assurance, Saham, LafargeHolcim Maroc, Renault Tanger, Stellantis Kenitra...)
et transcris leur nom exact dans "experience", sans les tronquer ni les
traduire.

Si une section est absente du CV, renvoie une liste vide pour cette clé.
Ne traduis pas le contenu, garde la langue d'origine du CV.

RÈGLE DE FORMAT JSON CRITIQUE : n'utilise JAMAIS de guillemets doubles (")
à l'intérieur du texte des valeurs (résumé, compétences, descriptions...).
Si tu dois citer un terme ou un nom de technologie entre guillemets,
utilise des guillemets simples (') ou des guillemets français (« »), jamais
de guillemets doubles droits, car cela casserait la structure du JSON.

Voici le texte du CV :
---
{cv_text}
---
"""


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    interview_event_id = fields.Many2one(
        'calendar.event',
        string="Entretien planifié"
    )
    ai_interview_questions = fields.Text(
        string="Questions d'entretien générées"
    )

    onboarding_task_ids = fields.One2many(
        'project.task', 'applicant_origin_id',
        string="Tâches d'onboarding"
    )
    generated_contract_id = fields.Many2one(
        'hr.contract', string="Contrat généré"
    )

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
    extracted_education_level = fields.Selection([
        ('bac', 'Bac'),
        ('bac_2', 'Bac+2 (DEUG/DEUST/DUT/Technicien Spécialisé)'),
        ('bac_3', 'Bac+3 (Licence/Licence Professionnelle)'),
        ('bac_5', 'Bac+5 et plus (Master/Diplôme d\'Ingénieur d\'État)'),
        ('doctorat', 'Doctorat'),
        ('autre', 'Autre / Non déterminé'),
    ], string="Niveau d'études (normalisé)",
        help="Niveau standardisé déduit par l'IA à partir des diplômes extraits, "
             "en tenant compte des équivalences du système éducatif marocain "
             "(ex: Diplôme d'Ingénieur d'État = Bac+5).")
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

    def action_run_full_ai_pipeline(self):
        """Enchaîne automatiquement les 4 étapes de l'analyse IA d'un candidat :
        extraction du texte du CV, analyse IA structurée, calcul du score de
        matching (si un poste est associé), génération des questions d'entretien.
        S'arrête à la première étape qui échoue et indique clairement où."""
        for applicant in self:
            steps_done = []
            try:
                applicant.action_extract_cv_text()
                if applicant.cv_extraction_state != 'extracted':
                    raise UserError(
                        "Aucun CV valide n'a pu être extrait (pas de fichier PDF/DOCX "
                        "attaché, ou échec d'extraction). Pipeline arrêté ici."
                    )
                steps_done.append("Extraction du texte du CV")

                applicant.action_ai_extract_structured_data()
                steps_done.append("Analyse IA du profil")

                if applicant.job_id:
                    applicant.action_compute_match_score()
                    steps_done.append("Calcul du score de matching")
                else:
                    _logger.info(
                        "Pipeline IA : scoring ignoré pour %s (aucune offre associée)",
                        applicant.partner_name,
                    )

                applicant.action_generate_interview_questions()
                steps_done.append("Génération des questions d'entretien")

            except UserError as e:
                raise UserError(
                    f"Pipeline IA interrompu pour {applicant.partner_name or applicant.id}.\n"
                    f"Étapes réussies : {', '.join(steps_done) if steps_done else 'aucune'}.\n\n"
                    f"Erreur rencontrée : {e}"
                )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Pipeline IA terminé",
                'message': (
                    "Toutes les étapes ont été exécutées avec succès pour : "
                    f"{', '.join(self.mapped('partner_name'))}."
                ),
                'type': 'success',
                'sticky': False,
                # Recharge automatiquement la fiche après la notification,
                # sinon les champs (score, questions, résumé...) restent
                # affichés avec leur ancienne valeur jusqu'à un rafraîchissement manuel.
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_reset_ai_processing(self):
        """Permet de relancer le traitement IA manuellement depuis la vue."""
        self.write({'ai_processing_state': 'pending'})

    def action_extract_cv_text(self):
        """Extrait le texte brut du CV attaché (PDF ou DOCX)."""
        for applicant in self:
            attachment = applicant._get_cv_attachment()
            if not attachment:
                applicant.cv_extraction_state = 'none'
                raise UserError(
                    "Aucun CV (PDF ou DOCX) n'est attaché à ce candidat.\n"
                    "Ajoute le fichier via les pièces jointes (chatter) avant de "
                    "lancer l'extraction."
                )

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
                page_text = page.extract_text(layout=True, x_tolerance=2)
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
                applicant.action_extract_cv_text()

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
        prompt = EXTRACTION_PROMPT.replace("{cv_text}", cv_text)
        return self._call_gemini_json(prompt)

    def _post_gemini_with_retry(self, api_key, payload, max_retries=3):
        """Appelle l'API Gemini avec retry automatique, mais UNIQUEMENT sur
        des erreurs réellement temporaires : problème réseau, 503 (surchargé),
        429 (quota momentané). Les autres erreurs HTTP (401/403 clé invalide,
        404 modèle introuvable, 400 requête malformée...) sont définitives :
        retenter donnerait exactement le même résultat, donc on remonte
        l'erreur immédiatement au lieu de faire perdre du temps."""
        last_error = None
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{GEMINI_URL}?key={api_key}",
                    json=payload,
                    timeout=60,
                )
            except requests.exceptions.RequestException as e:
                # Erreur réseau (timeout, DNS, connexion coupée...) : ça, c'est
                # bien temporaire, on retente.
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise UserError(
                    f"Impossible de contacter l'API Gemini après {max_retries} "
                    f"tentatives (problème réseau).\nDétail technique : {last_error}"
                )

            if response.status_code in (503, 429):
                last_error = f"HTTP {response.status_code} : {response.text[:200]}"
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    _logger.warning(
                        "Gemini indisponible (%s), nouvelle tentative dans %ss (essai %s/%s)",
                        response.status_code, wait, attempt + 1, max_retries,
                    )
                    time.sleep(wait)
                    continue
                raise UserError(
                    f"L'API Gemini est surchargée après {max_retries} tentatives. "
                    "C'est généralement temporaire (serveurs Google surchargés) — réessaie dans "
                    f"quelques instants.\nDétail technique : {last_error}"
                )

            if not response.ok:
                # Erreur définitive (mauvaise clé, modèle inconnu, requête
                # invalide...) : inutile de retenter, on échoue tout de suite
                # avec un message clair plutôt que de faire attendre pour rien.
                raise UserError(
                    f"L'API Gemini a renvoyé une erreur {response.status_code} "
                    "(non temporaire, retenter ne changera rien).\n"
                    f"Détail : {response.text[:300]}"
                )

            return response.json()

    def _call_gemini_json(self, prompt, max_attempts=3):
        """Appel générique à Gemini qui renvoie un JSON parsé. Réutilisé par extraction et scoring.
        Si le JSON renvoyé est invalide, on relance toute la génération (pas juste le parsing)
        jusqu'à max_attempts fois : c'est souvent un aléa ponctuel du modèle qui ne se
        reproduit pas d'un essai à l'autre.
        Attention : seules les erreurs marquées GeminiRetryableError sont retentées ici.
        Les autres UserError (clé API manquante, échec HTTP définitif, tokens dépassés...)
        remontent immédiatement — les retenter ne changerait rien au résultat et ferait
        juste perdre du temps avec un message trompeur."""
        last_error = None
        for attempt in range(max_attempts):
            try:
                return self._call_gemini_json_once(prompt)
            except GeminiRetryableError as e:
                last_error = e
                if attempt < max_attempts - 1:
                    _logger.warning(
                        "JSON Gemini invalide (essai %s/%s) pour %s, nouvelle génération : %s",
                        attempt + 1, max_attempts, getattr(self, 'partner_name', 'N/A'), e,
                    )
        raise last_error

    def _call_gemini_json_once(self, prompt):
        api_key = self.env['ir.config_parameter'].sudo().get_param('smart_hr_ai.gemini_api_key')
        if not api_key:
            raise UserError("Clé API Gemini non configurée dans les paramètres système.")

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json",
                "maxOutputTokens": 8192,
                # Les modèles "thinking" (ex: gemini-flash-latest -> gemini-3.5-flash)
                # peuvent renvoyer un raisonnement interne en plus de la réponse finale.
                # On désactive ce mode : on veut juste le JSON, pas le raisonnement.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        data = self._post_gemini_with_retry(api_key, payload)

        if self and len(self) == 1 and self.id:
            self.ai_extraction_raw = json.dumps(data, ensure_ascii=False, indent=2)

        candidate = data["candidates"][0]
        finish_reason = candidate.get("finishReason")
        if finish_reason == "MAX_TOKENS":
            raise UserError(
                "La réponse de l'IA a été coupée car elle dépassait la limite de tokens "
                "(CV probablement trop long ou trop détaillé). "
                "Consulte le champ 'Debug - Réponse brute Gemini' pour voir jusqu'où elle est allée, "
                "et réessaie — si le problème persiste régulièrement, il faut augmenter encore "
                "'maxOutputTokens' dans le code ou raccourcir le prompt."
            )

        # Par sécurité (au cas où le raisonnement ne serait pas totalement désactivable
        # selon le modèle), on ignore les éventuels blocs marqués "thought": true
        # et on concatène uniquement le texte de réponse final.
        parts = candidate.get("content", {}).get("parts", [])
        text_response = "".join(
            part.get("text", "") for part in parts if not part.get("thought")
        )
        if not text_response.strip():
            raise GeminiRetryableError(
                "Gemini n'a renvoyé aucun contenu exploitable (réponse vide ou "
                "uniquement du raisonnement interne). Consulte le champ "
                "'Debug - Réponse brute Gemini' et réessaie."
            )
        return self._parse_gemini_json(text_response)

    def _parse_gemini_json(self, text_response):
        """Parse le JSON renvoyé par Gemini, avec tentative de réparation
        si la réponse est légèrement mal formée (guillemets non échappés,
        virgule finale, balises markdown résiduelles...)."""
        cleaned = text_response.strip()

        # Retire d'éventuelles balises markdown (```json ... ```)
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as first_error:
            # Tentative de réparation légère : virgules finales avant } ou ]
            repaired = re.sub(r',\s*([}\]])', r'\1', cleaned)
            try:
                result = json.loads(repaired)
                _logger.warning(
                    "Réponse Gemini réparée automatiquement (JSON initialement invalide) pour %s",
                    getattr(self, 'partner_name', 'N/A'),
                )
                return result
            except json.JSONDecodeError:
                snippet = cleaned[max(0, first_error.pos - 80):first_error.pos + 80]
                raise GeminiRetryableError(
                    "La réponse de l'IA n'est pas un JSON valide "
                    f"({first_error.msg} à la position {first_error.pos}).\n"
                    f"Extrait autour de l'erreur : ...{snippet}...\n"
                    "Consulte le champ 'Debug - Réponse brute Gemini' pour le détail complet, "
                    "puis relance l'action."
                )


    def _apply_gemini_result(self, result):
        self.ensure_one()

        def _format_list(items):
            if not items:
                return ""
            return "\n".join(f"- {item}" for item in items)

        # Sécurité : si Gemini renvoie une valeur hors de la liste autorisée
        # (faute de frappe, valeur inventée...), on retombe sur 'autre' plutôt
        # que de planter sur une écriture de champ Selection invalide.
        allowed_levels = dict(self._fields['extracted_education_level'].selection)
        education_level = result.get('education_level_normalized', 'autre')
        if education_level not in allowed_levels:
            education_level = 'autre'

        self.write({
            'ai_summary': result.get('summary', ''),
            'extracted_skills': _format_list(result.get('skills', [])),
            'extracted_education': _format_list(result.get('education', [])),
            'extracted_education_level': education_level,
            'extracted_experience': _format_list(result.get('experience', [])),
            'extracted_languages': _format_list(result.get('languages', [])),
            'extracted_certifications': _format_list(result.get('certifications', [])),
        })

    @api.onchange('job_id')
    def _onchange_job_id_assign_recruiter(self):
        """Pré-remplit automatiquement le recruteur (user_id) avec le responsable
        recrutement défini sur le poste, si aucun recruteur n'a déjà été choisi
        manuellement. L'utilisateur reste libre de le changer ensuite."""
        if self.job_id and self.job_id.user_id and not self.user_id:
            self.user_id = self.job_id.user_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('user_id') and vals.get('job_id'):
                job = self.env['hr.job'].browse(vals['job_id'])
                if job.user_id:
                    vals['user_id'] = job.user_id.id
        applicants = super(HrApplicant, self).create(vals_list)
        applicants.action_detect_duplicates()
        return applicants

    def action_open_merge_wizard(self):
        """Ouvre l'assistant de fusion, pré-rempli avec ce candidat et
        les doublons déjà détectés."""
        self.ensure_one()
        if not self.duplicate_applicant_ids:
            raise UserError(
                "Aucun doublon détecté pour ce candidat. "
                "Lance d'abord 'Vérifier doublons' si ce n'est pas déjà fait."
            )
        all_ids = self.duplicate_applicant_ids.ids + [self.id]
        return {
            'type': 'ir.actions.act_window',
            'name': "Fusionner les doublons",
            'res_model': 'hr.applicant.merge.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_applicant_ids': [(6, 0, all_ids)],
                'default_keep_applicant_id': self.id,
            },
        }

    def action_detect_duplicates(self):
        """Recherche les candidatures similaires par email, téléphone ou nom+prénom."""
        for applicant in self:
            duplicates = applicant._find_duplicate_applicants()
            applicant.write({
                'is_potential_duplicate': bool(duplicates),
                'duplicate_applicant_ids': [(6, 0, duplicates.ids)],
            })
            if duplicates:
                duplicates.write({'is_potential_duplicate': True})


    def _find_duplicate_applicants(self):
        """Retourne un recordset des candidatures potentiellement en double."""
        self.ensure_one()
        domain_base = [('id', '!=', self.id)]
        matches = self.env['hr.applicant']

        # 1. Match exact par email (le plus fiable)
        if self.email_from:
            matches |= self.env['hr.applicant'].search(
                domain_base + [('email_from', '=', self.email_from)]
            )

        # 2. Match exact par téléphone/mobile
        if self.partner_phone:
            matches |= self.env['hr.applicant'].search(
                domain_base + [('partner_phone', '=', self.partner_phone)]
            )
        if self.partner_mobile:
            matches |= self.env['hr.applicant'].search(
                domain_base + [('partner_mobile', '=', self.partner_mobile)]
            )

        # 3. Match approximatif par nom (seulement si pas de conflit d'email/téléphone)
        if self.partner_name and not matches:
            name_matches = self.env['hr.applicant'].search(
                domain_base + [('partner_name', '=ilike', self.partner_name)]
            )
            filtered_matches = self.env['hr.applicant']
            for m in name_matches:
                if self.email_from and m.email_from and self.email_from != m.email_from:
                    continue
                if self.partner_phone and m.partner_phone and self.partner_phone != m.partner_phone:
                    continue
                if self.partner_mobile and m.partner_mobile and self.partner_mobile != m.partner_mobile:
                    continue
                filtered_matches |= m
            matches |= filtered_matches

        return matches

    def write(self, vals):
        result = super().write(vals)
        if 'stage_id' in vals:
            for applicant in self:
                applicant._send_stage_automatic_email()
                applicant._handle_interview_stage()
        return result

    def _send_stage_automatic_email(self):
        self.ensure_one()
        if not self.email_from:
            return  # pas d'email connu, on ne peut pas envoyer

        template = self.stage_id.auto_email_template_id
        if template:
            template.send_mail(self.id, force_send=True)

    def _handle_interview_stage(self):
        self.ensure_one()
        if self.stage_id.is_interview_stage:
            if not self.ai_interview_questions:
                self.action_generate_interview_questions()
            if not self.interview_event_id:
                self.action_schedule_interview()

    def action_schedule_interview(self):
        """Crée un événement calendrier pour l'entretien, planifié le lendemain à 10h par défaut."""
        for applicant in self:
            if applicant.interview_event_id:
                raise UserError("Un entretien est déjà planifié pour ce candidat.")

            start = fields.Datetime.now() + timedelta(days=1)
            start = start.replace(hour=10, minute=0, second=0)
            stop = start + timedelta(hours=1)

            partners = applicant.env.user.partner_id
            attendees = [(4, partners.id)]
            if applicant.interviewer_ids:
                for interviewer in applicant.interviewer_ids:
                    attendees.append((4, interviewer.partner_id.id))

            event = self.env['calendar.event'].create({
                'name': f"Entretien - {applicant.partner_name} - {applicant.job_id.name}",
                'start': start,
                'stop': stop,
                'partner_ids': attendees,
                'description': applicant.ai_interview_questions or "",
                'res_id': applicant.id,
                'res_model_id': self.env['ir.model']._get_id('hr.applicant'),
            })

            applicant.interview_event_id = event.id

    def create_employee_from_applicant(self):
        # Appelle le comportement natif d'Odoo (crée hr.employee, lie applicant à employee_id)
        result = super(HrApplicant, self).create_employee_from_applicant()
        for applicant in self:
            if applicant.emp_id:
                applicant._generate_onboarding_contract()
                applicant._create_onboarding_tasks()
        return result

    def _generate_onboarding_contract(self):
        self.ensure_one()
        if self.generated_contract_id:
            return

        contract = self.env['hr.contract'].create({
            'name': f"Contrat - {self.emp_id.name}",
            'employee_id': self.emp_id.id,
            'job_id': self.job_id.id,
            'wage': self.salary_proposed or self.salary_expected or 0.0,
            'state': 'draft',
        })
        self.generated_contract_id = contract.id

    def _create_onboarding_tasks(self):
        self.ensure_one()

        # Cherche (ou crée) un projet dédié à l'onboarding
        onboarding_project = self.env['project.project'].search(
            [('name', '=', 'Onboarding RH')], limit=1
        )
        if not onboarding_project:
            onboarding_project = self.env['project.project'].create({
                'name': 'Onboarding RH',
            })

        task_templates = [
            "Préparer le poste de travail et le matériel",
            "Créer les accès (email, VPN, logiciels internes)",
            "Planifier la journée d'accueil",
            "Assigner un parrain/mentor",
            "Remettre le livret d'accueil et les documents RH",
            "Planifier la formation initiale",
        ]

        for title in task_templates:
            self.env['project.task'].create({
                'name': f"{title} - {self.emp_id.name}",
                'project_id': onboarding_project.id,
                'user_ids': [(4, self.emp_id.parent_id.user_id.id)] if self.emp_id.parent_id.user_id else False,
                'applicant_origin_id': self.id,
            })