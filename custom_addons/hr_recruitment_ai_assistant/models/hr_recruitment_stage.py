# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class HrRecruitmentStage(models.Model):
    _inherit = 'hr.recruitment.stage'

    auto_email_template_id = fields.Many2one(
        'mail.template',
        string="Template email automatique",
        help="Email envoyé automatiquement quand un candidat atteint cette étape."
    )
    is_interview_stage = fields.Boolean(
        string="Étape d'entretien",
        help="Coche cette case si atteindre cette étape doit déclencher automatiquement "
             "la génération de questions IA et la planification d'un entretien. "
             "Remplace une ancienne logique basée sur le nom de l'étape (peu fiable "
             "si l'étape est renommée ou si Odoo est utilisé dans une autre langue)."
    )
    interview_type = fields.Selection([
        ('rh', 'Entretien RH'),
        ('technique', 'Entretien Technique'),
    ], string="Type d'entretien",
        help="Précise la nature de l'entretien pour cette étape (utilisé dans "
             "l'email de convocation envoyé au candidat, et pour adapter le "
             "contenu généré par l'IA). Laisse vide si cette étape n'est pas "
             "un entretien.")
    is_refusal_stage = fields.Boolean(
        string="Étape de refus",
        help="Coche cette case sur l'étape 'Refusé' (ou équivalent) du pipeline. "
             "Quand un candidat est refusé via l'assistant de refus, il est "
             "déplacé automatiquement vers cette étape plutôt que simplement "
             "archivé, pour garder une trace visible dans le pipeline ATS. "
             "Si aucune étape n'est marquée ainsi, le candidat est archivé "
             "(comportement standard Odoo).",
    )
    is_contract_signed_stage = fields.Boolean(
        string="Étape de contrat signé",
        help="Coche cette case sur l'étape représentant un contrat réellement "
             "signé (ex: 'Contrat signé'). Dès qu'un candidat atteint cette "
             "étape, le module crée automatiquement son employé (si pas déjà "
             "fait), génère le contrat, et le fait passer à l'état 'En cours' "
             "— ce qui déclenche aussi l'email d'acceptation au candidat. "
             "Ne coche cette case que sur une étape que le recruteur ne "
             "déplace un candidat vers elle qu'une fois le contrat réellement "
             "signé côté RH : cette automatisation est irréversible en un "
             "clic (création employé + validation contrat)."
    )

    @api.constrains('is_interview_stage', 'is_refusal_stage', 'is_contract_signed_stage')
    def _check_single_automatic_role(self):
        """Empêche de cocher plusieurs rôles automatiques contradictoires sur
        la même étape (ex: une étape marquée à la fois 'Entretien' et
        'Contrat signé' déclencherait planification d'entretien ET
        signature de contrat au même moment, ce qui n'a pas de sens
        métier). Chaque étape ne doit avoir qu'un seul rôle automatique
        actif à la fois."""
        for stage in self:
            active_roles = sum([
                stage.is_interview_stage,
                stage.is_refusal_stage,
                stage.is_contract_signed_stage,
            ])
            if active_roles > 1:
                raise ValidationError(
                    f"L'étape « {stage.name} » ne peut pas cumuler plusieurs "
                    "rôles automatiques (Entretien / Refus / Contrat signé). "
                    "Choisis-en un seul par étape pour éviter des "
                    "déclenchements contradictoires (ex: envoi d'une "
                    "convocation d'entretien ET signature de contrat en "
                    "même temps)."
                )

    # Pipeline standard du module : nom cible, noms existants à renommer
    # s'ils sont trouvés (valeurs par défaut Odoo, EN et FR), séquence,
    # et champs additionnels à appliquer. Appelée depuis post_init_hook
    # (installation initiale UNIQUEMENT — voir hooks.py) et depuis l'action
    # manuelle "Réparer la configuration du pipeline standard" (Configuration
    # > menu dédié), jamais automatiquement lors d'une simple mise à jour du
    # module : une fois installée, la configuration du pipeline appartient
    # au recruteur.
    _PIPELINE_STAGES_CONFIG = [
        ("Nouveau", ["New"], 1, {}),
        ("Qualification initiale", ["Initial Qualification"], 2, {}),
        ("Entretien RH", ["First Interview", "Premier entretien"], 3,
         {'is_interview_stage': True, 'interview_type': 'rh'}),
        ("Entretien Technique",
         ["Second Interview", "Second entretien", "Deuxième entretien"], 4,
         {'is_interview_stage': True, 'interview_type': 'technique'}),
        ("Proposition de contrat", ["Contract Proposal"], 5, {}),
        ("Contrat signé", ["Contract Signed"], 6,
         {'is_contract_signed_stage': True}),
        ("Refusé", ["Refused"], 7,
         {'is_refusal_stage': True}),
    ]

    def _pipeline_role_domain(self, extra_vals):
        """Construit un domaine de recherche à partir du RÔLE (les champs
        booléens/selection qui pilotent l'automatisation), pas du nom.
        Retourne [] si l'entrée de config n'a aucun rôle distinctif
        (ex: 'Nouveau', 'Qualification initiale' — ce sont de simples
        étapes sans automatisation, seul le nom permet de les repérer)."""
        if extra_vals.get('is_refusal_stage'):
            return [('is_refusal_stage', '=', True)]
        if extra_vals.get('is_contract_signed_stage'):
            return [('is_contract_signed_stage', '=', True)]
        if extra_vals.get('is_interview_stage'):
            domain = [('is_interview_stage', '=', True)]
            if extra_vals.get('interview_type'):
                domain.append(('interview_type', '=', extra_vals['interview_type']))
            return domain
        return []

    @api.model
    def _setup_default_pipeline_stages(self):
        """Garantit la présence et la configuration correcte des 7 étapes
        du pipeline standard, sans jamais créer de doublon. Ordre de
        recherche pour chaque entrée :
        1. Une étape porte-t-elle DÉJÀ ce rôle (is_refusal_stage,
           is_contract_signed_stage, is_interview_stage+interview_type) ?
           Si oui, on la laisse telle quelle — quel que soit son nom
           actuel. C'est le cas prioritaire : un recruteur qui a renommé
           "Refusé" en "Candidature refusée" tout en gardant la case
           "Étape de refus" cochée ne doit JAMAIS se retrouver avec une
           deuxième étape "Refusé" recréée à côté.
        2. Sinon, une étape porte-t-elle déjà le nom cible ? -> on met
           juste à jour son rôle (idempotent).
        3. Sinon, une étape porte-t-elle un ancien nom par défaut Odoo
           (EN/FR) ? -> on la renomme ET on la configure (réutilise
           l'étape existante, préserve les candidats déjà dessus).
        4. Sinon -> on la crée.
        Best effort : une erreur sur une étape ne doit jamais empêcher le
        chargement du module ni bloquer les étapes suivantes."""
        for target_name, alt_names, sequence, extra_vals in self._PIPELINE_STAGES_CONFIG:
            try:
                role_domain = self._pipeline_role_domain(extra_vals)
                stage = self.search(role_domain, limit=1) if role_domain else self.browse()

                if stage:
                    # Retrouvée par son RÔLE déjà actif : on ne touche ni
                    # à son nom (le recruteur a pu le choisir
                    # volontairement) ni à sa séquence. Rien à faire de
                    # plus, elle est déjà correctement configurée.
                    continue

                stage = self.search([('name', '=', target_name)], limit=1)
                if stage:
                    # Nom cible déjà présent : simple mise à jour du rôle,
                    # pas de la séquence (cf. explication ci-dessous).
                    stage.write(extra_vals)
                    continue

                if alt_names:
                    stage = self.search([('name', 'in', alt_names)], limit=1)
                    if stage:
                        # Ancien nom par défaut Odoo trouvé : on adopte et
                        # renomme cette étape plutôt que d'en créer une
                        # nouvelle (préserve les candidats déjà dessus).
                        # Ne PAS réécrire 'sequence' sur une étape déjà
                        # existante : si le recruteur a réorganisé son
                        # pipeline manuellement depuis, une mise à niveau
                        # ultérieure ne doit pas silencieusement annuler
                        # ce réordonnancement.
                        stage.write(dict(extra_vals, name=target_name))
                        continue

                # Aucune étape existante ne correspond, ni par rôle ni
                # par nom : on en crée une nouvelle avec la séquence par
                # défaut.
                self.create(dict(extra_vals, name=target_name, sequence=sequence))
            except Exception:
                _logger.warning(
                    "Assistant RH IA : impossible de configurer "
                    "automatiquement l'étape « %s », configuration "
                    "manuelle nécessaire (Configuration > Étapes de "
                    "recrutement).", target_name, exc_info=True,
                )