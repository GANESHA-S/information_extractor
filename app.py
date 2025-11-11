from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import re
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from werkzeug.utils import secure_filename
from typing import List, Optional
from collections import OrderedDict

# Local imports
from pipeline.utils import extract_text_from_pdf
from pipeline.ner_predictor import load_legalbert_model, post_process_ner
from pipeline.spacy_pipeline import load_spacy_ruler, apply_spacy_and_regex
from pipeline.postprocessing import merge_entities
from pipeline.segmenter import Segmenter
from pipeline.selectors import (
    select_primary_case_number, select_primary_court, select_primary_date,
    extract_case_name_from_header, make_case_name, normalize_case_name
)
from pipeline.party_extractor import extract_parties
from pipeline.advocate_extractor import extract_advocates
from pipeline.content_extractor import extract_background_facts, extract_order_summary

# FastAPI setup
app = FastAPI(
    title="Legal Document Extraction API",
    description="Extract structured information from legal judgment PDFs",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"] 
)

UPLOAD_FOLDER = "uploads"
LOGO_FOLDER = "assets"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(LOGO_FOLDER, exist_ok=True)

legalbert_model = None
spacy_nlp = None

LOGO_PATH = os.path.join(LOGO_FOLDER, "logo.png")
WATERMARK_PATH = os.path.join(LOGO_FOLDER, "watermark.png")


# Pydantic Models
class PDFGenerateRequest(BaseModel):
    data: dict
    content: Optional[dict] = None
    fields: Optional[List[str]] = None


class FilterFieldsRequest(BaseModel):
    data: dict
    fields: List[str]


class ExtractionResponse(BaseModel):
    structured: dict


# Custom Canvas
class HeaderFooterCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self.pages = []
        
    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()
        
    def save(self):
        page_count = len(self.pages)
        for page_num, page in enumerate(self.pages, start=1):
            self.__dict__.update(page)
            self.draw_header_footer(page_num, page_count)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)
        
    def draw_header_footer(self, page_num, page_count):
        self.saveState()
        
        # Header - Logo (left side)
        if os.path.exists(LOGO_PATH):
            try:
                # Try to load and draw the logo
                self.drawImage(
                    LOGO_PATH, 
                    40,                    # X position from left
                    A4[1] - 60,           # Y position from top (adjusted)
                    width=80,              # Logo width
                    height=40,             # Logo height
                    preserveAspectRatio=True,
                    mask='auto'
                )
            except Exception as e:
                # If image fails, show a placeholder text
                self.setFont('Helvetica-Bold', 10)
                self.setFillColor(colors.HexColor("#2563eb"))
                self.drawString(40, A4[1] - 35, "[LOGO]")
                print(f"Logo error: {e}")
        else:
            # If logo doesn't exist, show placeholder
            self.setFont('Helvetica-Bold', 10)
            self.setFillColor(colors.HexColor("#2563eb"))
            self.drawString(40, A4[1] - 35, "[No Logo]")
        
        # Header - Right side branding text
        self.setFont('Helvetica-Bold', 12)
        self.setFillColor(colors.HexColor("#2563eb"))
        #self.drawRightString(A4[0] - 40, A4[1] - 35, "VerdictX")
        if os.path.exists(WATERMARK_PATH):
            try:
                self.setFillAlpha(0.1)
                self.drawImage(WATERMARK_PATH, A4[0]/2 - 100, A4[1]/2 - 100, 
                             width=200, height=200, preserveAspectRatio=True, mask='auto')
                self.setFillAlpha(1)
            except:
                pass
        self.setFont('Helvetica', 9)
        self.setFillColor(colors.grey)
        self.drawCentredString(A4[0] / 2, 30, f"Page {page_num} of {page_count}")
        self.setFont('Helvetica', 8)
        self.drawString(40, 20, "© VerdictX - AI Generated Report")
        self.drawRightString(A4[0] - 40, 20, "Confidential")
        self.restoreState()


def safe_text(text):
    if text is None:
        return "—"
    text = str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def get_pdf_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Heading", fontSize=22, leading=26, alignment=TA_CENTER, 
                             spaceAfter=12, textColor=colors.HexColor("#1a365d"), fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Brand", fontSize=16, leading=20, alignment=TA_CENTER, 
                             spaceAfter=20, textColor=colors.HexColor("#2563eb"), fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="SubHeading", fontSize=13, leading=16, spaceBefore=14, 
                             spaceAfter=8, textColor=colors.HexColor("#1e40af"), fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Body", fontSize=10, leading=14, alignment=TA_LEFT, 
                             spaceAfter=6, fontName="Helvetica"))
    styles.add(ParagraphStyle(name="BodyBold", fontSize=10, leading=14, fontName="Helvetica-Bold"))
    return styles


