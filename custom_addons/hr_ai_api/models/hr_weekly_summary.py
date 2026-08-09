# -*- coding: utf-8 -*-
import json
import logging
import time
from datetime import timedelta

import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Reprend volontairement le même schéma de configuration que les autres
# modules IA (hr_recruitment_ai_assistant, hr_appraisal_ai...) : une seule
# clé API partagée, pour ne pas multiplier les paramètres système.
_CONFIG_PARAM_API_KEY = 'smart_hr_ai.gemini_api_key'

WEEKLY_SUMMARY_PROMPT = """Tu es l'assistant RH IA d'une entreprise. Rédige un résumé hebdomadaire
RH professionnel, clair et synthétique à partir des statistiques ci-dessous, à
destination de l'équipe RH et de la direction.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, sans
balises markdown, avec exactement cette structure :
{{
  "headline": "une phrase d'accroche résumant la tendance générale de la semaine",
  "highlights": ["fait marquant 1", "fait marquant 2", "fait marquant 3"],
  "recruitment_comment": "1-2 phrases commentant le recrutement cette semaine",
  "leaves_comment": "1-2 phrases commentant les congés cette semaine",
  "attendance_comment": "1-2 phrases commentant les présences/anomalies cette semaine",
  "performance_comment": "1-2 phrases commentant les évaluations de performance cette semaine",
  "alerts": ["point de vigilance 1", "point de vigilance 2"],
  "recommendations": ["recommandation actionnable 1", "recommandation actionnable 2"]
}}

Règles :
- Si une catégorie n'a aucune activité cette semaine (valeur à 0), dis-le
  simplement plutôt que d'inventer un commentaire ("Aucune nouvelle demande
  de congé cette semaine.").
- "alerts" ne doit contenir que des points RÉELLEMENT préoccupants d'après
  les chiffres (ex : beaucoup d'anomalies de présence, beaucoup de refus de
  congés, score de recrutement en baisse). Renvoie une liste vide si rien
  ne le justifie — n'invente jamais un problème pour remplir la liste.
- Reste factuel : base-toi uniquement sur les chiffres fournis, ne suppose
  aucune information que tu n'as pas.
- Ton professionnel, concis, orienté action pour les recommandations.

RÈGLE DE FORMAT JSON CRITIQUE : n'utilise JAMAIS de guillemets doubles (")
à l'intérieur du texte des valeurs. Utilise des guillemets simples (') ou
des guillemets français (« ») si nécessaire, jamais de guillemets doubles
droits, car cela casserait la structure du JSON.

--- PÉRIODE ---
Semaine du {date_from} au {date_to}

--- RECRUTEMENT ---
Nouvelles candidatures reçues : {new_applicants_count}
Entretiens planifiés : {interviews_scheduled_count}
Nouveaux employés embauchés : {new_hires_count}
Score IA moyen des candidatures traitées cette semaine : {avg_recruitment_score_week}

--- CONGÉS ---
Demandes de congés créées : {leaves_requested_count}
  dont recommandation IA "Approuver" : {leaves_approve_count}
  dont recommandation IA "Vigilance" : {leaves_caution_count}
  dont recommandation IA "Refuser" : {leaves_refuse_count}

--- PRÉSENCES ---
Anomalies de présence détectées : {attendance_anomalies_count}
  dont pointages de sortie manquants : {attendance_missing_checkout_count}
  dont retards répétés : {attendance_repeated_lateness_count}

--- PERFORMANCE ---
Évaluations IA générées : {appraisals_generated_count}
Score de performance moyen des évaluations générées cette semaine : {avg_performance_score_week}
Nouveaux hauts potentiels identifiés : {new_high_potentials_count}
"""


