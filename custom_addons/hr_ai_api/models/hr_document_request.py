# -*- coding: utf-8 -*-
from odoo import api, fields, models, SUPERUSER_ID


class HrDocumentRequest(models.Model):
    _name = 'hr.document.request'
    _inherit = ['mail.thread']
    _description = "Demandes de documents administratifs"
    _order = 'create_date desc'

    employee_id = fields.Many2one(
        'hr.employee', string="Employé", required=True, ondelete='cascade', index=True, tracking=True,
    )
    document_type = fields.Selection([
        ('attestation_travail', 'Attestation de travail'),
        ('bulletin_paie', 'Bulletin de paie'),
        ('certificat_travail', 'Certificat de travail'),
        ('attestation_salaire', 'Attestation de salaire'),
        ('attestation_cnss', 'Attestation CNSS'),
        ('contrat_travail', 'Copie du contrat de travail'),
        ('autre', 'Autre document'),
    ], string="Type de document", required=True, default='attestation_travail', tracking=True)

    custom_type_label = fields.Char(string="Préciser le document", help="Indiqué si 'Autre document' est sélectionné.")
    period_month = fields.Selection([
        ('1', 'Janvier'), ('2', 'Février'), ('3', 'Mars'), ('4', 'Avril'),
        ('5', 'Mai'), ('6', 'Juin'), ('7', 'Juillet'), ('8', 'Août'),
        ('9', 'Septembre'), ('10', 'Octobre'), ('11', 'Novembre'), ('12', 'Décembre')
    ], string="Mois concerné")
    period_year = fields.Integer(string="Année concernée", default=lambda self: fields.Datetime.now().year)

    comment = fields.Text(string="Motif / Destination", help="Indiquer par exemple la destination du document (Banque, Visa, etc.)")
    status = fields.Selection([
        ('pending', 'En attente'),
        ('processing', 'En cours de traitement'),
        ('ready', 'Prêt à récupérer'),
        ('delivered', 'Délivré'),
        ('rejected', 'Refusé'),
    ], string="Statut de la demande", default='pending', required=True, tracking=True)

    rejection_reason = fields.Text(string="Motif de refus")

    file_attachment_base64 = fields.Binary(string="Fichier joint / Document PDF", attachment=True)
    file_name = fields.Char(string="Nom du fichier")

    request_date = fields.Datetime(string="Date de la demande", default=fields.Datetime.now, readonly=True)
    processed_date = fields.Datetime(string="Date de traitement", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(HrDocumentRequest, self).create(vals_list)
        for rec in records:
            try:
                rec.with_user(SUPERUSER_ID).message_post(
                    body="📄 Nouvelle demande de document administrative créée : <b>%s</b>." % (
                        dict(rec._fields['document_type'].selection).get(rec.document_type)
                    )
                )
            except Exception:
                pass
        return records

    def write(self, vals):
        if 'status' in vals and vals['status'] in ('ready', 'delivered', 'rejected'):
            vals['processed_date'] = fields.Datetime.now()
        return super(HrDocumentRequest, self).write(vals)
