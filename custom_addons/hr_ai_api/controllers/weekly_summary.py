# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from ..utils.auth_decorator import require_auth


class HrAiApiWeeklySummaryController(http.Controller):
    """Endpoints de consultation du résumé hebdomadaire RH généré par IA.

    Lecture seule : la génération elle-même reste une action back-office
    (bouton "Générer le résumé IA" ou cron), pas une action mobile.
    Protégé par le scope 'analytics:read' (RH uniquement, voir utils/roles.py) :
    ce contenu agrège des données sensibles multi-employés (performance,
    congés, anomalies de présence), donc pas accessible à un simple profil
    employé même pour consulter sa propre équipe.
    """

    @http.route('/api/v1/weekly-summary/latest', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['analytics:read'])
    def get_latest_weekly_summary(self, **kwargs):
        department_id = kwargs.get('department_id')
        department_id = int(department_id) if department_id else None

        summary = request.env['hr.weekly.summary'].sudo()._get_latest(department_id=department_id)
        if not summary:
            return request.make_json_response(
                {'error': 'not_found', 'message': "Aucun résumé hebdomadaire généré pour le moment."},
                status=404,
            )
        return request.make_json_response(summary._to_api_dict())

    @http.route('/api/v1/weekly-summary/<int:summary_id>', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['analytics:read'])
    def get_weekly_summary(self, summary_id, **kwargs):
        summary = request.env['hr.weekly.summary'].sudo().browse(summary_id)
        if not summary.exists():
            return request.make_json_response(
                {'error': 'not_found', 'message': "Résumé hebdomadaire introuvable."}, status=404
            )
        return request.make_json_response(summary._to_api_dict())

    @http.route('/api/v1/weekly-summary', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth(['analytics:read'])
    def list_weekly_summaries(self, **kwargs):
        """Liste paginée, résumés les plus récents en premier. Ne renvoie
        que les résumés déjà générés (les brouillons/erreurs restent un
        détail back-office)."""
        domain = [('state', '=', 'generated')]

        department_id = kwargs.get('department_id')
        if department_id:
            domain.append(('department_id', '=', int(department_id)))

        try:
            limit = min(int(kwargs.get('limit', 10)), 50)
            offset = max(int(kwargs.get('offset', 0)), 0)
        except (TypeError, ValueError):
            return request.make_json_response(
                {'error': 'bad_request', 'message': "'limit' et 'offset' doivent être des entiers."},
                status=400,
            )

        summaries = request.env['hr.weekly.summary'].sudo().search(
            domain, order='date_from desc', limit=limit, offset=offset,
        )
        total = request.env['hr.weekly.summary'].sudo().search_count(domain)

        return request.make_json_response({
            'total': total,
            'limit': limit,
            'offset': offset,
            'results': [
                {
                    'id': s.id,
                    'name': s.name,
                    'date_from': s.date_from.isoformat() if s.date_from else None,
                    'date_to': s.date_to.isoformat() if s.date_to else None,
                    'department': s.department_id.name or None,
                    'generated_on': s.generated_on.isoformat() if s.generated_on else None,
                }
                for s in summaries
            ],
        })