def extract_full_data(text, segments):
    bert_output_header = post_process_ner(segments["header"], legalbert_model(segments["header"]))
    bert_output_body = post_process_ner(segments["body"], legalbert_model(segments["body"]))
    spacy_regex_ents = apply_spacy_and_regex(text, spacy_nlp)
    
    bert_ents_list = []
    for k, vals in bert_output_header.items():
        for v in vals:
            bert_ents_list.append((k.upper(), v + " [header]"))
    for k, vals in bert_output_body.items():
        for v in vals:
            bert_ents_list.append((k.upper(), v + " [body]"))
    
    final_output = merge_entities(bert_ents_list, spacy_regex_ents)
    appellants, respondents = extract_parties(segments["header"], final_output)
    adv_split = extract_advocates(text) or {"for_appellants": [], "for_respondent": []}
    background_facts = extract_background_facts(segments["body"])
    order_summary = extract_order_summary(segments["order"])
    
    structured = OrderedDict()
    
    # Extract case name first
    case_name = normalize_case_name(
        extract_case_name_from_header(segments["header"])
    )
    
    # If case name exists but no parties extracted, parse from case name
    if case_name and ' v. ' in case_name and (not appellants or not respondents):
        parts = re.split(r'\s+v\.?\s+', case_name, flags=re.I)
        if len(parts) == 2:
            if not appellants:
                appellants = [parts[0].strip()]
            if not respondents:
                respondents = [parts[1].strip()]
    
    # If still no case name, build from parties
    if not case_name and appellants and respondents:
        case_name = make_case_name(appellants, [respondents[0]] if respondents else [])
    
    if case_name:
        structured["case_name"] = case_name
    
    appeal_num = select_primary_case_number(final_output.get("case_number", []))
    if appeal_num:
        structured["appeal_number"] = appeal_num
    
    court = select_primary_court(final_output.get("court", []))
    if court:
        structured["court"] = court
    
    date_judgment = select_primary_date(final_output.get("date", []))
    if date_judgment:
        structured["date_of_judgment"] = date_judgment
    
    if final_output.get("coram"):
        structured["coram"] = final_output["coram"]
    
    # *** CRITICAL: Add appellants and respondent HERE ***
    if appellants:
        structured["appellants"] = appellants
    if respondents:
        structured["respondent"] = respondents[0]
    
    appellant_advs = adv_split.get("for_appellants", [])
    respondent_advs = adv_split.get("for_respondent", [])
    
    if appellant_advs or respondent_advs:
        structured["advocates"] = OrderedDict()
        if appellant_advs:
            structured["advocates"]["for_appellants"] = appellant_advs
        if respondent_advs:
            structured["advocates"]["for_respondent"] = respondent_advs
    
    if final_output.get("precedent"):
        structured["precedents"] = final_output["precedent"]
    if final_output.get("provision"):
        structured["provisions"] = final_output["provision"]
    if final_output.get("statute"):
        structured["statutes"] = final_output["statute"]
    if final_output.get("extra_courts"):
        structured["lower_courts"] = final_output["extra_courts"]
    if final_output.get("extra_dates"):
        structured["other_dates"] = final_output["extra_dates"]
    
    content = {}
    if background_facts:
        content["background_facts"] = background_facts
    
    clean_order = {}
    if order_summary.get("result"):
        clean_order["result"] = order_summary["result"]
    if order_summary.get("decision"):
        clean_order["decision"] = order_summary["decision"]
    if order_summary.get("directions"):
        clean_order["directions"] = order_summary["directions"]
    
    if clean_order:
        content["order_summary"] = clean_order
    if content:
        structured["content_info"] = content
    
    return dict(structured)


