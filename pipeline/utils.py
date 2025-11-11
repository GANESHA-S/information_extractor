# utils.py
# ========== PDF Text Extraction & Pre-Cleaning Utilities ==========
import fitz  # PyMuPDF
import re


def preclean_text(text: str) -> str:
    """
    Clean raw extracted text (from PDF or OCR):
    - remove headers/footers (e.g., Page 1 of 12)
    - de-hyphenate words broken across lines
    - normalize whitespace & line breaks
    - normalize quotes/apostrophes
    """
    if not text:
        return ""

    # Remove common headers/footers like "Page 1 of 12"
    text = re.sub(r'Page \d+ of \d+', '', text, flags=re.I)

    # Remove decorative lines or underscores
    text = re.sub(r'_{3,}', '', text)
    text = re.sub(r'-{3,}', '', text)

    # De-hyphenate words broken across lines: "appli-\ncation" → "application"
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)

    # Replace multiple newlines with a single newline
    text = re.sub(r'\n{2,}', '\n', text)

    # Normalize whitespace inside lines
    text = re.sub(r'[ \t]+', ' ', text)

    # Normalize quotes/apostrophes
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')

    # Collapse excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def extract_text_from_pdf(pdf_path: str, max_pages: int = None) -> str:
    """
    Extract and clean text from a PDF file using PyMuPDF.
    
    Args:
        pdf_path (str): Path to PDF file.
        max_pages (int, optional): Limit number of pages (useful for debugging).
    
    Returns:
        str: Cleaned extracted text.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF: {e}")

    all_text = []
    for page_num, page in enumerate(doc, start=1):
        if max_pages and page_num > max_pages:
            break

        raw_text = page.get_text("text")  # extract plain text
        clean_page = preclean_text(raw_text)
        if clean_page:
            all_text.append(clean_page)

    # Join all pages together
    return "\n".join(all_text).strip()


def normalize_statutes(statutes):
    """
    Normalize statute names:
    - Remove duplicates
    - Expand abbreviations (CrPC -> Code of Criminal Procedure, IPC -> Indian Penal Code, etc.)
    - Strip whitespace and punctuation
    """
    if not statutes:
        return []

    norm_map = {
        r"\bCrPC\b": "Code of Criminal Procedure, 1973",
        r"\bCPC\b": "Code of Civil Procedure, 1908",
        r"\bIPC\b": "Indian Penal Code, 1860",
        r"\bNI Act\b": "Negotiable Instruments Act, 1881",
        r"\bIT Act\b": "Information Technology Act, 2000",
        r"\bBNS\b": "Bharatiya Nyaya Sanhita, 2023",
        r"\bBNSS\b": "Bharatiya Nagarik Suraksha Sanhita, 2023",
    }

    cleaned = []
    seen = set()
    for s in statutes:
        s = s.strip().rstrip(".,;:")
        if not s:
            continue
        for pattern, full_form in norm_map.items():
            if re.search(pattern, s, flags=re.IGNORECASE):
                s = full_form
                break
        if s.lower() not in seen:
            seen.add(s.lower())
            cleaned.append(s)

    return cleaned
