"""
VVS Pipeline Backend - Updated with Materials Support
Generates PDF reports and sends via email
"""

import os
import json
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime
from io import BytesIO

# PDF Generation
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage

# Email
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# Image processing
from PIL import Image

# ============================================
# CONFIG
# ============================================
CONFIG = {
    'port': int(os.environ.get('PORT', 10000)),
    'output_dir': './outputs',
    'smtp': {
        'host': os.environ.get('SMTP_HOST', 'smtp.gmail.com'),
        'port': int(os.environ.get('SMTP_PORT', 587)),
        'user': os.environ.get('SMTP_USER', ''),
        'password': os.environ.get('SMTP_PASSWORD', '')
    },
    'office_email': os.environ.get('DEFAULT_OFFICE_EMAIL', '')
}

os.makedirs(CONFIG['output_dir'], exist_ok=True)

# ============================================
# PDF GENERATOR
# ============================================
class PDFGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_styles()
    
    def _setup_styles(self):
        self.styles.add(ParagraphStyle(
            name='CompanyName',
            parent=self.styles['Normal'],
            fontSize=14,
            fontName='Helvetica-Bold',
            spaceAfter=2*mm
        ))
        
        self.styles.add(ParagraphStyle(
            name='CompanyInfo',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=HexColor('#666666'),
            spaceAfter=1*mm
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Normal'],
            fontSize=11,
            fontName='Helvetica-Bold',
            spaceBefore=8*mm,
            spaceAfter=3*mm,
            textColor=HexColor('#333333')
        ))
        
        self.styles.add(ParagraphStyle(
            name='FieldLabel',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=HexColor('#666666')
        ))
        
        self.styles.add(ParagraphStyle(
            name='FieldValue',
            parent=self.styles['Normal'],
            fontSize=10,
            fontName='Helvetica-Bold'
        ))
    
    def generate(self, job_data):
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=20*mm)
        story = []
        
        # Company header
        company = job_data.get('company', {})
        story.append(Paragraph(company.get('name', 'VVS Bedrift'), self.styles['CompanyName']))
        story.append(Paragraph(f"Org.nr: {company.get('orgNr', 'N/A')}", self.styles['CompanyInfo']))
        story.append(Spacer(1, 3*mm))
        
        # Blue header bar
        header_table = Table([['']], colWidths=[170*mm], rowHeights=[10*mm])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), HexColor('#0d1f26'))
        ]))
        story.append(header_table)
        story.append(Spacer(1, 5*mm))
        
        # Customer section with light background
        story.append(Paragraph("KUNDE / ADRESSE", self.styles['FieldLabel']))
        customer_table = Table([[job_data.get('customer', 'N/A')]], colWidths=[170*mm])
        customer_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), HexColor('#F5F5F5')),
            ('BOX', (0,0), (-1,-1), 1, HexColor('#E0E0E0')),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('FONT', (0,0), (-1,-1), 'Helvetica-Bold', 11)
        ]))
        story.append(customer_table)
        story.append(Spacer(1, 5*mm))
        
        # Date/Time
        timestamp = job_data.get('timestamp', '')
        if timestamp:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            date_time_str = dt.strftime('%d.%m.%Y kl. %H:%M')
        else:
            date_time_str = 'N/A'
        
        story.append(Paragraph("DATO / TID", self.styles['FieldLabel']))
        story.append(Paragraph(date_time_str, self.styles['FieldValue']))
        story.append(Spacer(1, 5*mm))
        
        # Work description
        job_desc = job_data.get('jobDescription', '')
        if job_desc:
            story.append(Paragraph("<i>ARBEID UTFØRT</i>", ParagraphStyle('BlueItalic', parent=self.styles['Normal'], fontSize=11, textColor=HexColor('#0d1f26'), fontName='Helvetica-Oblique')))
            story.append(Paragraph(job_desc, self.styles['Normal']))
            story.append(Spacer(1, 5*mm))
        
        # Time and distance
        if job_data.get('startTime') or job_data.get('endTime') or job_data.get('kilometers'):
            time_dist_data = []
            if job_data.get('startTime'):
                time_dist_data.append(['Starttid:', job_data.get('startTime')])
            if job_data.get('endTime'):
                time_dist_data.append(['Sluttid:', job_data.get('endTime')])
            if job_data.get('kilometers'):
                time_dist_data.append(['Kjørt distanse:', f"{job_data.get('kilometers')} km"])
            
            if time_dist_data:
                time_table = Table(time_dist_data, colWidths=[40*mm, 130*mm])
                time_table.setStyle(TableStyle([
                    ('FONT', (0, 0), (0, -1), 'Helvetica', 9),
                    ('FONT', (1, 0), (1, -1), 'Helvetica-Bold', 10),
                    ('TEXTCOLOR', (0, 0), (0, -1), HexColor('#666666')),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2*mm)
                ]))
                story.append(time_table)
                story.append(Spacer(1, 5*mm))
        
        # Materials
        materials = job_data.get('materials', [])
        if materials:
            story.append(Paragraph("<i>MATERIALER BRUKT</i>", ParagraphStyle('BlueItalic', parent=self.styles['Normal'], fontSize=11, textColor=HexColor('#0d1f26'), fontName='Helvetica-Oblique')))
            materials_text = ", ".join(materials)
            story.append(Paragraph(materials_text, self.styles['Normal']))
            story.append(Spacer(1, 5*mm))
        
        # Status section with blue header
        story.append(Paragraph("<i>STATUS</i>", ParagraphStyle('BlueItalic', parent=self.styles['Normal'], fontSize=11, textColor=HexColor('#0d1f26'), fontName='Helvetica-Oblique')))
        
        status_header = Table([['KONTROLLPUNKT']], colWidths=[170*mm])
        status_header.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), HexColor('#0d1f26')),
            ('TEXTCOLOR', (0,0), (-1,-1), HexColor('#FFFFFF')),
            ('FONT', (0,0), (-1,-1), 'Helvetica-Bold', 10),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5)
        ]))
        story.append(status_header)
        
        answers = job_data.get('answers', {})
        status_data = [
            ['Arbeid fullført'],
            ['Materialer byttet'],
            ['Oppfølging påkrevd']
        ]
        
        status_table = Table(status_data, colWidths=[170*mm])
        status_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), HexColor('#F5F5F5')),
            ('BOX', (0,0), (-1,-1), 1, HexColor('#E0E0E0')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, HexColor('#E0E0E0')),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10)
        ]))
        story.append(status_table)
        story.append(Spacer(1, 5*mm))
        
        # Photos section
        photos_obj = job_data.get('photos', {})
        if photos_obj:
            story.append(Paragraph("<i>FOTODOKUMENTASJON</i>", ParagraphStyle('BlueItalic', parent=self.styles['Normal'], fontSize=11, textColor=HexColor('#0d1f26'), fontName='Helvetica-Oblique')))
            
            photo_keys = ['before', 'during', 'detail', 'after']
            photo_labels = ['FØR — Utgangspunkt', 'ÅPENT — Under arbeid', 'DETALJ — Viktig info', 'ETTER — Ferdig resultat']
            photos = []
            labels = []
            
            for i, key in enumerate(photo_keys):
                if key in photos_obj and photos_obj[key]:
                    photo_data = photos_obj[key]
                    if isinstance(photo_data, dict) and 'data' in photo_data:
                        photos.append(photo_data['data'])
                        labels.append(photo_labels[i])
                    elif isinstance(photo_data, str):
                        photos.append(photo_data)
                        labels.append(photo_labels[i])
            
            if photos:
                photo_rows = []
                for i in range(0, len(photos), 2):
                    img_row = []
                    label_row = []
                    
                    for j in range(2):
                        if i + j < len(photos):
                            try:
                                img_data = photos[i + j]
                                if img_data.startswith('data:image'):
                                    img_data = img_data.split(',')[1]
                                
                                img_bytes = base64.b64decode(img_data)
                                img = Image.open(BytesIO(img_bytes))
                                img.thumbnail((800, 600), Image.Resampling.LANCZOS)
                                
                                img_buffer = BytesIO()
                                img.save(img_buffer, format='JPEG', quality=85)
                                img_buffer.seek(0)
                                
                                rl_img = RLImage(img_buffer, width=80*mm, height=60*mm)
                                img_row.append(rl_img)
                                label_row.append(Paragraph(f"<font size=8>{labels[i + j]}</font>", ParagraphStyle('Center', alignment=TA_CENTER)))
                            except Exception as e:
                                print(f"[ERROR] Photo: {e}")
                                img_row.append('')
                                label_row.append('')
                        else:
                            img_row.append('')
                            label_row.append('')
                    
                    photo_rows.append(img_row)
                    photo_rows.append(label_row)
                
                if photo_rows:
                    photo_table = Table(photo_rows, colWidths=[85*mm, 85*mm])
                    photo_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 2*mm),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 2*mm),
                        ('TOPPADDING', (0, 0), (-1, -1), 2*mm),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 2*mm)
                    ]))
                    story.append(photo_table)
        
        # Notes
        notes = job_data.get('notes', '')
        if notes:
            story.append(Spacer(1, 5*mm))
            story.append(Paragraph("Merknader", self.styles['SectionHeader']))
            story.append(Paragraph(notes, self.styles['Normal']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()


# ============================================
# EMAIL SENDER
# ============================================
class EmailSender:
    def __init__(self, smtp_config):
        self.config = smtp_config
    
    def send(self, to_email, subject, body, attachments=None):
        if not self.config['user'] or not self.config['password']:
            print("[EMAIL] SMTP not configured")
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.config['user']
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            if attachments:
                for filename, content in attachments:
                    part = MIMEApplication(content, Name=filename)
                    part['Content-Disposition'] = f'attachment; filename="{filename}"'
                    msg.attach(part)
            
            context = ssl.create_default_context()
            with smtplib.SMTP(self.config['host'], self.config['port']) as server:
                server.starttls(context=context)
                server.login(self.config['user'], self.config['password'])
                server.send_message(msg)
            
            print(f"[EMAIL] Sent to {to_email}")
            return True
        
        except Exception as e:
            print(f"[EMAIL] Failed: {e}")
            return False


# ============================================
# REQUEST HANDLER
# ============================================
class PipelineHandler(BaseHTTPRequestHandler):
    pdf_generator = PDFGenerator()
    email_sender = EmailSender(CONFIG['smtp'])
    
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()
    
    def do_GET(self):
        path = urlparse(self.path).path
        
        if path == '/api/status':
            self._json({'status': 'ok', 'version': '2.0.0', 'smtp_configured': bool(CONFIG['smtp']['user'])})
        elif path == '/health':
            self._json({'healthy': True})
        else:
            self.send_error(404)
    
    def do_POST(self):
        path = urlparse(self.path).path
        
        if path == '/api/submit':
            self._handle_submit()
        else:
            self.send_error(404)
    
    def _handle_submit(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode('utf-8'))
            
            job_id = data.get('id', 'unknown')
            print(f"\n[JOB] Received: {job_id}")
            
            # Generate PDF
            print("[JOB] Generating PDF...")
            pdf_bytes = self.pdf_generator.generate(data)
            
            # Save locally
            pdf_filename = f"jobbrapport_{job_id}.pdf"
            pdf_path = os.path.join(CONFIG['output_dir'], pdf_filename)
            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            print(f"[JOB] PDF saved: {pdf_path}")
            
            # Send email
            if CONFIG['office_email']:
                print("[JOB] Sending email...")
                
                customer = data.get('customer', 'Ukjent kunde')
                plumber = data.get('plumber', {}).get('name', 'Ukjent montør')
                
                email_subject = f"Jobbrapport - {customer}"
                email_body = f"""Jobbrapport fra {plumber}

Kunde: {customer}
Jobb ID: {job_id}

Se vedlagt PDF for detaljer og separate bilder.

---
Automatisk generert av VVS Pipeline
"""
                
                # Prepare attachments: PDF + separate photos
                attachments = [(pdf_filename, pdf_bytes)]
                
                # Add photos as separate attachments
                photos_obj = data.get('photos', {})
                if photos_obj:
                    photo_keys = ['before', 'during', 'detail', 'after']
                    photo_count = 1
                    
                    for key in photo_keys:
                        if key in photos_obj and photos_obj[key]:
                            photo_data = photos_obj[key]
                            if isinstance(photo_data, dict) and 'data' in photo_data:
                                photo_data = photo_data['data']
                            
                            try:
                                if photo_data.startswith('data:image'):
                                    photo_data = photo_data.split(',')[1]
                                
                                photo_bytes = base64.b64decode(photo_data)
                                photo_filename = f"bilde_{photo_count}_{key}.jpg"
                                attachments.append((photo_filename, photo_bytes))
                                photo_count += 1
                            except Exception as e:
                                print(f"[ERROR] Photo attachment: {e}")
                    
                    # Add extra photos
                    for key, value in photos_obj.items():
                        if key.startswith('extra_') and value:
                            if isinstance(value, dict) and 'data' in value:
                                photo_data = value['data']
                            else:
                                photo_data = value
                            
                            try:
                                if photo_data.startswith('data:image'):
                                    photo_data = photo_data.split(',')[1]
                                
                                photo_bytes = base64.b64decode(photo_data)
                                photo_filename = f"bilde_{photo_count}_{key}.jpg"
                                attachments.append((photo_filename, photo_bytes))
                                photo_count += 1
                            except Exception as e:
                                print(f"[ERROR] Extra photo attachment: {e}")
                
                self.email_sender.send(
                    to_email=CONFIG['office_email'],
                    subject=email_subject,
                    body=email_body,
                    attachments=attachments
                )
            
            self._json({
                'success': True,
                'job_id': job_id,
                'pdf_filename': pdf_filename
            })
            
            print(f"[JOB] Completed: {job_id}\n")
        
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            self._json({'success': False, 'error': str(e)}, status=500)
    
    def _json(self, data, status=200):
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    def log_message(self, format, *args):
        print(f"[HTTP] {args[0]}")


# ============================================
# MAIN
# ============================================
def main():
    server_address = ('', CONFIG['port'])
    httpd = HTTPServer(server_address, PipelineHandler)
    
    print(f"""
╔══════════════════════════════════════════════════╗
║        VVS PIPELINE BACKEND - V2.0               ║
╠══════════════════════════════════════════════════╣
║  Port: {CONFIG['port']}                                    ║
║  SMTP: {CONFIG['smtp']['user'][:30]}...║
║  Office: {CONFIG['office_email'][:28]}...  ║
╚══════════════════════════════════════════════════╝

Endpoints:
  POST /api/submit  - Submit job
  GET  /api/status  - Server status
  GET  /health      - Health check

Waiting for jobs...
""")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
        httpd.shutdown()


if __name__ == '__main__':
    main()