def build_pdf_elements(data, styles):
    elements = []
    
    # Removed centered "VerdictX" brand heading
    # Only show main title
    elements.append(Paragraph("LEGAL DOCUMENT EXTRACTION REPORT", styles["Heading"]))
    elements.append(Spacer(1, 20))
    
    case_data = []
    if data.get("case_name"):
        case_data.append(["Case name:", safe_text(data.get("case_name"))])
    if data.get("appeal_number"):
        case_data.append(["Appeal number:", safe_text(data.get("appeal_number"))])
    if data.get("date_of_judgment"):
        case_data.append(["Date of judgment:", safe_text(data.get("date_of_judgment"))])
    if data.get("court"):
        case_data.append(["Court:", safe_text(data.get("court"))])
    
    if case_data:
        t = Table(case_data, colWidths=[130, 370])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#eff6ff")),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor("#1e40af")),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
        ]))
        # Keep table together on same page
        elements.append(KeepTogether(t))
        elements.append(Spacer(1, 20))
    
    # Coram section - keep together
    if data.get("coram"):
        coram_elements = []
        coram_elements.append(Paragraph("Coram:", styles["SubHeading"]))
        for j in data["coram"]:
            coram_elements.append(Paragraph(f"• {safe_text(j)}", styles["Body"]))
        elements.append(KeepTogether(coram_elements))
        elements.append(Spacer(1, 15))
    
    # Appellants section - keep together
    if data.get("appellants"):
        appellant_elements = []
        appellant_elements.append(Paragraph("Appellants:", styles["SubHeading"]))
        for a in data["appellants"]:
            appellant_elements.append(Paragraph(f"• {safe_text(a)}", styles["Body"]))
        elements.append(KeepTogether(appellant_elements))
        elements.append(Spacer(1, 10))
    
    # Respondent section - keep together
    if data.get("respondent"):
        respondent_elements = []
        respondent_elements.append(Paragraph("Respondent:", styles["SubHeading"]))
        respondent_elements.append(Paragraph(f"• {safe_text(data['respondent'])}", styles["Body"]))
        elements.append(KeepTogether(respondent_elements))
        elements.append(Spacer(1, 15))
    
    # Advocates section - keep together
    advs = data.get("advocates", {})
    if advs:
        adv_elements = []
        adv_elements.append(Paragraph("Advocates:", styles["SubHeading"]))
        if advs.get("for_appellants"):
            adv_elements.append(Paragraph("- For appellants:", styles["BodyBold"]))
            for adv in advs["for_appellants"]:
                adv_elements.append(Paragraph(f"  • {safe_text(adv)}", styles["Body"]))
            adv_elements.append(Spacer(1, 8))
        if advs.get("for_respondent"):
            adv_elements.append(Paragraph("- For Respondent:", styles["BodyBold"]))
            for adv in advs["for_respondent"]:
                adv_elements.append(Paragraph(f"  • {safe_text(adv)}", styles["Body"]))
        elements.append(KeepTogether(adv_elements))
        elements.append(Spacer(1, 15))
    
    # Precedents - allow natural breaks if too long
    if data.get("precedents"):
        elements.append(Paragraph("Precedent:", styles["SubHeading"]))
        for p in data["precedents"][:15]:
            elements.append(Paragraph(f"• {safe_text(p)}", styles["Body"]))
        elements.append(Spacer(1, 15))
    
    # Provisions - allow natural breaks if too long
    if data.get("provisions"):
        elements.append(Paragraph("Provisions:", styles["SubHeading"]))
        for p in data["provisions"][:20]:
            elements.append(Paragraph(f"• {safe_text(p)}", styles["Body"]))
        elements.append(Spacer(1, 15))
    
    # Statutes section
    if data.get("statutes"):
        elements.append(Paragraph("Statutes:", styles["SubHeading"]))
        for s in data["statutes"][:15]:
            elements.append(Paragraph(f"• {safe_text(s)}", styles["Body"]))
        elements.append(Spacer(1, 15))
    
    # Lower courts section
    if data.get("lower_courts"):
        elements.append(Paragraph("Lower courts:", styles["SubHeading"]))
        for c in data["lower_courts"][:10]:
            elements.append(Paragraph(f"• {safe_text(c)}", styles["Body"]))
        elements.append(Spacer(1, 15))
    
    # Other dates section
    if data.get("other_dates"):
        elements.append(Paragraph("Other dates:", styles["SubHeading"]))
        for d in data["other_dates"][:10]:
            elements.append(Paragraph(f"• {safe_text(d)}", styles["Body"]))
        elements.append(Spacer(1, 20))
    
    # Content section
    content = data.get("content_info", {})
    if content:
        elements.append(Paragraph("Content:", styles["SubHeading"]))
        
        # Background facts
        if content.get("background_facts"):
            bg_elements = []
            bg_elements.append(Paragraph("- Background:", styles["BodyBold"]))
            bg_elements.append(Spacer(1, 6))
            for i, f in enumerate(content["background_facts"][:8], 1):
                bg_elements.append(Paragraph(f"  {i}. {safe_text(f)}", styles["Body"]))
                bg_elements.append(Spacer(1, 4))
            elements.append(KeepTogether(bg_elements))
            elements.append(Spacer(1, 10))
        
        # Order summary
        order = content.get("order_summary", {})
        if order:
            order_elements = []
            if order.get("result"):
                order_elements.append(Paragraph("- Result:", styles["BodyBold"]))
                order_elements.append(Paragraph(f"  {safe_text(order['result'])}", styles["Body"]))
                order_elements.append(Spacer(1, 8))
            if order.get("decision"):
                order_elements.append(Paragraph("- Decision:", styles["BodyBold"]))
                order_elements.append(Paragraph(f"  {safe_text(order['decision'])}", styles["Body"]))
            
            if order_elements:
                elements.append(KeepTogether(order_elements))
                elements.append(Spacer(1, 10))
    
    # Footer
    elements.append(Spacer(1, 30))
    # Replaced harsh black lines with subtle gray separator
    footer_separator = Paragraph(
        '<font color="#d1d5db">━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</font>',
        styles["Body"]
    )
    elements.append(footer_separator)
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>Disclaimer:</b> This is an AI-generated report", styles["Body"]))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph("© VerdictX", styles["Body"]))
    
    return elements


