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

# Niveaux de maîtrise normalisés pour les compétences extraites du CV par
# l'IA, et pourcentage cible correspondant sur l'échelle hr.skill.level
# (level_progress, 0-100). Utilisé par hr_recruitment_ai_assistant/models/
# hr_employee.py::_pick_skill_level_for() pour choisir, parmi les niveaux
# RÉELLEMENT configurés pour un type de compétence donné, celui le plus
# proche de cette cible — plutôt que d'assigner systématiquement le niveau
# le plus bas du système à toutes les compétences (bug corrigé le 15/08/2026 :
# un employé recruté avec 5 ans d'expérience Python se retrouvait avec
# "Python - Débutant" sur sa fiche, quel que soit son niveau réel).
SKILL_LEVEL_TARGET_PROGRESS = {
    'debutant': 20,
    'intermediaire': 50,
    'avance': 75,
    'expert': 95,
}
SKILL_LEVEL_LABELS = {
    'debutant': "Débutant",
    'intermediaire': "Intermédiaire",
    'avance': "Avancé",
    'expert': "Expert",
}


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
  "skills": [
    {"name": "compétence1", "level": "avance"},
    {"name": "compétence2", "level": "debutant"}
  ],
  "education": ["diplôme - établissement - année"],
  "education_level_normalized": "bac_5",
  "experience": ["poste - entreprise - période - description courte"],
  "languages": ["langue (niveau)"],
  "certifications": ["certification1"]
}

Pour CHAQUE compétence de la liste "skills", évalue également un niveau de
maîtrise à partir des indices présents dans le CV : nombre d'années
d'expérience mentionnées avec cette compétence, mots-clés explicites
("expert", "avancé", "maîtrise", "confirmé", "senior", "notions",
"débutant", "junior"...), intitulé du poste occupé, importance et
récurrence de la compétence dans les expériences décrites.

"level" doit être EXACTEMENT une de ces 4 valeurs : "debutant",
"intermediaire", "avance", "expert". Barème indicatif :
- "debutant" : simple notion, mentionnée une fois sans contexte d'usage
  réel, ou explicitement qualifiée de basique/débutante.
- "intermediaire" : usage pratique réel mais limité (< 2 ans, ou projets
  ponctuels), ou compétence mentionnée sans indice suffisant pour un
  niveau supérieur.
- "avance" : expérience solide et répétée (environ 2 à 5 ans), ou
  responsabilités techniques significatives autour de cette compétence.
- "expert" : maîtrise clairement établie (5 ans et plus, poste
  senior/lead/architecte sur cette compétence, ou mention explicite
  "expert"/"avancé confirmé").
