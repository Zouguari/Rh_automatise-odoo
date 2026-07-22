# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

# Noms d'étapes "entretien" courants, en français et en anglais, utilisés
# uniquement comme valeur de départ pratique à l'installation du module.
# Ce n'est PAS une dépendance au runtime : une fois installé, tout se pilote
# via la case à cocher "Étape d'entretien" (is_interview_stage), configurable
# librement par les recruteurs, quelle que soit la langue ou le nom donné
# à l'étape par la suite.
# Noms d'étapes "entretien" courants, en français et en anglais, utilisés
# uniquement comme valeur de départ pratique à l'installation du module.
# Ce n'est PAS une dépendance au runtime : une fois installé, tout se pilote
# via la case à cocher "Étape d'entretien" (is_interview_stage), configurable
# librement par les recruteurs, quelle que soit la langue ou le nom donné
# à l'étape par la suite.
# Ordre du process : l'entretien RH (1er) filtre motivation/disponibilité
# avant de mobiliser un interviewer technique (2e) — ordre inversable si le
# process réel de l'équipe est différent, simple champ à changer.
_FIRST_INTERVIEW_NAMES = ['First Interview', 'Premier entretien']
_SECOND_INTERVIEW_NAMES = ['Second Interview', 'Second entretien', 'Deuxième entretien']


def _mark_default_interview_stages(env):
    """Sur une installation neuve : renomme et type les 2 étapes d'entretien
    standard de hr_recruitment (best effort, non bloquant, ne s'applique
    jamais à une base déjà en place — configuration manuelle nécessaire
    dans ce cas, voir Configuration > Étapes de recrutement)."""
    try:
        rh_stages = env['hr.recruitment.stage'].search([
            ('name', 'in', _FIRST_INTERVIEW_NAMES),
        ])
        if rh_stages:
            rh_stages.write({
                'name': 'Entretien RH',
                'is_interview_stage': True,
                'interview_type': 'rh',
            })

        technique_stages = env['hr.recruitment.stage'].search([
            ('name', 'in', _SECOND_INTERVIEW_NAMES),
        ])
        if technique_stages:
            technique_stages.write({
                'name': 'Entretien Technique',
                'is_interview_stage': True,
                'interview_type': 'technique',
            })

        total = len(rh_stages) + len(technique_stages)
        if total:
            _logger.info(
                "Assistant RH IA : %s étape(s) configurée(s) automatiquement "
                "comme entretien RH/Technique.", total,
            )
    except Exception:
        # Best effort uniquement : un échec ici ne doit jamais empêcher
        # l'installation du module. Les recruteurs peuvent toujours
        # configurer manuellement depuis Configuration > Étapes de recrutement.
        _logger.warning(
            "Assistant RH IA : impossible de pré-configurer les étapes "
            "d'entretien automatiquement, configuration manuelle nécessaire.",
            exc_info=True,
        )


def post_init_hook(env):
    _mark_default_interview_stages(env)