def filter_data_by_fields(full_data, fields):
    mapping = {
        "case name": "case_name", "casename": "case_name",
        "appeal number": "appeal_number", "appeal no": "appeal_number",
        "court": "court", "date": "date_of_judgment",
        "date of judgment": "date_of_judgment", "judgment date": "date_of_judgment",
        "coram": "coram", "bench": "coram", "judges": "coram",
        "appellants": "appellants", "petitioners": "appellants",
        "respondent": "respondent", "respondents": "respondent",
        "advocates": "advocates", "lawyers": "advocates",
        "precedents": "precedents", "cases cited": "precedents",
        "provisions": "provisions", "sections": "provisions",
        "statutes": "statutes", "acts": "statutes",
        "lower courts": "lower_courts", "other dates": "other_dates",
        "content": "content_info", "content info": "content_info",
        "background": "content_info", "facts": "content_info",
        "order": "content_info", "decision": "content_info"
    }
    
    norm = []
    for f in fields:
        fl = f.lower().strip()
        if fl in mapping:
            norm.append(mapping[fl])
        else:
            for k, v in mapping.items():
                if fl in k or k in fl:
                    norm.append(v)
                    break
            else:
                if fl.replace(" ", "_") in full_data:
                    norm.append(fl.replace(" ", "_"))
    
    seen = set()
    norm = [x for x in norm if not (x in seen or seen.add(x))]
    
    result = {}
    for f in norm:
        if f in full_data:
            result[f] = full_data[f]
    return result


@app.on_event("startup")
async def startup_event():
    global legalbert_model, spacy_nlp
    print("Loading models...")
    legalbert_model = load_legalbert_model("model/legalbert2.0")
    spacy_nlp = load_spacy_ruler()
    print("Models loaded!")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "models_loaded": legalbert_model is not None and spacy_nlp is not None}


@app.post("/api/extract", response_model=ExtractionResponse)
async def extract_info(file: UploadFile = File(...)):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files supported")
    
    path = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    with open(path, "wb") as buffer:
        buffer.write(await file.read())

    try:
        text = extract_text_from_pdf(path)
        segments = Segmenter(text).split_segments()
        structured = extract_full_data(text, segments)
        return {"structured": structured}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if os.path.exists(path):
            os.remove(path)