Si aucun indice de niveau n'est disponible pour une compétence donnée,
utilise "intermediaire" par défaut — ne mets JAMAIS "debutant" faute
d'information, ce serait sous-évaluer injustement le candidat.

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
    last_scheduled_interview_stage_id = fields.Many2one(
        'hr.recruitment.stage',
        string="Étape de la dernière convocation envoyée",
        help="Mémorise pour quelle étape (RH, Technique...) le dernier "
             "entretien a été planifié, afin de permettre une nouvelle "
             "planification/convocation à chaque nouvelle étape d'entretien "
             "plutôt que de considérer qu'un entretien déjà planifié "
             "couvre toutes les étapes suivantes."
    )
    ai_interview_questions = fields.Text(
        string="Questions d'entretien générées"
    )
    interview_ids = fields.One2many(
        'hr.applicant.interview', 'applicant_id',
        string="Historique des entretiens",
        help="Un enregistrement distinct par entretien planifié (RH, "
             "Technique...), pour garder une trace de chacun séparément — "
             "contrairement à interview_event_id / ai_interview_questions "
             "ci-dessus, qui ne pointent que vers le DERNIER entretien "
             "planifié."
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
    extracted_skills_detailed = fields.Text(
        string="Compétences extraites - détail (JSON)",
        help="Détail structuré [{'name', 'level'}] des compétences extraites du "
             "CV par l'IA, niveau normalisé inclus (voir SKILL_LEVEL_TARGET_PROGRESS). "
             "Champ technique utilisé pour peupler le profil de compétences Odoo de "
             "l'employé avec un niveau réaliste lors de l'embauche — voir "
             "hr_employee.py::_populate_employee_skills_from_ai(). Le champ "
             "'extracted_skills' ci-dessus reste le texte lisible affiché dans le formulaire."
    )
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

    @api.model
    def _cron_auto_process_new_applicants(self):
        """Traite automatiquement les nouvelles candidatures pas encore
        analysées, quel que soit leur canal d'origine (portail carrière
        web, email entrant via alias, création manuelle...).

        Volontairement découplé du moment exact de création : pour une
        candidature reçue via le portail public, le CV est parfois attaché
        JUSTE APRÈS la création de la fiche (requête HTTP séparée) — un
        déclenchement direct dans create() raterait le CV, pas encore là.
        Un cron périodique est le pattern robuste pour ce cas : il repasse
        régulièrement sur tout ce qui n'a pas encore été traité, peu
        importe quand le CV est finalement arrivé."""
        if not self.env['ir.config_parameter'].sudo().get_param(
            'smart_hr_ai.auto_run_pipeline_on_create', default='1'
        ):
            return

        candidates = self.search([('ai_processing_state', '=', 'pending')], limit=20)

        for applicant in candidates:
            if not applicant._get_cv_attachment():
                continue  # pas encore de CV attaché, on retentera au prochain passage
            try:
                applicant.action_run_full_ai_pipeline()
            except Exception as e:
                # On marque explicitement en erreur pour ne pas retenter
                # indéfiniment un CV structurellement illisible à chaque
                # passage du cron (perte de temps + de quota IA).
                _logger.warning(
                    "Traitement IA automatique échoué pour %s (candidature #%s) : %s",
                    applicant.partner_name, applicant.id, e,
                )
                applicant.ai_processing_state = 'error'
                applicant.message_post(
                    body=(
                        f"⚠️ Analyse IA automatique (candidature reçue via portail/"
                        f"email) échouée : {e}\nÀ relancer manuellement si besoin."
                    )
                )
    
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

        skills_detailed = self._normalize_extracted_skills(result.get('skills', []))
        skills_display = [
            f"{s['name']} ({SKILL_LEVEL_LABELS[s['level']]})" for s in skills_detailed
        ]

        self.write({
            'ai_summary': result.get('summary', ''),
            'extracted_skills': _format_list(skills_display),
            'extracted_skills_detailed': json.dumps(skills_detailed, ensure_ascii=False),
            'extracted_education': _format_list(result.get('education', [])),
            'extracted_education_level': education_level,
            'extracted_experience': _format_list(result.get('experience', [])),
            'extracted_languages': _format_list(result.get('languages', [])),
            'extracted_certifications': _format_list(result.get('certifications', [])),
        })

    def _normalize_extracted_skills(self, raw_skills):
        """Normalise la liste de compétences renvoyée par Gemini vers une
        liste de dicts {'name', 'level'} avec un niveau garanti parmi les
        4 valeurs de SKILL_LEVEL_TARGET_PROGRESS.

        Tolère un ancien format (liste de chaînes simples, sans niveau —
        ex: réponse générée avant ce correctif et encore en cache/debug,
        ou modèle IA qui s'écarte occasionnellement du format demandé) :
        dans ce cas, niveau 'intermediaire' par défaut, plutôt que de faire
        échouer tout le traitement de l'extraction pour un simple souci de
        format sur un sous-champ non critique."""
        normalized = []
        for item in raw_skills or []:
            if isinstance(item, dict):
                name = (item.get('name') or '').strip()
                level = (item.get('level') or '').strip().lower()
            else:
                name = str(item).strip()
                level = ''
            if not name:
                continue
            if level not in SKILL_LEVEL_TARGET_PROGRESS:
                level = 'intermediaire'
            normalized.append({'name': name, 'level': level})
        return normalized

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
                applicant._handle_contract_signed_stage()
        if vals.get('refuse_reason_id'):
            for applicant in self:
                applicant._send_refusal_email()
                applicant._move_to_refusal_stage()
        return result

    def _move_to_refusal_stage(self):
        """Déplace le candidat vers l'étape marquée is_refusal_stage (si une
        telle étape est configurée), pour garder une trace visible du refus
        dans le pipeline ATS plutôt que de le laisser simplement archivé.
        Le refus natif Odoo archive le candidat (active=False) au même
        moment que refuse_reason_id est renseigné — sans réactivation, le
        déplacement d'étape ci-dessous fonctionnerait bien en base mais
        resterait invisible dans le Kanban standard, qui masque les
        enregistrements archivés quelle que soit leur étape. Sans étape
        dédiée configurée, ne fait rien (comportement natif Odoo :
        archivage seul, candidat visible uniquement via le filtre
        "Archivé")."""
        self.ensure_one()
        refusal_stage = self.env['hr.recruitment.stage'].search(
            [('is_refusal_stage', '=', True)], limit=1
        )
        if not refusal_stage:
            return

        vals = {}
        if self.stage_id != refusal_stage:
            vals['stage_id'] = refusal_stage.id
        if not self.active:
            vals['active'] = True
        if vals:
            self.write(vals)

    def _send_email_safely(self, subject, body_html, log_success, log_failure_prefix):
        """Envoie un email et trace le résultat RÉEL dans le chatter (succès
        ou échec), au lieu de supposer que ça a marché. mail.mail.send()
        avale les erreurs par défaut (raise_exception=False) : sans ce
        wrapper, un échec d'envoi (SMTP mal configuré, adresse invalide...)
        passerait totalement inaperçu."""
        self.ensure_one()
        if not self.email_from:
            _logger.warning(
                "Email non envoyé pour %s : aucune adresse email connue.",
                self.partner_name,
            )
            return False

        mail = self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': body_html,
            'email_to': self.email_from,
            'auto_delete': True,
        })
        try:
            mail.send(raise_exception=True)
            self.message_post(body=log_success)
            return True
        except Exception as e:
            _logger.error("%s pour %s : %s", log_failure_prefix, self.partner_name, e)
            self.message_post(body=f"⚠️ {log_failure_prefix} : {e}")
            return False

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
            # Une nouvelle étape d'entretien (RH puis Technique) doit
            # regénérer ses PROPRES questions (adaptées à interview_type)
            # et sa propre convocation — pas réutiliser celles de l'étape
            # précédente. Avant ce correctif, les questions n'étaient
            # générées qu'une seule fois pour tout le pipeline via
            # "if not self.ai_interview_questions", donc l'entretien
            # Technique héritait à tort des questions RH. Même logique de
            # comparaison que pour interview_event_id (bug du 25/07/2026) :
            # un entretien déjà planifié pour une étape précédente ne
            # couvre pas les étapes suivantes.
            needs_new_interview = (
                not self.interview_event_id
                or self.last_scheduled_interview_stage_id != self.stage_id
            )
            if needs_new_interview:
                self.action_generate_interview_questions()
                self.action_schedule_interview()

    def _handle_contract_signed_stage(self):
        """Automatise la suite complète "embauche" dès que le candidat
        atteint une étape marquée is_contract_signed_stage : création de
        l'employé (si pas déjà fait), génération du contrat, puis
        validation du contrat (état 'En cours'). Cette dernière étape
        déclenche à son tour l'email d'acceptation via hr_contract.py.
        Avant cette automatisation, il fallait cliquer sur "Créer un
        employé" PUIS aller changer manuellement l'état du contrat dans
        l'app Employés — source d'oublis et d'emails d'acceptation jamais
        envoyés."""
        self.ensure_one()
        if not self.stage_id.is_contract_signed_stage:
            return

        if not self.emp_id:
            try:
                self.create_employee_from_applicant()
            except UserError:
                # Erreur métier volontaire (ex : un employé actif existe déjà
                # avec ces coordonnées) — on la laisse remonter pour BLOQUER
                # le changement d'étape et afficher un message clair au
                # recruteur, plutôt que de la masquer dans le chatter et
                # laisser la candidature avancer silencieusement vers
                # "Contrat signé" sans qu'aucun employé n'ait réellement été
                # créé/rattaché. Voir create_employee_from_applicant().
                raise
            except Exception as e:
                _logger.error(
                    "Création automatique de l'employé impossible pour %s : %s",
                    self.partner_name, e,
                )
                self.message_post(
                    body=(
                        "⚠️ Création automatique de l'employé impossible à "
                        f"cette étape : {e}\nÀ finaliser manuellement via le "
                        "bouton « Créer un employé »."
                    )
                )
                return

        if self.generated_contract_id and self.generated_contract_id.state != 'open':
            try:
                self.generated_contract_id.write({'state': 'open'})
            except Exception as e:
                _logger.error(
                    "Validation automatique du contrat impossible pour %s : %s",
                    self.partner_name, e,
                )
                self.message_post(
                    body=(
                        "⚠️ Validation automatique du contrat impossible : "
                        f"{e}\nÀ finaliser manuellement depuis la fiche du "
                        "contrat (app Employés > Contrats)."
                    )
                )

    def action_schedule_interview(self):
        """Crée un événement calendrier pour l'entretien, planifié le lendemain à 10h par défaut."""
        for applicant in self:
            if (applicant.interview_event_id
                    and applicant.last_scheduled_interview_stage_id == applicant.stage_id):
                raise UserError(
                    "Un entretien est déjà planifié pour ce candidat à "
                    f"l'étape « {applicant.stage_id.name} »."
                )

            start = fields.Datetime.now() + timedelta(days=1)
            start = start.replace(hour=10, minute=0, second=0)
            stop = start + timedelta(hours=1)

            partners = applicant.env.user.partner_id
            attendees = [(4, partners.id)]
            if applicant.interviewer_ids:
                for interviewer in applicant.interviewer_ids:
                    attendees.append((4, interviewer.partner_id.id))

            interview_type_label = dict(
                applicant.stage_id._fields['interview_type'].selection
            ).get(applicant.stage_id.interview_type, "Entretien")

            event = self.env['calendar.event'].create({
                'name': (
                    f"{interview_type_label} - {applicant.partner_name} "
                    f"- {applicant.job_id.name}"
                ),
                'start': start,
                'stop': stop,
                'partner_ids': attendees,
                'description': applicant.ai_interview_questions or "",
                'res_id': applicant.id,
                'res_model_id': self.env['ir.model']._get_id('hr.applicant'),
            })

            applicant.interview_event_id = event.id
            applicant.last_scheduled_interview_stage_id = applicant.stage_id.id
            self.env['hr.applicant.interview'].create({
                'applicant_id': applicant.id,
                'stage_id': applicant.stage_id.id,
                'calendar_event_id': event.id,
                'questions': applicant.ai_interview_questions,
            })
            applicant._send_interview_invitation_email()

    def _send_interview_invitation_email(self):
        """Envoie au candidat un email de convocation précisant le type
        d'entretien (RH/Technique), la date/heure, et l'interviewer.
        Appelé juste après la création de l'événement calendrier — c'est
        volontairement séparé de l'email générique par étape
        (_send_stage_automatic_email), qui se déclenche trop tôt (avant que
        l'événement et sa date n'existent)."""
        self.ensure_one()
        if not self.email_from:
            _logger.warning(
                "Email de convocation non envoyé pour %s : aucune adresse "
                "email connue sur cette candidature.", self.partner_name,
            )
            return
        if not self.interview_event_id:
            return

        interview_type_label = dict(
            self.stage_id._fields['interview_type'].selection
        ).get(self.stage_id.interview_type, "Entretien")

        event = self.interview_event_id
        date_str = fields.Datetime.context_timestamp(
            self, event.start
        ).strftime('%d/%m/%Y à %H:%M')

        interviewer_names = ", ".join(self.interviewer_ids.mapped('name'))
        if not interviewer_names:
            interviewer_names = self.user_id.name or "à confirmer prochainement"

        job_name = self.job_id.name if self.job_id else "notre entreprise"
        subject = f"{interview_type_label} — Candidature {job_name}"
        body_html = f"""
            <p>Bonjour {self.partner_name or ''},</p>
            <p>Nous avons le plaisir de vous convier à un entretien dans le cadre
            de votre candidature{" au poste de " + job_name if self.job_id else ""}.</p>
            <ul>
                <li><strong>Type d'entretien :</strong> {interview_type_label}</li>
                <li><strong>Date et heure :</strong> {date_str}</li>
                <li><strong>Avec :</strong> {interviewer_names}</li>
            </ul>
            <p>Merci de confirmer votre disponibilité en répondant à cet email.
            N'hésitez pas à nous contacter si ce créneau ne vous convient pas.</p>
            <p>Cordialement,<br/>L'équipe recrutement</p>
        """

        self._send_email_safely(
            subject=subject,
            body_html=body_html,
            log_success=(
                f"Email de convocation envoyé au candidat : {interview_type_label}, "
                f"le {date_str}, avec {interviewer_names}."
            ),
            log_failure_prefix="Échec de l'envoi de l'email de convocation",
        )

    def _send_refusal_email(self):
        """Envoie un email de refus avec motif explicite au candidat.
        Déclenché automatiquement dès que refuse_reason_id est renseigné
        (champ standard Odoo, rempli via le bouton "Refuser")."""
        self.ensure_one()
        reason_label = self.refuse_reason_id.name if self.refuse_reason_id else "non précisé"
        job_name = self.job_id.name if self.job_id else "notre entreprise"

        subject = f"Réponse à votre candidature — {job_name}"
        body_html = f"""
            <p>Bonjour {self.partner_name or ''},</p>
            <p>Nous vous remercions pour l'intérêt que vous avez porté à notre
            entreprise et pour le temps consacré à votre candidature
            {"au poste de " + job_name if self.job_id else ""}.</p>
            <p>Après étude attentive de votre profil, nous sommes au regret
            de vous informer que nous ne donnerons pas suite à votre
            candidature.</p>
            <p><strong>Motif :</strong> {reason_label}</p>
            <p>Nous vous souhaitons une pleine réussite dans vos recherches
            et conservons votre profil pour de futures opportunités
            correspondant à votre parcours.</p>
            <p>Cordialement,<br/>L'équipe recrutement</p>
        """

        self._send_email_safely(
            subject=subject,
            body_html=body_html,
            log_success=f"Email de refus envoyé au candidat (motif : {reason_label}).",
            log_failure_prefix="Échec de l'envoi de l'email de refus",
        )

    def _send_acceptance_email(self):
        """Envoie un email de félicitations/acceptation au candidat.
        Déclenché automatiquement quand son contrat généré passe à l'état
        "En cours" (signé/validé) — voir models/hr_contract.py."""
        self.ensure_one()
        job_name = self.job_id.name if self.job_id else "notre entreprise"

        subject = f"Félicitations — Votre candidature « {job_name} » est acceptée !"
        body_html = f"""
            <p>Bonjour {self.partner_name or ''},</p>
            <p>Nous avons le plaisir de vous confirmer que votre candidature
            {"au poste de " + job_name if self.job_id else ""} a été retenue
            et que votre contrat est désormais validé.</p>
            <p>Toute l'équipe se réjouit de vous accueillir prochainement.
            Vous recevrez très prochainement les informations pratiques pour
            votre intégration (matériel, accès, journée d'accueil...).</p>
            <p>Bienvenue parmi nous !<br/>L'équipe RH</p>
        """

        self._send_email_safely(
            subject=subject,
            body_html=body_html,
            log_success="Email de félicitations/acceptation envoyé au candidat.",
            log_failure_prefix="Échec de l'envoi de l'email d'acceptation",
        )

    def create_employee_from_applicant(self):
        """Crée un employé depuis la candidature, transfère les résultats
        d'analyse IA, et déclenche l'onboarding IA automatique.

        Si un EMPLOYÉ ACTIF existe déjà avec le même email ou le même nom
        (ex : la même personne postule pour un second poste, ou une erreur
        de saisie), on NE le réutilise PLUS silencieusement. Une première
        version le faisait (pour éviter les employés en double), mais ça
        revenait à réappliquer tout l'onboarding IA — nouvelle évaluation
        de performance, tâches d'onboarding, etc. — sur une personne DÉJÀ
        en poste, pour une candidature qui n'a souvent rien à voir avec
        son poste actuel.
        Bug réel constaté le 13/08/2026 : une personne recrutée comme
        « Développeur IA » (évaluation IA à 89%) a vu son évaluation
        écrasée par celle d'une seconde candidature « Développeur Odoo »
        pour la même personne (89% -> 79%), sans lien avec son poste réel.
        On bloque maintenant avec un message clair, sans toucher à
        l'employé ni à hr.appraisal, et on laisse le recruteur traiter le
        cas manuellement (mobilité interne, doublon de saisie...)."""
        for applicant in self:
            if not applicant.emp_id:
                existing_emp = False
                if applicant.email_from:
                    existing_emp = self.env['hr.employee'].sudo().search([
                        '|',
                        ('work_email', '=ilike', applicant.email_from.strip()),
                        ('private_email', '=ilike', applicant.email_from.strip()),
                    ], limit=1)
                if not existing_emp and applicant.partner_name:
                    existing_emp = self.env['hr.employee'].sudo().search([
                        ('name', '=ilike', applicant.partner_name.strip())
                    ], limit=1)

                # NB : .search() sans with_context(active_test=False) ne
                # trouve QUE des employés actifs (comportement Odoo par
                # défaut) — tout match ici est donc forcément quelqu'un
                # actuellement en poste, jamais un ancien employé archivé.
                if existing_emp:
                    raise UserError(
                        "Impossible de créer un employé pour « %s » : un employé "
                        "actif (« %s », poste : %s) existe déjà avec les mêmes "
                        "coordonnées (email ou nom).\n\n"
                        "Si cette candidature correspond à une mobilité interne ou "
                        "un changement de poste pour cette personne, traitez-la "
                        "manuellement depuis sa fiche employé plutôt que via le "
                        "pipeline de recrutement. Si c'est une erreur de saisie "
                        "(doublon de candidature), fusionnez ou supprimez cette "
                        "candidature avant de continuer." % (
                            applicant.partner_name or applicant.name,
                            existing_emp.name,
                            existing_emp.job_title or existing_emp.job_id.name or "non renseigné",
                        )
                    )

        # La méthode native d'Odoo (super) crée TOUJOURS un nouvel
        # hr.employee et écrase applicant.emp_id, sans jamais vérifier si
        # le champ est déjà renseigné. L'appeler inconditionnellement sur
        # une candidature déjà convertie (emp_id déjà présent avant cet
        # appel, ex : appel répété) créerait donc un EMPLOYÉ EN DOUBLE —
        # bug réel détecté le 13/08/2026. On ne délègue à super() que pour
        # les candidatures qui ont RÉELLEMENT besoin d'un nouvel employé
        # (à ce stade, on sait qu'aucune ne correspond à un employé actif
        # existant : on aurait levé une erreur juste avant).
        to_create = self.filtered(lambda a: not a.emp_id)
        result = False
        if to_create:
            result = super(HrApplicant, to_create).create_employee_from_applicant()
        if not result and self[:1].emp_id:
            result = {
                'type': 'ir.actions.act_window',
                'res_model': 'hr.employee',
                'res_id': self[:1].emp_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

        for applicant in self:
            if applicant.emp_id:
                # Service réutilisable : transfert des données IA du recrutement
                applicant._transfer_ai_recruitment_data_to_employee(applicant.emp_id)

                # Rattachement département & tâches onboarding
                applicant._ensure_employee_department()
                applicant._generate_onboarding_contract()
                applicant._create_onboarding_tasks()

                # Service réutilisable : déclenchement Onboarding IA automatique
                if hasattr(applicant.emp_id, 'action_run_ai_onboarding'):
                    applicant.emp_id.action_run_ai_onboarding()

        return result

    def _transfer_ai_recruitment_data_to_employee(self, employee):
        """Transfère les données d'analyse IA de la candidature vers l'employé sans re-calculer."""
        self.ensure_one()
        if not employee:
            return
        employee.sudo().write({
            'ai_recruitment_score': self.ai_score or 0.0,
            'ai_recruitment_summary': self.ai_summary or '',
            'ai_extracted_skills': self.extracted_skills or '',
            'ai_extracted_skills_detailed': self.extracted_skills_detailed or '',
            'ai_extracted_technologies': self.ai_matched_skills or '',
            'ai_extracted_soft_skills': self.ai_recommendation or '',
            'ai_extracted_languages': self.extracted_languages or '',
            'ai_extracted_certifications': self.extracted_certifications or '',
        })

    def action_view_employee(self):
        """Action pour le smart button 'Employé créé' sur la candidature."""
        self.ensure_one()
        if not self.emp_id:
            return {}
        return {
            'name': "Fiche Employé",
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'res_id': self.emp_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


    def _ensure_employee_department(self):
        """Garantit que l'employé créé depuis ce candidat est bien rattaché
        au département du poste concerné (hr.job.department_id), plutôt
        que de supposer que le comportement natif d'Odoo l'a déjà fait
        correctement (il peut être absent si le poste a été modifié après
        la candidature, ou vide selon la configuration)."""
        self.ensure_one()
        if not self.emp_id or not self.job_id:
            return

        job_department = self.job_id.department_id
        if not job_department:
            _logger.warning(
                "Impossible de rattacher %s à un département : aucun "
                "département défini sur le poste « %s ».",
                self.emp_id.name, self.job_id.name,
            )
            self.message_post(
                body=(
                    f"⚠️ Employé créé sans département : le poste "
                    f"« {self.job_id.name} » n'a aucun département "
                    "configuré. Rattache-le manuellement."
                )
            )
            return

        if self.emp_id.department_id != job_department:
            self.emp_id.department_id = job_department.id
            self.message_post(
                body=(
                    f"Employé rattaché automatiquement au département "
                    f"« {job_department.name} » (d'après le poste "
                    f"« {self.job_id.name} »)."
                )
            )

    def _generate_onboarding_contract(self):
        self.ensure_one()
        if self.generated_contract_id:
            return

        contract = self.env['hr.contract'].create({
            'name': f"Contrat - {self.emp_id.name}",
            'employee_id': self.emp_id.id,
            'job_id': self.job_id.id,
            'wage': self.salary_proposed or self.salary_expected or 0.0,
            'date_start': fields.Date.context_today(self),
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