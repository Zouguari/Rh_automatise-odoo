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
- Reste factuel : base-toi uniquement sur les chiffres et noms fournis
  ci-dessous, ne suppose aucune information que tu n'as pas.
- Si des noms d'employés nouvellement embauchés ou des intitulés de poste
  sont fournis ci-dessous (sections "Détail des nouvelles embauches" et
  "Postes ayant reçu des candidatures"), cite-les NOMMÉMENT dans
  "recruitment_comment" et/ou "highlights" pour rendre le résumé concret —
  mais UNIQUEMENT les noms/postes réellement fournis, n'en invente jamais
  d'autres.
- Si "Période complète ?" indique qu'il s'agit d'une semaine EN COURS (pas
  encore terminée), formule tous tes commentaires au conditionnel/provisoire
  ("jusqu'à présent cette semaine...", "à ce stade..."), jamais comme un
  bilan définitif — la semaine n'est pas terminée, d'autres événements
  peuvent encore survenir avant sa clôture.
- Ton professionnel, concis, orienté action pour les recommandations.

RÈGLE DE FORMAT JSON CRITIQUE : n'utilise JAMAIS de guillemets doubles (")
à l'intérieur du texte des valeurs. Utilise des guillemets simples (') ou
des guillemets français (« ») si nécessaire, jamais de guillemets doubles
droits, car cela casserait la structure du JSON.

--- PÉRIODE ---
Semaine du {date_from} au {date_to}
Période complète ? {is_partial_week}

--- RECRUTEMENT ---
Nouvelles candidatures reçues : {new_applicants_count}
Postes ayant reçu des candidatures cette semaine : {top_recruiting_jobs}
Entretiens planifiés : {interviews_scheduled_count}
Nouveaux employés (tous types de recrutement confondus) : {new_hires_count}
  dont recrutés via le pipeline de recrutement IA (candidature -> embauche) : {new_hires_via_ai_pipeline_count}
