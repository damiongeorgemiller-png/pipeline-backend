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
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
        story = []
        
        # Company header
        company = job_data.get('company', {})
        story.append(Paragraph(company.get('name', 'VVS Bedrift'), self.styles['CompanyName']))
        story.append(Paragraph(f"Org.nr: {company.get('orgNr', 'N/A')}", self.styles['CompanyInfo']))
        story.append(Paragraph(f"Tlf: {company.get('phone', 'N/A')}", self.styles['CompanyInfo']))
        story.append(Spacer(1, 8*mm))
        
        # Title
        story.append(Paragraph("JOBBRAPPORT", self.styles['Heading1']))
        story.append(Spacer(1, 6*mm))
        
        # Job info
        timestamp = job_data.get('timestamp', '')
        if timestamp:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            date_str = dt.strftime('%d.%m.%Y')
            time_str = dt.strftime('%H:%M')
        else:
            date_str = 'N/A'
            time_str = 'N/A'
        
        plumber = job_data.get('plumber', {})
        
        info_data = [
            ['Dato:', date_str],
            ['Tid:', time_str],
            ['Montør:', plumber.get('name', 'N/A')],
            ['Kunde:', job_data.get('customer', 'N/A')],
            ['Adresse:', job_data.get('location', {}).get('address', 'N/A') if isinstance(job_data.get('location'), dict) else 'N/A']
        ]
        
        # Add start/end time if present
        if job_data.get('startTime'):
            info_data.append(['Starttid:', job_data.get('startTime')])
        if job_data.get('endTime'):
            info_data.append(['Sluttid:', job_data.get('endTime')])
        
        info_table = Table(info_data, colWidths=[40*mm, 130*mm])
        info_table.setStyle(TableStyle([
            ('FONT', (0, 0), (0, -1), 'Helvetica-Bold', 9),
            ('FONT', (1, 0), (1, -1), 'Helvetica', 10),
            ('TEXTCOLOR', (0, 0), (0, -1), HexColor('#666666')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm)
        ]))
        story.append(info_table)
        story.append(Spacer(1, 6*mm))
        
        # Job description
        job_desc = job_data.get('jobDescription', '')
        if job_desc:
            story.append(Paragraph("Beskrivelse", self.styles['SectionHeader']))
            story.append(Paragraph(job_desc, self.styles['Normal']))
            story.append(Spacer(1, 4*mm))
        
        # Materials
        materials = job_data.get('materials', [])
        if materials:
            story.append(Paragraph("Materialer brukt", self.styles['SectionHeader']))
            materials_text = ", ".join(materials)
            story.append(Paragraph(materials_text, self.styles['Normal']))
            story.append(Spacer(1, 4*mm))
        
        # Status
        answers = job_data.get('answers', {})
        story.append(Paragraph("Status", self.styles['SectionHeader']))
        
        status_data = [
            ['Jobb fullført:', 'Ja' if answers.get('completed') else 'Nei'],
            ['Materialer byttet:', 'Ja' if answers.get('materials') else 'Nei'],
            ['Oppfølging nødvendig:', 'Ja' if answers.get('followup') else 'Nei']
        ]
        
        status_table = Table(status_data, colWidths=[60*mm, 110*mm])
        status_table.setStyle(TableStyle([
            ('FONT', (0, 0), (0, -1), 'Helvetica', 9),
            ('FONT', (1, 0), (1, -1), 'Helvetica-Bold', 10),
            ('TEXTCOLOR', (0, 0), (0, -1), HexColor('#666666')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2*mm)
        ]))
        story.append(status_table)
        story.append(Spacer(1, 6*mm))
        
        # Photos
        photos_obj = job_data.get('photos', {})
        if photos_obj:
            story.append(Paragraph("Fotodokumentasjon", self.styles['SectionHeader']))
            
            # Get up to 4 photos
            photo_keys = ['before', 'during', 'detail', 'after']
            photos = []
            
            for key in photo_keys:
                if key in photos_obj and photos_obj[key]:
                    photo_data = photos_obj[key]
                    if isinstance(photo_data, dict) and 'data' in photo_data:
                        photos.append(photo_data['data'])
                    elif isinstance(photo_data, str):
                        photos.append(photo_data)
            
            # Add extra photos if any
            for key, value in photos_obj.items():
                if key.startswith('extra_') and value:
                    if isinstance(value, dict) and 'data' in value:
                        photos.append(value['data'])
                    elif isinstance(value, str):
                        photos.append(value)
            
            if photos:
                photo_rows = []
                for i in range(0, len(photos), 2):
                    row = []
                    for j in range(2):
                        if i + j < len(photos):
                            try:
                                img_data = photos[i + j]
                                if img_data.startswith('data:image'):
                                    img_data = img_data.split(',')[1]
                                
                                img_bytes = base64.b64decode(img_data)
                                img = Image.open(BytesIO(img_bytes))
                                
                                # Resize
                                img.thumbnail((800, 600), Image.Resampling.LANCZOS)
                                
                                img_buffer = BytesIO()
                                img.save(img_buffer, format='JPEG', quality=85)
                                img_buffer.seek(0)
                                
                                rl_img = RLImage(img_buffer, width=75*mm, height=56*mm)
                                row.append(rl_img)
                            except Exception as e:
                                print(f"[ERROR] Photo processing: {e}")
                                row.append(Paragraph("Bilde feil", self.styles['Normal']))
                        else:
                            row.append('')
                    
                    if row:
                        photo_rows.append(row)
                
                if photo_rows:
                    photo_table = Table(photo_rows, colWidths=[80*mm, 80*mm])
                    photo_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 2*mm),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 2*mm),
                        ('TOPPADDING', (0, 0), (-1, -1), 2*mm),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 2*mm)
                    ]))
                    story.append(photo_table)
        
        # Notes
        notes = job_data.get('notes', '')
        if notes:
            story.append(Spacer(1, 6*mm))
            story.append(Paragraph("Merknader", self.styles['SectionHeader']))
            story.append(Paragraph(notes, self.styles['Normal']))
        
        # Build PDF
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

Se vedlagt PDF for detaljer.

---
Automatisk generert av VVS Pipeline
"""
                
                self.email_sender.send(
                    to_email=CONFIG['office_email'],
                    subject=email_subject,
                    body=email_body,
                    attachments=[(pdf_filename, pdf_bytes)]
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