@app.post("/api/generate-pdf")
async def generate_pdf(request: PDFGenerateRequest):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, 
                               topMargin=70, bottomMargin=60, title="Legal Report")
        styles = get_pdf_styles()
        elements = build_pdf_elements(request.data, styles)
        doc.build(elements, canvasmaker=HeaderFooterCanvas)
        buffer.seek(0)
        
        fname = "report.pdf"
        if request.data.get("appeal_number"):
            fname = f"{request.data['appeal_number'].replace('/', '-')[:50]}_report.pdf"
        elif request.data.get("case_name"):
            fname = f"{request.data['case_name'].replace(' ', '_')[:50]}_report.pdf"
        
        return StreamingResponse(buffer, media_type="application/pdf",
                               headers={"Content-Disposition": f"attachment; filename={fname}"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF Error: {str(e)}")


@app.post("/api/extract-and-download")
async def extract_and_download(file: UploadFile = File(...)):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files")
    
    path = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    with open(path, "wb") as buffer:
        buffer.write(await file.read())

    try:
        text = extract_text_from_pdf(path)
        segments = Segmenter(text).split_segments()
        structured = extract_full_data(text, segments)
        
        # Generate PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, 
                               topMargin=70, bottomMargin=60, title="Legal Report")
        styles = get_pdf_styles()
        elements = build_pdf_elements(structured, styles)
        doc.build(elements, canvasmaker=HeaderFooterCanvas)
        buffer.seek(0)
        
        fname = "report.pdf"
        if structured.get("appeal_number"):
            fname = f"{structured['appeal_number'].replace('/', '-')[:50]}_report.pdf"
        elif structured.get("case_name"):
            fname = f"{structured['case_name'].replace(' ', '_')[:50]}_report.pdf"
        
        # FIXED: Return with proper headers for CORS
        return StreamingResponse(
            buffer, 
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
                "Cache-Control": "no-cache"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if os.path.exists(path):
            os.remove(path)


@app.get("/api/fields")
async def get_available_fields():
    return {
        "available_fields": {
            "case_name": {"description": "Full case name", "type": "string"},
            "appeal_number": {"description": "Appeal number", "type": "string"},
            "court": {"description": "Court name", "type": "string"},
            "date_of_judgment": {"description": "Judgment date", "type": "string"},
            "coram": {"description": "Judges", "type": "list"},
            "appellants": {"description": "Appellants", "type": "list"},
            "respondent": {"description": "Respondent", "type": "string"},
            "advocates": {"description": "Advocates", "type": "object"},
            "precedents": {"description": "Cases cited", "type": "list"},
            "provisions": {"description": "Provisions", "type": "list"},
            "statutes": {"description": "Statutes", "type": "list"},
            "lower_courts": {"description": "Lower courts", "type": "list"},
            "other_dates": {"description": "Other dates", "type": "list"},
            "content_info": {"description": "Background and order", "type": "object"}
        }
    }


@app.post("/api/smart-extract")
async def smart_extract(file: UploadFile = File(...), fields: Optional[str] = None):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files")
    
    path = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    with open(path, "wb") as buffer:
        buffer.write(await file.read())

    try:
        text = extract_text_from_pdf(path)
        segments = Segmenter(text).split_segments()
        structured = extract_full_data(text, segments)
        
        if fields:
            req_fields = [f.strip() for f in fields.split(",")]
            filtered = filter_data_by_fields(structured, req_fields)
            if not filtered:
                return JSONResponse(content={"error": "No matching fields", 
                    "requested": req_fields, "available": list(structured.keys())}, status_code=400)
            return filtered
        return structured
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if os.path.exists(path):
            os.remove(path)


@app.post("/api/smart-extract-pdf")
async def smart_extract_pdf(file: UploadFile = File(...), fields: Optional[str] = None):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files")
    
    path = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    with open(path, "wb") as buffer:
        buffer.write(await file.read())

    try:
        text = extract_text_from_pdf(path)
        segments = Segmenter(text).split_segments()
        structured = extract_full_data(text, segments)
        
        if fields:
            req_fields = [f.strip() for f in fields.split(",")]
            filtered = filter_data_by_fields(structured, req_fields)
            return await generate_pdf(PDFGenerateRequest(data=filtered))
        return await generate_pdf(PDFGenerateRequest(data=structured))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if os.path.exists(path):
            os.remove(path)


@app.post("/api/filter-fields")
async def filter_fields_endpoint(request: FilterFieldsRequest):
    filtered = filter_data_by_fields(request.data, request.fields)
    if not filtered:
        return JSONResponse(content={"error": "No matching fields", 
            "requested": request.fields, "available": list(request.data.keys())}, status_code=400)
    return filtered


@app.post("/api/generate-custom-pdf")
async def generate_custom_pdf(request: FilterFieldsRequest):
    filtered = filter_data_by_fields(request.data, request.fields)
    if not filtered:
        return JSONResponse(content={"error": "No matching fields"}, status_code=400)
    
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40,
                               topMargin=70, bottomMargin=60, title="Filtered Report")
        styles = get_pdf_styles()
        elements = []
        
        # Removed centered "VerdictX" brand heading
        elements.append(Paragraph("FILTERED EXTRACTION REPORT", styles["Heading"]))
        elements.append(Spacer(1, 20))
        
        labels = {"case_name": "Case name:", "appeal_number": "Appeal number:",
                 "court": "Court:", "date_of_judgment": "Date of judgment:",
                 "coram": "Coram:", "appellants": "Appellants:", "respondent": "Respondent:",
                 "advocates": "Advocates:", "precedents": "Precedent:", "provisions": "Provisions:",
                 "statutes": "Statutes:", "lower_courts": "Lower courts:", 
                 "other_dates": "Other dates:", "content_info": "Content:"}
        
        for k, v in filtered.items():
            label = labels.get(k, k.replace("_", " ").title() + ":")
            
            if k in ["case_name", "appeal_number", "court", "date_of_judgment"]:
                t = Table([[label, safe_text(v)]], colWidths=[130, 370])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#eff6ff")),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                    ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ]))
                elements.append(t)
                elements.append(Spacer(1, 12))
            elif isinstance(v, list):
                elements.append(Paragraph(label, styles["SubHeading"]))
                for item in v:
                    elements.append(Paragraph(f"• {safe_text(item)}", styles["Body"]))
                elements.append(Spacer(1, 12))
            elif isinstance(v, dict):
                elements.append(Paragraph(label, styles["SubHeading"]))
                if k == "advocates":
                    if v.get("for_appellants"):
                        elements.append(Paragraph("- For appellants:", styles["BodyBold"]))
                        for adv in v["for_appellants"]:
                            elements.append(Paragraph(f"  • {safe_text(adv)}", styles["Body"]))
                    if v.get("for_respondent"):
                        elements.append(Paragraph("- For Respondent:", styles["BodyBold"]))
                        for adv in v["for_respondent"]:
                            elements.append(Paragraph(f"  • {safe_text(adv)}", styles["Body"]))
                elif k == "content_info":
                    if v.get("background_facts"):
                        elements.append(Paragraph("- Background:", styles["BodyBold"]))
                        for i, f in enumerate(v["background_facts"][:8], 1):
                            elements.append(Paragraph(f"  {i}. {safe_text(f)}", styles["Body"]))
                    order = v.get("order_summary", {})
                    if order.get("result"):
                        elements.append(Paragraph("- Result:", styles["BodyBold"]))
                        elements.append(Paragraph(f"  {safe_text(order['result'])}", styles["Body"]))
                    if order.get("decision"):
                        elements.append(Paragraph("- Decision:", styles["BodyBold"]))
                        elements.append(Paragraph(f"  {safe_text(order['decision'])}", styles["Body"]))
                elements.append(Spacer(1, 12))
            else:
                elements.append(Paragraph(label, styles["SubHeading"]))
                elements.append(Paragraph(safe_text(v), styles["Body"]))
                elements.append(Spacer(1, 12))
        
        elements.append(Spacer(1, 30))
        # Subtle gray separator instead of black lines
        footer_separator = Paragraph(
            '<font color="#d1d5db">━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</font>',
            styles["Body"]
        )
        elements.append(footer_separator)
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("<b>Disclaimer:</b> AI-generated filtered report", styles["Body"]))
        elements.append(Spacer(1, 5))
        elements.append(Paragraph("© VerdictX", styles["Body"]))
        
        doc.build(elements, canvasmaker=HeaderFooterCanvas)
        buffer.seek(0)
        
        fname = "filtered_report.pdf"
        if filtered.get("appeal_number"):
            fname = f"{str(filtered['appeal_number']).replace('/', '-')[:50]}_filtered.pdf"
        elif filtered.get("case_name"):
            fname = f"{str(filtered['case_name']).replace(' ', '_')[:50]}_filtered.pdf"
        
        return StreamingResponse(buffer, media_type="application/pdf",
                               headers={"Content-Disposition": f"attachment; filename={fname}"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF Error: {str(e)}")





if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)