Détail des nouvelles embauches (nom — poste — département) : {new_hires_detail}
Score IA moyen des candidatures évaluées/notées cette semaine : {avg_recruitment_score_week}

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
    period_type = fields.Selection([
        ('last_week', "Dernière semaine complète"),
        ('current_week_to_date', "Semaine en cours (aperçu provisoire)"),
        ('custom', "Période personnalisée"),
    ], string="Type de période", default='last_week', required=True,
        help="'Dernière semaine complète' : le rapport hebdomadaire officiel "
             "(généré chaque lundi par le cron, ou manuellement). 'Semaine en "
             "cours' : un aperçu provisoire à jour, généré à la demande sans "
             "attendre la clôture de la semaine — ex: pour voir immédiatement "
             "l'effet d'une embauche qui vient d'avoir lieu. Ces deux types ne "
             "doivent jamais être confondus : le premier est un bilan clos, le "
             "second peut encore changer avant la fin de la semaine.")
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
    new_hires_via_ai_pipeline_count = fields.Integer(
        string="dont recrutés via le pipeline IA", readonly=True, copy=False,
        help="Parmi 'Nouveaux employés' ci-dessus, ceux réellement issus du "
             "pipeline de recrutement IA (candidature -> pipeline -> contrat "
             "signé), identifiés via hr.employee.origin_applicant_id. Les "
             "employés créés manuellement (hors ATS) sont comptés dans "
             "'Nouveaux employés' mais pas ici."
    )
    avg_recruitment_score_week = fields.Float(string="Score IA moyen (recrutement)", readonly=True, copy=False)
    top_recruiting_jobs = fields.Text(
        string="Postes ayant reçu des candidatures", readonly=True, copy=False,
        help="Répartition (poste, nombre de candidatures) des candidatures reçues "
             "sur la période, triée par volume décroissant. Alimente le prompt IA "
             "(pour que le résumé cite les postes concrètement) et sert de trace "
             "lisible directement sur la fiche."
    )
    new_hires_detail = fields.Text(
        string="Détail des nouvelles embauches", readonly=True, copy=False,
        help="Nom, poste et département de chaque nouvel employé créé sur la "
             "période (limité aux 10 premiers). Permet à l'IA de citer les "
             "embauches nommément dans le résumé (voir WEEKLY_SUMMARY_PROMPT), "
             "au lieu de rester sur un simple total agrégé."
    )

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

    @api.depends('date_from', 'date_to', 'department_id', 'period_type')
    def _compute_name(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                if rec.period_type == 'current_week_to_date':
                    base = "Aperçu RH — semaine en cours (au %s)" % rec.date_to.strftime('%d/%m/%Y')
                else:
                    base = "Résumé RH — semaine du %s au %s" % (
                        rec.date_from.strftime('%d/%m/%Y'), rec.date_to.strftime('%d/%m/%Y'),
                    )
                rec.name = f"{base} ({rec.department_id.name})" if rec.department_id else base
            else:
                rec.name = "Résumé RH hebdomadaire"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        period_type = self.env.context.get('default_period_type', 'last_week')
        if period_type == 'current_week_to_date':
            date_from, date_to = self._get_current_week_to_date()
        else:
            date_from, date_to = self._get_last_full_week()
        if 'date_from' in fields_list:
            res['date_from'] = date_from
        if 'date_to' in fields_list:
            res['date_to'] = date_to
        return res

    @api.model
    def _get_current_week_to_date(self, reference_date=None):
        """Renvoie (lundi de la semaine en cours, aujourd'hui) — utilisé pour
        un aperçu "à chaud" de la semaine NON encore terminée, contrairement
        à _get_last_full_week() qui ne renvoie jamais qu'une semaine
        entièrement écoulée. Un résumé basé sur cette période est
        nécessairement provisoire (voir period_type='current_week_to_date') :
        à ne jamais confondre avec le résumé hebdomadaire officiel."""
        today = reference_date or fields.Date.context_today(self)
        monday_this_week = today - timedelta(days=today.weekday())
        return monday_this_week, today

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

    @api.model
    def action_generate_current_week_snapshot(self, department_id=None):
        """Génère (ou régénère) un APERÇU PROVISOIRE de la semaine en cours,
        à la demande, sans attendre la clôture de la semaine ni le prochain
        passage du cron hebdomadaire.

        Cas d'usage typique corrigé ici : un recruteur vient d'embaucher un
        candidat aujourd'hui et veut voir immédiatement l'effet sur le
        résumé RH, plutôt que de tomber sur le dernier résumé OFFICIEL généré
        par le cron — qui porte forcément sur une semaine déjà close, donc
        potentiellement plusieurs jours dans le passé et ne pouvant par
        définition pas encore contenir l'embauche du jour.

        Un seul enregistrement 'current_week_to_date' est conservé par jour
        et par département (régénéré s'il existe déjà pour aujourd'hui),
        pour ne pas accumuler des aperçus obsolètes à chaque rafraîchissement
        manuel dans la même journée."""
        date_from, date_to = self._get_current_week_to_date()
        domain = [
            ('period_type', '=', 'current_week_to_date'),
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
            ('department_id', '=', department_id or False),
        ]
        record = self.search(domain, limit=1)
        if not record:
            record = self.create({
                'date_from': date_from,
                'date_to': date_to,
                'period_type': 'current_week_to_date',
                'department_id': department_id or False,
            })
        record.action_generate_summary()
        return record

    @api.model
    def _get_latest_snapshot(self, department_id=None):
        """Dernier aperçu 'semaine en cours' généré (le plus récent), à ne
        jamais mélanger avec _get_latest() (résumé OFFICIEL de la dernière
        semaine complète) — voir period_type."""
        domain = [('state', '=', 'generated'), ('period_type', '=', 'current_week_to_date')]
        domain.append(('department_id', '=', department_id or False))
        return self.search(domain, order='generated_on desc', limit=1)

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
            rec.write(stats)
            try:
                result = rec._call_gemini_weekly_summary(stats)
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
        Renvoie UN SEUL dict plat {champ: valeur}, écrit tel quel sur
        l'enregistrement (rec.write(stats)) ET utilisé tel quel pour
        formatter le prompt Gemini (voir _call_gemini_weekly_summary) —
        une seule source de vérité, plutôt qu'un dict 'fields' stocké et
        un dict 'details' séparé uniquement utilisé pour le prompt (ancien
        découpage qui faisait perdre le détail des embauches/candidatures
        après génération, et qui provoquait une KeyError au formatage du
        prompt : 'top_recruiting_jobs' et 'new_hires_detail' n'étaient
        jamais transmis à .format()).
        Chaque bloc est protégé par une vérification de présence du modèle
        pour rester robuste si un module optionnel n'est pas installé
        (même logique défensive que smart.hr.ai.dashboard)."""
        self.ensure_one()
        start = fields.Datetime.to_datetime(self.date_from)
        end = fields.Datetime.to_datetime(self.date_to) + timedelta(days=1) - timedelta(seconds=1)
        dept = self.department_id

        stats = {}

        # --- Recrutement ---
        applicant_domain = [('create_date', '>=', start), ('create_date', '<=', end)]
        if dept:
            applicant_domain.append(('department_id', '=', dept.id))
        applicants = self.env['hr.applicant'].sudo().with_context(active_test=False).search(applicant_domain)
        stats['new_applicants_count'] = len(applicants)

        # Répartition par poste : donne un aperçu de OÙ se concentre l'effort
        # de recrutement cette semaine, pas juste un total agrégé. Stockée
        # (pas juste passée au prompt) pour rester consultable sur la fiche
        # même après génération — équivalent texte de score_history_ids pour
        # la partie "candidatures".
        jobs_count = {}
        for applicant in applicants:
            job_name = applicant.job_id.name if applicant.job_id else "Sans poste précisé"
            jobs_count[job_name] = jobs_count.get(job_name, 0) + 1
        stats['top_recruiting_jobs'] = (
            ", ".join(f"{name} ({count})" for name, count in sorted(jobs_count.items(), key=lambda kv: -kv[1])[:8])
            or "Aucun"
        )

        interview_domain = [('create_date', '>=', start), ('create_date', '<=', end)]
        if dept:
            interview_domain.append(('applicant_id.department_id', '=', dept.id))
        interviews = self.env['hr.applicant.interview'].sudo().search(interview_domain) \
            if 'hr.applicant.interview' in self.env else self.env['hr.applicant.interview']
        stats['interviews_scheduled_count'] = len(interviews)

        hire_domain = [('create_date', '>=', start), ('create_date', '<=', end)]
        if dept:
            hire_domain.append(('department_id', '=', dept.id))
        new_hires = self.env['hr.employee'].sudo().search(hire_domain)
        stats['new_hires_count'] = len(new_hires)

        # Distingue les embauches réellement passées par le pipeline ATS/IA
        # (candidature -> pipeline -> contrat signé, tracé via
        # origin_applicant_id) des employés ajoutés manuellement à Odoo
        # (import, saisie directe...) — les deux sont légitimes, mais les
        # confondre sous un seul "Nouveaux employés embauchés" faussait la
        # lecture de la section "Recrutement" du résumé.
        hires_via_pipeline = new_hires.filtered(
            lambda e: getattr(e, 'origin_applicant_id', False)
        ) if hasattr(self.env['hr.employee'], 'origin_applicant_id') else self.env['hr.employee']
        stats['new_hires_via_ai_pipeline_count'] = len(hires_via_pipeline)

        stats['new_hires_detail'] = "; ".join(
            f"{emp.name} — {emp.job_title or (emp.job_id.name if emp.job_id else 'poste non précisé')}"
            f"{' (' + emp.department_id.name + ')' if emp.department_id else ''}"
            for emp in new_hires[:10]
        ) or "Aucune"

        # Score IA moyen : basé sur les ÉVÉNEMENTS DE NOTATION réellement
        # survenus cette semaine (hr.applicant.score.history, alimenté à
        # chaque action_compute_match_score), pas sur les candidatures
        # CRÉÉES cette semaine. Avant ce correctif, un candidat créé la
        # semaine précédente mais scoré cette semaine (CV traité en retard,
        # rescoring après changement de poste...) était invisible dans cette
        # moyenne — et une candidature créée cette semaine mais pas encore
        # scorée y était comptée à tort comme si elle avait un score connu.
        # Cette approche est cohérente avec le libellé du champ ("candidatures
        # évaluées cette semaine") et avec la logique déjà utilisée plus bas
        # pour la Performance (hr.appraisal.ai.analysis, un historique
        # d'événements équivalent).
        if 'hr.applicant.score.history' in self.env:
            score_history_domain = [('create_date', '>=', start), ('create_date', '<=', end)]
            if dept:
                score_history_domain.append(('applicant_id.department_id', '=', dept.id))
            score_events = self.env['hr.applicant.score.history'].sudo().search(score_history_domain)
        else:
            score_events = None
        week_scores = score_events.mapped('score') if score_events is not None else []
        week_scores = [s for s in week_scores if s]
        stats['avg_recruitment_score_week'] = (
            round(sum(week_scores) / len(week_scores), 1) if week_scores else 0.0
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
        stats['leaves_requested_count'] = leaves_count
        stats['leaves_approve_count'] = len(leaves.filtered(lambda l: l.ai_recommendation == 'approve')) if leaves is not None else 0
        stats['leaves_caution_count'] = len(leaves.filtered(lambda l: l.ai_recommendation == 'caution')) if leaves is not None else 0
        stats['leaves_refuse_count'] = len(leaves.filtered(lambda l: l.ai_recommendation == 'refuse')) if leaves is not None else 0

        # --- Présences ---
        if 'hr.attendance.anomaly' in self.env:
            anomaly_domain = [('detected_on', '>=', start), ('detected_on', '<=', end)]
            if dept:
                anomaly_domain.append(('employee_id.department_id', '=', dept.id))
            anomalies = self.env['hr.attendance.anomaly'].sudo().search(anomaly_domain)
        else:
            anomalies = None
        anomalies_count = len(anomalies) if anomalies is not None else 0
        stats['attendance_anomalies_count'] = anomalies_count
        stats['attendance_missing_checkout_count'] = (
            len(anomalies.filtered(lambda a: a.anomaly_type == 'missing_checkout')) if anomalies is not None else 0
        )
        stats['attendance_repeated_lateness_count'] = (
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
        stats['appraisals_generated_count'] = analyses_count
        perf_scores = analyses.mapped('performance_score') if analyses is not None else []
        perf_scores = [s for s in perf_scores if s]
        stats['avg_performance_score_week'] = round(sum(perf_scores) / len(perf_scores), 1) if perf_scores else 0.0
        stats['new_high_potentials_count'] = (
            len(analyses.filtered('high_potential')) if analyses is not None else 0
        )

        return stats

    def _call_gemini_weekly_summary(self, stats):
        self.ensure_one()
        today = fields.Date.context_today(self)
        is_partial = self.period_type == 'current_week_to_date' or (
            self.date_to and self.date_to >= today
        )
        prompt = WEEKLY_SUMMARY_PROMPT.format(
            date_from=self.date_from.strftime('%d/%m/%Y'),
            date_to=self.date_to.strftime('%d/%m/%Y'),
            is_partial_week=(
                "Oui — semaine EN COURS, données provisoires et incomplètes"
                if is_partial else
                "Non — semaine entièrement écoulée, bilan définitif"
            ),
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
            'period_type': self.period_type,
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
                'top_recruiting_jobs': self.top_recruiting_jobs,
                'interviews_scheduled_count': self.interviews_scheduled_count,
                'new_hires_count': self.new_hires_count,
                'new_hires_via_ai_pipeline_count': self.new_hires_via_ai_pipeline_count,
                'new_hires_detail': self.new_hires_detail,
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
    def _get_latest_any(self, department_id=None):
        """Le résumé le plus récent TOUS TYPES CONFONDUS (rapport officiel
        de la dernière semaine complète OU aperçu provisoire de la semaine
        en cours) — celui des deux réellement généré le plus récemment.

        Avant ce correctif, le dashboard et l'API mobile ne regardaient
        QUE le rapport officiel (_get_latest), qui ne peut par construction
        jamais porter sur la semaine en cours : après une embauche du jour,
        l'utilisateur retombait systématiquement sur le dernier rapport
        officiel — potentiellement vieux de plusieurs jours, voire de
        plusieurs semaines si le cron hebdomadaire n'a pas encore tourné —
        sans aucun moyen de savoir qu'un aperçu plus frais existait."""
        official = self._get_latest(department_id=department_id)
        snapshot = self._get_latest_snapshot(department_id=department_id)
        candidates = [r for r in (official, snapshot) if r]
        if not candidates:
            return self.browse()
        return max(candidates, key=lambda r: r.generated_on or r.create_date)

    @api.model
    def _get_latest(self, department_id=None):
        """Dernier résumé OFFICIEL généré (period_type != 'current_week_to_date',
        le plus récent par date_from), optionnellement filtré par département.
        Ne renvoie JAMAIS un aperçu provisoire — voir _get_latest_any() pour
        le plus récent tous types confondus, généralement préférable pour
        l'affichage (dashboard, API mobile)."""
        domain = [('state', '=', 'generated'), ('period_type', '!=', 'current_week_to_date')]
        if department_id:
            domain.append(('department_id', '=', department_id))
        else:
            domain.append(('department_id', '=', False))
        return self.search(domain, order='date_from desc', limit=1)

    def action_open_latest(self):
        """Ouvre le résumé le plus récent (toutes équipes), officiel ou
        aperçu provisoire selon lequel est le plus frais — utilisé par le
        smart button du tableau de bord global."""
        latest = self._get_latest_any()
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

    def action_open_or_generate_current_week_snapshot(self):
        """Point d'entrée UI (bouton) : génère (ou régénère s'il existe déjà
        pour aujourd'hui) l'aperçu de la semaine en cours et ouvre
        directement la fiche obtenue.

        Distinct de action_generate_current_week_snapshot() ci-dessus, qui
        est @api.model et renvoie l'enregistrement lui-même (utilisée par
        le tableau de bord et par du code Python) : ici on renvoie une
        action de fenêtre exploitable directement par un bouton.

        Si appelé depuis un enregistrement existant (bouton sur une fiche
        déjà filtrée par département), régénère l'aperçu pour CE département ;
        sinon (bouton du tableau de bord, aucun enregistrement en contexte),
        génère l'aperçu toutes équipes confondues."""
        department_id = self[:1].department_id.id if self and self[:1].department_id else None
        record = self.action_generate_current_week_snapshot(department_id=department_id)
        return {
            'name': record.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.weekly.summary',
            'res_id': record.id,
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
        Génère le résumé OFFICIEL de la dernière semaine complète, toutes
        équipes confondues, sans doublon si un enregistrement existe déjà
        pour cette période (ex: relance manuelle du cron)."""
        date_from, date_to = self._get_last_full_week()
        existing = self.search([
            ('date_from', '=', date_from), ('date_to', '=', date_to),
            ('department_id', '=', False), ('period_type', '=', 'last_week'),
        ], limit=1)
        record = existing or self.create({
            'date_from': date_from, 'date_to': date_to, 'period_type': 'last_week',
        })
        try:
            record.action_generate_summary()
        except Exception as e:
            _logger.error(
                "Échec de la génération automatique du résumé hebdomadaire RH (%s - %s) : %s",
                date_from, date_to, e,
            )

    @api.model
    def _cron_generate_weekly_summary_snapshot(self):
        """Point d'entrée du cron quotidien (voir
        data/ir_cron_weekly_summary.xml) qui maintient un APERÇU de la
        semaine en cours à jour en permanence, sans action manuelle.

        Corrige le problème constaté en usage réel : un recruteur embauche
        un candidat, ouvre les Résumés hebdomadaires RH et ne trouve que le
        rapport OFFICIEL de la dernière semaine close (potentiellement
        vieux de plusieurs jours), sans savoir qu'un bouton "Aperçu semaine
        en cours" existe. Avec ce cron, le dashboard (_get_latest_any)
        affiche systématiquement un aperçu daté d'aujourd'hui au plus tard,
        sans que personne n'ait besoin de cliquer sur quoi que ce soit —
        le bouton manuel reste disponible pour un rafraîchissement immédiat
        à la demande (ex: juste après une embauche, sans attendre le
        prochain passage du cron)."""
        try:
            self.action_generate_current_week_snapshot()
        except Exception as e:
            _logger.error(
                "Échec de la génération automatique de l'aperçu (semaine en "
                "cours) du résumé hebdomadaire RH : %s", e,
            )