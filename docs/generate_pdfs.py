import json, re
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

def reshape_ar(text):
    return get_display(arabic_reshaper.reshape(text))

def parse_sections(filepath, is_arabic):
    sections = []
    current_type = None
    current_text = []
    
    heading_pattern = re.compile(r'^(\d+\.(?:\d+\.?)*)\s+(.*)')
    major_heading = re.compile(r'^(?:Introduction|Conclusion|[\d]+\.\s)', re.UNICODE)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = [l.rstrip('\n\r') for l in f.readlines()]
    
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        
        # Check for major heading (no number prefix like "Introduction", "1. Project Overview")
        m = re.match(r'^(\d+)\.\s+(.*)', line)
        if m:
            sections.append(('h1', line))
            i += 1
            continue
        
        m2 = re.match(r'^(\d+\.\d+)\s+(.*)', line)
        if m2:
            sections.append(('h2', line))
            i += 1
            continue
        
        # Check if line is a heading without number (Introduction, Conclusion)
        if line in ['Introduction', 'Conclusion'] or re.match(r'^(\d+)\.\s', line):
            sections.append(('h1', line))
            i += 1
            continue
        
        # It's a body paragraph
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r'^\d', lines[i].strip()):
            para.append(lines[i])
            i += 1
        if para:
            sections.append(('body', ' '.join(para)))
        else:
            i += 1
    
    return sections

class ReportPDF(FPDF):
    def __init__(self, is_arabic=False):
        super().__init__('P', 'mm', 'A4')
        self.is_arabic = is_arabic
        self.add_font('Tahoma', '', r'C:\Windows\Fonts\tahoma.ttf')
        self.set_auto_page_break(auto=True, margin=20)
    
    def t(self, text):
        if self.is_arabic:
            return reshape_ar(text)
        return text
    
    def add_sections(self, sections):
        for stype, text in sections:
            if stype == 'h1':
                self.set_font('Tahoma', size=16)
                self.ln(4)
                self.cell(0, 9, self.t(text.strip()), new_x='LMARGIN', new_y='NEXT', align='C' if not self.is_arabic else 'R')
                self.ln(2)
            elif stype == 'h2':
                self.set_font('Tahoma', size=12)
                self.ln(3)
                self.cell(0, 7, self.t(text.strip()), new_x='LMARGIN', new_y='NEXT', align='L' if not self.is_arabic else 'R')
                self.ln(1)
            elif stype == 'body':
                self.set_font('Tahoma', size=10)
                body = text.strip()
                if self.is_arabic:
                    body = reshape_ar(body)
                self.multi_cell(0, 5, body, align='R' if self.is_arabic else 'L')
                self.ln(1)

# Parse English
en_sections = parse_sections('docs/software_report.txt', is_arabic=False)
pdf_en = ReportPDF(is_arabic=False)
pdf_en.add_page()
pdf_en.add_sections(en_sections)
pdf_en.output('docs/software_report.pdf')
print(f"English PDF generated. Sections: {len(en_sections)}")

# Parse Arabic
ar_sections = parse_sections('docs/software_report_ar.txt', is_arabic=True)
pdf_ar = ReportPDF(is_arabic=True)
pdf_ar.add_page()
pdf_ar.add_sections(ar_sections)
pdf_ar.output('docs/software_report_ar.pdf')
print(f"Arabic PDF generated. Sections: {len(ar_sections)}")
