# -*- coding: utf-8 -*-
{
    'name': "Assistant RH IA - Gestion des congés",
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Analyse automatique des demandes de congés : recommandation, "
               "détection de conflits d'équipe.",
    'description': """
        Module métier (aucune route HTTP ici, voir hr_ai_api pour l'exposition
        API) qui enrichit hr.leave avec :
        - Une recommandation automatique (approuver / vigilance / refuser)
        - La détection de conflits de planning au sein du département
        - Un historique des recommandations IA (hr.leave.ai.recommendation)

        Logique volontairement simple (heuristique à base de règles) pour
        cette première itération — pourra être enrichie plus tard (ex : appel
        à un modèle IA, comme dans hr_recruitment_ai_assistant) sans changer
        les champs ni l'API exposée.
    """,
    'author': 'Votre Nom / Équipe',
    'depends': ['hr_holidays'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
