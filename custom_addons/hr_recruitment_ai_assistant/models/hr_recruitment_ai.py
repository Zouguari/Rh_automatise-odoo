# -*- coding: utf-8 -*-

from odoo import models, fields, api

class HrRecruitmentAiGenerator(models.Model):
    _name = 'hr.recruitment.ai.generator'
    _description = 'Générateur de Description de Poste IA'

    name = fields.Char(string="Titre du poste ciblé", required=True)
    key_skills = fields.Text(string="Compétences & Mots-clés")
    generated_description = fields.Html(string="Description générée par l'IA", readonly=True)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('generated', 'Généré par l\'IA')
    ], string="Statut", default='draft', readonly=True)

    def action_generate_description(self):
        for record in self:
            if not record.name:
                continue
            
            skills = record.key_skills or "Non spécifiées"
            skills_html = skills.replace('\n', '<br/>')
            
            # Générer une description HTML structurée
            html_content = f"""
                <div style="font-family: sans-serif; line-height: 1.6; color: #333;">
                    <h2 style="color: #0070C0; border-bottom: 2px solid #0070C0; padding-bottom: 5px;">Description du Poste : {record.name}</h2>
                    <p>Nous recherchons un professionnel qualifié pour rejoindre notre équipe dynamique en tant que <strong>{record.name}</strong>.</p>
                    
                    <h3 style="color: #0070C0;">🎯 Missions principales</h3>
                    <ul>
                        <li>Définir et concevoir des solutions innovantes adaptées aux besoins.</li>
                        <li>Assurer le développement et le déploiement continu des applications.</li>
                        <li>Collaborer activement avec les autres services pour garantir le succès des projets.</li>
                        <li>Maintenir une veille technologique et s'adapter aux évolutions du marché.</li>
                    </ul>

                    <h3 style="color: #0070C0;">🛠️ Compétences clés requises</h3>
                    <p style="background-color: #f9f9f9; padding: 10px; border-left: 4px solid #0070C0; font-style: italic;">
                        {skills_html}
                    </p>

                    <h3 style="color: #0070C0;">💼 Profil recherché</h3>
                    <ul>
                        <li>Diplômé d'études supérieures ou autodidacte passionné.</li>
                        <li>Expérience de travail dans un environnement collaboratif et dynamique.</li>
                        <li>Capacités d'adaptation, de résolution de problèmes et d'autonomie.</li>
                    </ul>

                    <h3 style="color: #0070C0;">✨ Avantages</h3>
                    <ul>
                        <li>Environnement propice à l'apprentissage et à l'évolution.</li>
                        <li>Horaires flexibles et possibilités de travail à distance.</li>
                        <li>Équipe internationale et passionnée.</li>
                    </ul>
                </div>
            """
            
            record.generated_description = html_content
            record.state = 'generated'
