# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

# Noms d'étapes "entretien" courants, en français et en anglais, utilisés
# uniquement comme valeur de départ pratique à l'installation du module.
# Ce n'est PAS une dépendance au runtime : une fois installé, tout se pilote
# via la case à cocher "Étape d'entretien" (is_interview_stage), configurable
# librement par les recruteurs, quelle que soit la langue ou le nom donné
# à l'étape par la suite.
_DEFAULT_INTERVIEW_STAGE_NAMES = [
    'First Interview', 'Second Interview',
    'Premier entretien', 'Second entretien', 'Deuxième entretien',
]


def _mark_default_interview_stages(env):
    """Coche automatiquement is_interview_stage sur les étapes existantes
    dont le nom correspond à un entretien connu (best effort, non bloquant)."""
    try:
        stages = env['hr.recruitment.stage'].search([
            ('name', 'in', _DEFAULT_INTERVIEW_STAGE_NAMES),
        ])
        if stages:
            stages.write({'is_interview_stage': True})
            _logger.info(
                "Assistant RH IA : %s étape(s) marquée(s) automatiquement "
                "comme 'Étape d'entretien' (%s).",
                len(stages), ', '.join(stages.mapped('name')),
            )
    except Exception:
        # Best effort uniquement : un échec ici ne doit jamais empêcher
        # l'installation du module. Les recruteurs peuvent toujours cocher
        # la case manuellement depuis Configuration > Étapes de recrutement.
        _logger.warning(
            "Assistant RH IA : impossible de pré-configurer les étapes "
            "d'entretien automatiquement, configuration manuelle nécessaire.",
            exc_info=True,
        )


def post_init_hook(env):
    _mark_default_interview_stages(env)