class HrWeeklySummary(models.Model):
    _name = 'hr.weekly.summary'
    _inherit = ['mail.thread']
    _description = "Résumé hebdomadaire RH généré par IA"
    _order = 'date_from desc'

    name = fields.Char(string="Titre", compute='_compute_name', store=True)
    date_from = fields.Date(string="Du", required=True)
    date_to = fields.Date(string="Au", required=True)
    department_id = fields.Many2one(
        'hr.department', string="Département (optionnel)",
        help="Si renseigné, le résumé ne porte que sur ce département. "
             "Laisser vide pour un résumé toutes équipes confondues."
    )
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('generated', 'Généré'),
        ('error', 'Erreur'),
    ], string="Statut", default='draft', required=True)
    generated_on = fields.Datetime(string="Généré le", readonly=True, copy=False)
    summary_html = fields.Html(string="Résumé IA", readonly=True, copy=False)
    summary_json = fields.Text(
        string="Résumé IA (JSON brut)", readonly=True, copy=False,
        help="Sortie structurée brute de Gemini (headline, highlights, "
             "commentaires par domaine, alertes, recommandations). Utilisée "
             "par l'API mobile pour éviter de reparser le HTML."
    )

    # --- Statistiques brutes (traçabilité + affichage en stat-boxes) ---
    new_applicants_count = fields.Integer(string="Nouvelles candidatures", readonly=True, copy=False)
    interviews_scheduled_count = fields.Integer(string="Entretiens planifiés", readonly=True, copy=False)
    new_hires_count = fields.Integer(string="Nouveaux employés", readonly=True, copy=False)
    avg_recruitment_score_week = fields.Float(string="Score IA moyen (recrutement)", readonly=True, copy=False)

    leaves_requested_count = fields.Integer(string="Demandes de congés", readonly=True, copy=False)
    leaves_approve_count = fields.Integer(string="dont Approuver (IA)", readonly=True, copy=False)
    leaves_caution_count = fields.Integer(string="dont Vigilance (IA)", readonly=True, copy=False)
    leaves_refuse_count = fields.Integer(string="dont Refuser (IA)", readonly=True, copy=False)

    attendance_anomalies_count = fields.Integer(string="Anomalies de présence", readonly=True, copy=False)
    attendance_missing_checkout_count = fields.Integer(string="dont sorties manquantes", readonly=True, copy=False)
    attendance_repeated_lateness_count = fields.Integer(string="dont retards répétés", readonly=True, copy=False)

    appraisals_generated_count = fields.Integer(string="Évaluations générées", readonly=True, copy=False)
    avg_performance_score_week = fields.Float(string="Score de performance moyen", readonly=True, copy=False)
    new_high_potentials_count = fields.Integer(string="Nouveaux hauts potentiels", readonly=True, copy=False)

    @api.depends('date_from', 'date_to', 'department_id')
    def _compute_name(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                base = "Résumé RH — semaine du %s au %s" % (
                    rec.date_from.strftime('%d/%m/%Y'), rec.date_to.strftime('%d/%m/%Y'),
                )
                rec.name = f"{base} ({rec.department_id.name})" if rec.department_id else base
            else:
                rec.name = "Résumé RH hebdomadaire"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        date_from, date_to = self._get_last_full_week()
        if 'date_from' in fields_list:
            res['date_from'] = date_from
        if 'date_to' in fields_list:
            res['date_to'] = date_to
        return res

    @api.model
    def _get_last_full_week(self, reference_date=None):
        """Renvoie (lundi, dimanche) de la dernière semaine ENTIÈREMENT
        écoulée par rapport à reference_date (aujourd'hui par défaut).
        Ex : si on est mercredi, renvoie la semaine précédente complète,
        pas la semaine en cours (encore partielle)."""
        today = reference_date or fields.Date.context_today(self)
        monday_this_week = today - timedelta(days=today.weekday())
        monday_last_week = monday_this_week - timedelta(days=7)
        sunday_last_week = monday_this_week - timedelta(days=1)
        return monday_last_week, sunday_last_week

    # ------------------------------------------------------------------
    # Génération
    # ------------------------------------------------------------------

    def action_generate_summary(self):
        """Recalcule les statistiques de la période puis génère le résumé
        narratif via Gemini. Rejouable : régénère entièrement le résumé
        (utile si des données ont été corrigées après une première
        génération)."""
        for rec in self:
            if not rec.date_from or not rec.date_to or rec.date_from > rec.date_to:
                raise UserError(
                    "La période (Du / Au) doit être renseignée et cohérente "
                    "avant de générer le résumé."
                )
            stats = rec._collect_week_stats()
            rec.write(stats['fields'])
            try:
                result = rec._call_gemini_weekly_summary(stats['fields'], stats['details'])
                rec.summary_html = rec._build_summary_html(result)
                rec.summary_json = json.dumps(result, ensure_ascii=False)
                rec.write({'state': 'generated', 'generated_on': fields.Datetime.now()})
            except Exception as e:
                _logger.error(
                    "Erreur génération résumé hebdomadaire RH (%s - %s) : %s",
                    rec.date_from, rec.date_to, e,
                )
                rec.state = 'error'
                raise UserError(f"Erreur lors de la génération IA du résumé : {e}")

    def _collect_week_stats(self):
        """Rassemble les statistiques de la période [date_from, date_to]
        (bornes incluses) depuis les modules métier déjà installés.
        Chaque bloc est protégé par une vérification de présence du modèle
        pour rester robuste si un module optionnel n'est pas installé
        (même logique défensive que smart.hr.ai.dashboard)."""
        self.ensure_one()
        start = fields.Datetime.to_datetime(self.date_from)
        end = fields.Datetime.to_datetime(self.date_to) + timedelta(days=1) - timedelta(seconds=1)
        dept = self.department_id

        fields_vals = {}
        details = {}

        # --- Recrutement ---
        applicant_domain = [('create_date', '>=', start), ('create_date', '<=', end)]
        if dept:
            applicant_domain.append(('department_id', '=', dept.id))
        applicants = self.env['hr.applicant'].sudo().with_context(active_test=False).search(applicant_domain)
        fields_vals['new_applicants_count'] = len(applicants)

        interview_domain = [('create_date', '>=', start), ('create_date', '<=', end)]
        if dept:
            interview_domain.append(('applicant_id.department_id', '=', dept.id))
        interviews = self.env['hr.applicant.interview'].sudo().search(interview_domain) \
            if 'hr.applicant.interview' in self.env else self.env['hr.applicant.interview']
        fields_vals['interviews_scheduled_count'] = len(interviews)

        hire_domain = [('create_date', '>=', start), ('create_date', '<=', end)]
        if dept:
            hire_domain.append(('department_id', '=', dept.id))
        new_hires = self.env['hr.employee'].sudo().search(hire_domain)
        fields_vals['new_hires_count'] = len(new_hires)
        details['new_hire_names'] = new_hires.mapped('name')[:10]

        scored_applicants = applicants.filtered(lambda a: getattr(a, 'ai_score', 0) > 0)
        fields_vals['avg_recruitment_score_week'] = (
            round(sum(scored_applicants.mapped('ai_score')) / len(scored_applicants), 1)
            if scored_applicants else 0.0
        )

        # --- Congés ---
        if 'hr.leave' in self.env:
            leave_domain = [('create_date', '>=', start), ('create_date', '<=', end)]
            if dept:
                leave_domain.append(('department_id', '=', dept.id))
            leaves = self.env['hr.leave'].sudo().search(leave_domain)
        else:
            leaves = None
        leaves_count = len(leaves) if leaves is not None else 0
        fields_vals['leaves_requested_count'] = leaves_count
        fields_vals['leaves_approve_count'] = len(leaves.filtered(lambda l: l.ai_recommendation == 'approve')) if leaves is not None else 0
        fields_vals['leaves_caution_count'] = len(leaves.filtered(lambda l: l.ai_recommendation == 'caution')) if leaves is not None else 0
        fields_vals['leaves_refuse_count'] = len(leaves.filtered(lambda l: l.ai_recommendation == 'refuse')) if leaves is not None else 0

        # --- Présences ---
        if 'hr.attendance.anomaly' in self.env:
            anomaly_domain = [('detected_on', '>=', start), ('detected_on', '<=', end)]
            if dept:
                anomaly_domain.append(('employee_id.department_id', '=', dept.id))
            anomalies = self.env['hr.attendance.anomaly'].sudo().search(anomaly_domain)
        else:
            anomalies = None
        anomalies_count = len(anomalies) if anomalies is not None else 0
        fields_vals['attendance_anomalies_count'] = anomalies_count
        fields_vals['attendance_missing_checkout_count'] = (
            len(anomalies.filtered(lambda a: a.anomaly_type == 'missing_checkout')) if anomalies is not None else 0
        )
        fields_vals['attendance_repeated_lateness_count'] = (
            len(anomalies.filtered(lambda a: a.anomaly_type == 'repeated_lateness')) if anomalies is not None else 0
        )

        # --- Performance ---
        if 'hr.appraisal.ai.analysis' in self.env:
            analysis_domain = [('create_date', '>=', start), ('create_date', '<=', end)]
            if dept:
                analysis_domain.append(('employee_id.department_id', '=', dept.id))
            analyses = self.env['hr.appraisal.ai.analysis'].sudo().search(analysis_domain)
        else:
            analyses = None
        analyses_count = len(analyses) if analyses is not None else 0
        fields_vals['appraisals_generated_count'] = analyses_count
        perf_scores = analyses.mapped('performance_score') if analyses is not None else []
        perf_scores = [s for s in perf_scores if s]
        fields_vals['avg_performance_score_week'] = round(sum(perf_scores) / len(perf_scores), 1) if perf_scores else 0.0
        fields_vals['new_high_potentials_count'] = (
            len(analyses.filtered('high_potential')) if analyses is not None else 0
        )

        return {'fields': fields_vals, 'details': details}

    def _call_gemini_weekly_summary(self, stats, details):
        self.ensure_one()
        prompt = WEEKLY_SUMMARY_PROMPT.format(
            date_from=self.date_from.strftime('%d/%m/%Y'),
            date_to=self.date_to.strftime('%d/%m/%Y'),
            **stats,
        )
        return self._call_gemini_json(prompt)

    def _call_gemini_json(self, prompt, max_attempts=3):
        """Appel Gemini avec retry sur erreurs temporaires uniquement
        (503/429, réseau, JSON invalide) — même logique que les autres
        modules IA du projet (voir hr_recruitment_ai_assistant)."""
        api_key = self.env['ir.config_parameter'].sudo().get_param(_CONFIG_PARAM_API_KEY)
        if not api_key:
            raise UserError(
                "Clé API Gemini non configurée (Configuration > Technique > "
                "Paramètres système > 'smart_hr_ai.gemini_api_key')."
            )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json",
                "maxOutputTokens": 2048,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        last_error = None
        for attempt in range(max_attempts):
            try:
                response = requests.post(f"{GEMINI_URL}?key={api_key}", json=payload, timeout=60)
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise UserError(f"Impossible de contacter l'API Gemini (problème réseau) : {e}")

            if response.status_code in (503, 429):
                last_error = f"HTTP {response.status_code} : {response.text[:200]}"
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise UserError(f"L'API Gemini est surchargée après {max_attempts} tentatives.")

            if not response.ok:
                raise UserError(
                    f"L'API Gemini a renvoyé une erreur {response.status_code} "
                    f"(non temporaire) : {response.text[:300]}"
                )

            data = response.json()
            candidate = data["candidates"][0]
            if candidate.get("finishReason") == "MAX_TOKENS":
                raise UserError("La réponse IA a été coupée (dépassement de tokens).")

            parts = candidate.get("content", {}).get("parts", [])
            text_response = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if not text_response.strip():
                last_error = "réponse vide"
                if attempt < max_attempts - 1:
                    continue
                raise UserError("Gemini n'a renvoyé aucun contenu exploitable.")

            try:
                return json.loads(text_response)
            except json.JSONDecodeError as e:
                last_error = e
                if attempt < max_attempts - 1:
                    _logger.warning("JSON Gemini invalide (essai %s/%s) : %s", attempt + 1, max_attempts, e)
                    continue
                raise UserError(f"L'IA n'a pas renvoyé un JSON valide : {e}")

        raise UserError(f"Échec de génération après {max_attempts} tentatives : {last_error}")

    def _build_summary_html(self, result):
        """Construit un rendu HTML soigné, dans le même esprit visuel que
        les autres contenus générés du projet (hr.recruitment.ai.generator)."""
        self.ensure_one()

        def _list_html(items, empty_label):
            if not items:
                return f'<p style="color:#8A94A6; font-style:italic; margin:0;">{empty_label}</p>'
            lis = "".join(
                f'<li style="margin-bottom:6px; padding-left:18px; position:relative;">'
                f'<span style="position:absolute; left:0; color:#4F46E5; font-weight:bold;">•</span>'
                f'{item}</li>'
                for item in items
            )
            return f'<ul style="list-style:none; padding-left:0; margin:0;">{lis}</ul>'

        highlights_html = _list_html(result.get('highlights', []), "Aucun fait marquant particulier cette semaine.")
        alerts_html = _list_html(result.get('alerts', []), "Aucun point de vigilance particulier cette semaine.")
        recommendations_html = _list_html(result.get('recommendations', []), "Aucune recommandation spécifique.")

        return f"""
            <div style="font-family:'Outfit','Inter',sans-serif; line-height:1.7; color:#2C3E50; max-width:800px; margin:0 auto; background:#fff; padding:25px; border-radius:12px; border:1px solid #E2E8F0;">
                <div style="background:linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%); padding:24px; border-radius:10px; color:#fff; margin-bottom:20px;">
                    <span style="background:rgba(255,255,255,0.2); padding:4px 10px; border-radius:15px; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:1px;">Résumé hebdomadaire RH</span>
                    <h2 style="font-size:22px; margin:8px 0 5px 0; font-weight:700; color:#fff; border:none;">
                        Semaine du {self.date_from.strftime('%d/%m/%Y')} au {self.date_to.strftime('%d/%m/%Y')}
                    </h2>
                    <p style="margin:0; font-size:14px; opacity:0.9;">{result.get('headline', '')}</p>
                </div>

                <div style="margin-bottom:18px;">
                    <h3 style="color:#4F46E5; font-size:15px; font-weight:600; border-bottom:2px solid #EEF2F6; padding-bottom:6px; margin-bottom:10px;">🎯 Points clés</h3>
                    {highlights_html}
                </div>

                <div style="margin-bottom:18px;">
                    <h3 style="color:#4F46E5; font-size:15px; font-weight:600; border-bottom:2px solid #EEF2F6; padding-bottom:6px; margin-bottom:10px;">🧑‍💼 Recrutement</h3>
                    <p style="margin:0;">{result.get('recruitment_comment', '')}</p>
                </div>

                <div style="margin-bottom:18px;">
                    <h3 style="color:#4F46E5; font-size:15px; font-weight:600; border-bottom:2px solid #EEF2F6; padding-bottom:6px; margin-bottom:10px;">🌴 Congés</h3>
                    <p style="margin:0;">{result.get('leaves_comment', '')}</p>
                </div>

                <div style="margin-bottom:18px;">
                    <h3 style="color:#4F46E5; font-size:15px; font-weight:600; border-bottom:2px solid #EEF2F6; padding-bottom:6px; margin-bottom:10px;">⏱️ Présences</h3>
                    <p style="margin:0;">{result.get('attendance_comment', '')}</p>
                </div>

                <div style="margin-bottom:18px;">
                    <h3 style="color:#4F46E5; font-size:15px; font-weight:600; border-bottom:2px solid #EEF2F6; padding-bottom:6px; margin-bottom:10px;">📈 Performance</h3>
                    <p style="margin:0;">{result.get('performance_comment', '')}</p>
                </div>

                <div style="margin-bottom:18px;">
                    <h3 style="color:#B45309; font-size:15px; font-weight:600; border-bottom:2px solid #EEF2F6; padding-bottom:6px; margin-bottom:10px;">⚠️ Points de vigilance</h3>
                    {alerts_html}
                </div>

                <div>
                    <h3 style="color:#047857; font-size:15px; font-weight:600; border-bottom:2px solid #EEF2F6; padding-bottom:6px; margin-bottom:10px;">✅ Recommandations</h3>
                    {recommendations_html}
                </div>
            </div>
        """

    def _to_api_dict(self):
        """Représentation JSON-friendly d'un résumé, utilisée par le
        contrôleur API mobile (controllers/weekly_summary.py)."""
        self.ensure_one()
        try:
            parsed = json.loads(self.summary_json) if self.summary_json else {}
        except json.JSONDecodeError:
            parsed = {}
        return {
            'id': self.id,
            'name': self.name,
            'date_from': self.date_from.isoformat() if self.date_from else None,
            'date_to': self.date_to.isoformat() if self.date_to else None,
            'department': self.department_id.name or None,
            'department_id': self.department_id.id or None,
            'state': self.state,
            'generated_on': self.generated_on.isoformat() if self.generated_on else None,
            'headline': parsed.get('headline'),
            'highlights': parsed.get('highlights', []),
            'recruitment_comment': parsed.get('recruitment_comment'),
            'leaves_comment': parsed.get('leaves_comment'),
            'attendance_comment': parsed.get('attendance_comment'),
            'performance_comment': parsed.get('performance_comment'),
            'alerts': parsed.get('alerts', []),
            'recommendations': parsed.get('recommendations', []),
            'stats': {
                'new_applicants_count': self.new_applicants_count,
                'interviews_scheduled_count': self.interviews_scheduled_count,
                'new_hires_count': self.new_hires_count,
                'avg_recruitment_score_week': self.avg_recruitment_score_week,
                'leaves_requested_count': self.leaves_requested_count,
                'leaves_approve_count': self.leaves_approve_count,
                'leaves_caution_count': self.leaves_caution_count,
                'leaves_refuse_count': self.leaves_refuse_count,
                'attendance_anomalies_count': self.attendance_anomalies_count,
                'attendance_missing_checkout_count': self.attendance_missing_checkout_count,
                'attendance_repeated_lateness_count': self.attendance_repeated_lateness_count,
                'appraisals_generated_count': self.appraisals_generated_count,
                'avg_performance_score_week': self.avg_performance_score_week,
                'new_high_potentials_count': self.new_high_potentials_count,
            },
        }

    @api.model
    def _get_latest(self, department_id=None):
        """Dernier résumé GÉNÉRÉ (le plus récent par date_from), optionnellement
        filtré par département. Utilisé par le dashboard et par l'API mobile."""
        domain = [('state', '=', 'generated')]
        if department_id:
            domain.append(('department_id', '=', department_id))
        else:
            domain.append(('department_id', '=', False))
        return self.search(domain, order='date_from desc', limit=1)

    def action_open_latest(self):
        """Ouvre le dernier résumé généré (toutes équipes) — utilisé par le
        smart button du tableau de bord global."""
        latest = self._get_latest()
        if not latest:
            raise UserError("Aucun résumé hebdomadaire n'a encore été généré.")
        return {
            'name': latest.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.weekly.summary',
            'res_id': latest.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Envoi par email (optionnel)
    # ------------------------------------------------------------------

    def action_send_summary_email(self):
        """Envoie le résumé déjà généré aux utilisateurs du groupe RH
        (hr.group_hr_manager). Action manuelle, distincte de la génération
        (on peut vouloir relire avant d'envoyer)."""
        for rec in self:
            if rec.state != 'generated' or not rec.summary_html:
                raise UserError("Génère d'abord le résumé avant de l'envoyer par email.")

            hr_managers = self.env['res.users'].sudo().search([
                ('groups_id', 'in', self.env.ref('hr.group_hr_manager').id),
            ])
            recipients = hr_managers.mapped('email')
            recipients = [r for r in recipients if r]
            if not recipients:
                raise UserError("Aucun utilisateur RH avec une adresse email trouvée pour l'envoi.")

            mail = self.env['mail.mail'].sudo().create({
                'subject': rec.name,
                'body_html': rec.summary_html,
                'email_to': ",".join(recipients),
                'auto_delete': False,
            })
            mail.send()
            rec.message_post(body=f"Résumé envoyé par email à : {', '.join(recipients)}.")

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------

    @api.model
    def _cron_generate_weekly_summary(self):
        """Point d'entrée du cron hebdomadaire (voir data/ir_cron_weekly_summary.xml).
        Génère le résumé de la dernière semaine complète, sans doublon si
        un enregistrement existe déjà pour cette période (ex: relance
        manuelle du cron)."""
        date_from, date_to = self._get_last_full_week()
        existing = self.search([
            ('date_from', '=', date_from), ('date_to', '=', date_to),
        ], limit=1)
        record = existing or self.create({'date_from': date_from, 'date_to': date_to})
        try:
            record.action_generate_summary()
        except Exception as e:
            _logger.error(
                "Échec de la génération automatique du résumé hebdomadaire RH (%s - %s) : %s",
                date_from, date_to, e,
            )
