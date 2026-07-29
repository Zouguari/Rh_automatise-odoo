# -*- coding: utf-8 -*-


def post_init_hook(env):
    """Configure le pipeline de recrutement standard (7 étapes) UNIQUEMENT
    à l'installation initiale du module — un post_init_hook ne s'exécute
    jamais lors d'un simple "-u" sur une base existante, ce qui est
    volontaire ici : une fois installée, la configuration du pipeline
    appartient au recruteur (renommage, réorganisation, désactivation
    d'une automatisation...) et ne doit plus être modifiée dans son dos
    par une mise à jour du module.

    Pour corriger une configuration cassée sur une base existante, utiliser
    le bouton manuel "Réparer la configuration du pipeline standard"
    (menu Actions ⚙️ sur Configuration > Étapes), qui appelle la même
    méthode _setup_default_pipeline_stages() de façon explicite."""
    env['hr.recruitment.stage']._setup_default_pipeline_stages()