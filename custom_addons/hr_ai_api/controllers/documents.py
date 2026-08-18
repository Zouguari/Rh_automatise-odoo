# -*- coding: utf-8 -*-
import json
import logging
import base64

from odoo import http, SUPERUSER_ID
from odoo.http import request
from ..utils.auth_decorator import require_auth

_logger = logging.getLogger(__name__)

STATUS_LABELS = {
    'pending': 'En attente',
    'processing': 'En cours de traitement',
    'ready': 'Prêt à récupérer',
    'delivered': 'Délivré',
    'rejected': 'Refusé',
}

TYPE_LABELS = {
    'attestation_travail': 'Attestation de travail',
    'bulletin_paie': 'Bulletin de paie',
    'certificat_travail': 'Certificat de travail',
    'attestation_salaire': 'Attestation de salaire',
    'attestation_cnss': 'Attestation CNSS',
    'contrat_travail': 'Copie du contrat de travail',
    'autre': 'Autre document',
}


class HrDocumentRequestController(http.Controller):

    @http.route('/api/v1/documents/my', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth()
    def get_my_document_requests(self, **kwargs):
        payload = request.jwt_payload
        employee_id = payload.get('employee_id')
        if not employee_id:
            return request.make_json_response({'error': 'no_employee_linked', 'message': "Aucun profil employé associé."}, status=400)

        records = request.env['hr.document.request'].sudo().search(
            [('employee_id', '=', employee_id)], order='create_date desc'
        )

        res = []
        for r in records:
            res.append({
                'id': r.id,
                'document_type': r.document_type,
                'document_type_label': TYPE_LABELS.get(r.document_type, r.document_type),
                'custom_type_label': r.custom_type_label,
                'period_month': r.period_month,
                'period_year': r.period_year,
                'comment': r.comment,
                'status': r.status,
                'status_label': STATUS_LABELS.get(r.status, r.status),
                'rejection_reason': r.rejection_reason,
                'has_file': bool(r.file_attachment_base64),
                'file_name': r.file_name or "Document.pdf",
                'request_date': r.request_date.strftime('%Y-%m-%d') if r.request_date else None,
                'processed_date': r.processed_date.strftime('%Y-%m-%d') if r.processed_date else None,
            })

        return request.make_json_response({'requests': res})

    @http.route('/api/v1/documents/request', type='http', auth='none', methods=['POST'], csrf=False)
    @require_auth()
    def create_document_request(self, **kwargs):
        payload = request.jwt_payload
        employee_id = payload.get('employee_id')
        if not employee_id:
            return request.make_json_response({'error': 'no_employee_linked', 'message': "Aucun profil employé associé."}, status=400)

        raw = request.httprequest.get_data()
        data = json.loads(raw.decode('utf-8')) if raw else {}

        doc_type = data.get('document_type')
        if not doc_type:
            return request.make_json_response({'error': 'missing_fields', 'message': "Le type de document est requis."}, status=400)

        vals = {
            'employee_id': employee_id,
            'document_type': doc_type,
            'custom_type_label': data.get('custom_type_label'),
            'period_month': str(data.get('period_month')) if data.get('period_month') else False,
            'period_year': int(data.get('period_year')) if data.get('period_year') else False,
            'comment': data.get('comment'),
            'status': 'pending',
        }

        # Use with_user(SUPERUSER_ID) to ensure mail thread / chatter has valid env.user
        rec = request.env['hr.document.request'].with_user(SUPERUSER_ID).create(vals)

        return request.make_json_response({
            'success': True,
            'message': "Votre demande de document a été enregistrée.",
            'id': rec.id,
            'status': rec.status,
            'status_label': STATUS_LABELS.get(rec.status, rec.status),
        })

    @http.route('/api/v1/documents/<int:doc_id>/download', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth()
    def download_document(self, doc_id, **kwargs):
        payload = request.jwt_payload
        employee_id = payload.get('employee_id')

        rec = request.env['hr.document.request'].sudo().browse(doc_id)
        if not rec.exists() or rec.employee_id.id != employee_id:
            return request.make_json_response({'error': 'not_found', 'message': "Document non trouvé."}, status=404)

        if not rec.file_attachment_base64:
            return request.make_json_response({'error': 'no_file', 'message': "Le fichier n'a pas encore été généré."}, status=404)

        file_content = base64.b64decode(rec.file_attachment_base64)
        filename = rec.file_name or f"Document_{rec.id}.pdf"

        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'attachment; filename="{filename}"'),
            ('Content-Length', str(len(file_content))),
        ]
        return request.make_response(file_content, headers=headers)
