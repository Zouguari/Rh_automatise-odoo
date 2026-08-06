# -*- coding: utf-8 -*-
{
    'name': "Assistant RH IA - Évaluation des performances",
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Génération automatique d'évaluations, score de performance, identification des hauts potentiels.",
    'description': """
Module metier (aucune route HTTP ici, voir hr_ai_api) qui definit son propre modele d'evaluation (hr.appraisal) avec un score de performance calcule automatiquement (ai_performance_score), un indicateur de haut potentiel (ai_high_potential) et une synthese textuelle (ai_summary). Le score combine deux signaux deja disponibles dans le systeme : la ponctualite (module Presences) et la couverture des competences requises par le poste (module Competences). Un historique des analyses est conserve dans hr.appraisal.ai.analysis.
    """,
    'author': 'Votre Nom / Équipe',
    'depends': ['hr', 'hr_attendance_ai', 'hr_skills_ai'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_appraisal_ai_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
