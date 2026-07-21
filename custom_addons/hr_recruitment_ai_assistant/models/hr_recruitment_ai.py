# -*- coding: utf-8 -*-

import json
import logging
import re
import requests
import time
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

JOB_DESCRIPTION_PROMPT = """Tu es un expert en recrutement et en ressources humaines.
Génère une description de poste professionnelle, attrayante et structurée pour le poste suivant :
Titre du poste : {job_title}
Compétences & Mots-clés souhaités : {skills}

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, sans balises markdown.

RÈGLE DE FORMAT JSON CRITIQUE : n'utilise JAMAIS de guillemets doubles (")
à l'intérieur du texte des valeurs (intro, missions, compétences, profil, avantages...).
Utilise des guillemets simples (') ou des guillemets français (« ») à la place, sinon cela casserait la structure du JSON.

Le JSON doit avoir exactement cette structure :
{{
  "intro": "une phrase d'introduction accueillante et stimulante présentant le poste",
  "missions": ["mission 1", "mission 2", "mission 3", "mission 4"],
  "skills": ["compétence 1 (avec précision/outil)", "compétence 2 (avec précision/outil)"],
  "profile": ["exigence de profil/études 1", "soft skill 1", "soft skill 2"],
  "benefits": ["avantage 1", "avantage 2", "avantage 3"]
}}
"""

class HrRecruitmentAiGenerator(models.Model):
    _name = 'hr.recruitment.ai.generator'
    _description = 'Générateur de Description de Poste IA'

    name = fields.Char(string="Titre du poste ciblé", required=True)
    key_skills = fields.Text(string="Compétences & Mots-clés")
    generated_description = fields.Html(string="Description générée par l'IA", readonly=True)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('generated', 'Généré par l\'IA')
    ], string="Statut", default='draft', readonly=True)

    def action_generate_description(self):
        for record in self:
            if not record.name:
                continue

            skills = record.key_skills or "Non spécifiées"
            prompt = JOB_DESCRIPTION_PROMPT.format(
                job_title=record.name,
                skills=skills
            )

            res_json = record._call_gemini_api(prompt)

            # Construction des listes HTML
            missions_list = "".join(f"""
                <li style="margin-bottom: 8px; padding-left: 20px; position: relative;">
                    <span style="position: absolute; left: 0; color: #4F46E5; font-weight: bold;">•</span>
                    {mission}
                </li>
            """ for mission in res_json.get('missions', []))

            skills_list = "".join(f"""
                <span style="background-color: #EEF2F6; color: #4F46E5; padding: 6px 12px; border-radius: 20px; font-size: 13px; font-weight: 500; border: 1px solid #E2E8F0; display: inline-block; margin-right: 6px; margin-bottom: 6px;">
                    {skill}
                </span>
            """ for skill in res_json.get('skills', []))

            profile_list = "".join(f"""
                <li style="margin-bottom: 8px; padding-left: 20px; position: relative;">
                    <span style="position: absolute; left: 0; color: #4F46E5; font-weight: bold;">•</span>
                    {req}
                </li>
            """ for req in res_json.get('profile', []))

            benefits_list = "".join(f"""
                <li style="margin-bottom: 8px; padding-left: 20px; position: relative;">
                    <span style="position: absolute; left: 0; color: #4F46E5; font-weight: bold;">•</span>
                    {benefit}
                </li>
            """ for benefit in res_json.get('benefits', []))

            # HTML final haut de gamme
            html_content = f"""
                <div style="font-family: 'Outfit', 'Inter', sans-serif; line-height: 1.7; color: #2C3E50; max-width: 800px; margin: 0 auto; background: #ffffff; padding: 25px; border-radius: 12px; border: 1px solid #E2E8F0;">
                    <!-- En-tête avec dégradé subtil -->
                    <div style="background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%); padding: 24px; border-radius: 10px; color: #ffffff; margin-bottom: 20px;">
                        <span style="background: rgba(255, 255, 255, 0.2); padding: 4px 10px; border-radius: 15px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Offre d'emploi</span>
                        <h2 style="font-size: 24px; margin: 8px 0 5px 0; font-weight: 700; color: #ffffff; border: none; letter-spacing: -0.5px;">{record.name}</h2>
                        <p style="margin: 0; font-size: 14px; opacity: 0.9; font-weight: 400; line-height: 1.4;">{res_json.get('intro', '')}</p>
                    </div>

                    <!-- Missions principales -->
                    <div style="margin-bottom: 20px;">
                        <h3 style="color: #4F46E5; font-size: 16px; font-weight: 600; border-bottom: 2px solid #EEF2F6; padding-bottom: 6px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 18px;">🎯</span> Missions principales
                        </h3>
                        <ul style="list-style-type: none; padding-left: 0; margin: 0;">
                            {missions_list}
                        </ul>
                    </div>

                    <!-- Compétences clés -->
                    <div style="margin-bottom: 20px;">
                        <h3 style="color: #4F46E5; font-size: 16px; font-weight: 600; border-bottom: 2px solid #EEF2F6; padding-bottom: 6px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 18px;">🛠️</span> Compétences clés requises
                        </h3>
                        <div style="margin-top: 8px;">
                            {skills_list}
                        </div>
                    </div>

                    <!-- Profil recherché -->
                    <div style="margin-bottom: 20px;">
                        <h3 style="color: #4F46E5; font-size: 16px; font-weight: 600; border-bottom: 2px solid #EEF2F6; padding-bottom: 6px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 18px;">👤</span> Profil recherché
                        </h3>
                        <ul style="list-style-type: none; padding-left: 0; margin: 0;">
                            {profile_list}
                        </ul>
                    </div>

                    <!-- Avantages -->
                    <div>
                        <h3 style="color: #4F46E5; font-size: 16px; font-weight: 600; border-bottom: 2px solid #EEF2F6; padding-bottom: 6px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 18px;">✨</span> Avantages proposés
                        </h3>
                        <ul style="list-style-type: none; padding-left: 0; margin: 0;">
                            {benefits_list}
                        </ul>
                    </div>
                </div>
            """

            record.generated_description = html_content
            record.state = 'generated'

    def _call_gemini_api(self, prompt):
        api_key = self.env['ir.config_parameter'].sudo().get_param('smart_hr_ai.gemini_api_key')
        if not api_key or api_key == 'VOTRE_CLE_API_GEMINI':
            raise UserError("Clé API Gemini non configurée. Veuillez renseigner le paramètre système 'smart_hr_ai.gemini_api_key' sous Configuration > Technique > Paramètres système.")

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json",
                "maxOutputTokens": 4096,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        last_error = None
        max_retries = 3
        data = None
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{GEMINI_URL}?key={api_key}",
                    json=payload,
                    timeout=60,
                )
                if response.status_code in (503, 429) and attempt < max_retries - 1:
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                data = response.json()
                break
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
        
        if not data:
            raise UserError(
                f"L'API Gemini est indisponible après {max_retries} tentatives. "
                f"Détail technique : {last_error}"
            )

        try:
            candidate = data["candidates"][0]
            parts = candidate.get("content", {}).get("parts", [])
            text_response = "".join(
                part.get("text", "") for part in parts if not part.get("thought")
            )
            
            cleaned = text_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()

            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                repaired = re.sub(r',\s*([}\]])', r'\1', cleaned)
                return json.loads(repaired)
        except Exception as e:
            _logger.error("Erreur de parsing de la réponse Gemini : %s", e)
            raise UserError("L'IA n'a pas retourné une structure JSON valide. Veuillez réessayer.")

