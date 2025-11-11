import re
from typing import List, Optional
from datetime import datetime


def extract_case_name_from_header(header: str) -> Optional[str]:
    """
    IMPROVED: Extract case name with support for VERSUS format.
    Now handles both inline "v." and multi-line "VERSUS" patterns.
    """
    if not header:
        return None

    # Step 1: Pre-clean
    text = header.strip()
    
    # Remove SCR/SCC citations at the start
    text = re.sub(r'^\s*\[\d{4}\]\s+\d+\s+(?:S\.C\.R\.?|SCC|SCR)\s+\d+\s*[:\-]?\s*\d*\s*[:\-]?\s*\d+\s+INSC\s+\d+\s*', '', text, flags=re.I)
    text = re.sub(r'^\s*\[\d{4}\]\s+\d+\s+(?:S\.C\.R\.?|SCC|SCR|INSC)\s+\d+\s*', '', text, flags=re.I)
    
    # Remove case numbers BEFORE case name (but keep those after)
    text = re.sub(r'^\s*(?:Criminal|Civil)\s+(?:Appeal|Application)\s+No\.?\s*\d+.*?(?:of\s+\d{4})?\s*', '', text, flags=re.I)
    
    # Remove date lines
    text = re.sub(r'^\s*Dated?\s*:.*?\d{4}\s*', '', text, flags=re.I | re.M)
    
    # Remove CORAM lines
    text = re.sub(r'^\s*CORAM\s*:.*?(?=\n|$)', '', text, flags=re.I | re.M)
    
    # Normalize whitespace
    text = re.sub(r'\s*\n\s*', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Step 2A: Try VERSUS pattern first (for formats like Sample 4)
    # This handles "NAME\nVERSUS\nNAME" which becomes "NAME VERSUS NAME" after normalization
    versus_pattern = re.compile(
        r'([A-Z][A-Z\s\.,&]+?)\s+'  # Left party (uppercase words)
        r'(?:VERSUS|V[Ss]?\.?)\s+'  # VERSUS or v. or vs.
        r'([A-Z][A-Z\s\.,&]+?)'     # Right party
        r'(?=\s*(?:'                 # Stop before these markers
        r'IN THE|Date|CORAM|Bench|'
        r'Advocate|Advs\.|represented|'
        r'\(|$'
        r'))',
        re.IGNORECASE
    )
    
    versus_match = versus_pattern.search(text)
    if versus_match:
        left = versus_match.group(1).strip()
        right = versus_match.group(2).strip()
        
        # Clean both parties
        left = _clean_party_chunk(left)
        right = _clean_party_chunk(right)
        
        if left and right and len(left) >= 3 and len(right) >= 3:
            return f"{left} v. {right}"
    
    # Step 2B: Try standard "v." pattern (for typical Supreme Court format)
    pattern = re.compile(
        r'([A-Z][A-Za-z0-9\.\s\-&,\'\/]{2,80}?)\s+'  # Left party
        r'v\.?s?\.?\s+'  # "v." or "vs" or "v.s."
        r'([A-Z][A-Za-z0-9\.\s\-&,\'\/]{2,80}?)'  # Right party
        r'(?=\s*(?:'  # Stop before these markers
        r'Petitioner|Respondent|Appellant|'
        r'\(Criminal|IN THE|Date|CORAM|'
        r'Appearances|Advs\.|'
        r'\[|\(|$'
        r'))',
        re.IGNORECASE
    )
    
    match = pattern.search(text)
    
    if not match:
        # Check for "In Re" matters
        in_re = re.search(r'\bIn\s+Re[:\-]?\s*([A-Z][A-Za-z\s]{5,60})', text, re.I)
        if in_re:
            name = in_re.group(1).strip()
            return f"In Re {_clean_party_chunk(name)}"
        return None
    
    left = match.group(1).strip()
    right = match.group(2).strip()
    
    # Step 3: Clean both parties
    left = _clean_party_chunk(left)
    right = _clean_party_chunk(right)
    
    # Validation
    if not left or not right:
        return None
    
    if len(left) < 3 or len(right) < 3:
        return None
    
    # Format with standardized "v."
    case_name = f"{left} v. {right}"
    return case_name


def _clean_party_chunk(chunk: str) -> str:
    """Enhanced cleaning for party name chunks."""
    if not chunk:
        return ""
    
    # Remove "& Anr." and similar
    chunk = re.sub(r'\b(?:&\s*Anr\.?|&\s*Ors\.?|and\s+Another|and\s+Others)\b', '', chunk, flags=re.I)
    
    # Remove role markers
    chunk = re.sub(r'\b(?:Petitioner|Appellant|Respondent|Defendant)\b.*$', '', chunk, flags=re.I)
    
    # Remove dates
    chunk = re.sub(r'\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b', '', chunk)
    chunk = re.sub(r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b', '', chunk, flags=re.I)
    
    # Remove citations
    chunk = re.sub(r'\[\d{4}\]', '', chunk)
    chunk = re.sub(r'\(\d{4}\)', '', chunk)
    chunk = re.sub(r'\b(?:SCC|SCR|INSC|AIR)\s+\d+', '', chunk, flags=re.I)
    
    # Remove case numbers
    chunk = re.sub(r'\bNo\.?\s*\d+', '', chunk, flags=re.I)
    chunk = re.sub(r'\bCriminal\s+Appeal\b.*$', '', chunk, flags=re.I)
    
    # Remove "Rep. by" and similar
    chunk = re.sub(r'\bRep(?:resented)?\.?\s+by\b.*$', '', chunk, flags=re.I)
    chunk = re.sub(r'\bThrough\b.*$', '', chunk, flags=re.I)
    
    # Remove trailing prepositions
    chunk = re.sub(r'\s+(?:in|of|the|at|to)\s*$', '', chunk, flags=re.I)
    
    # Clean whitespace
    chunk = re.sub(r'\s+', ' ', chunk).strip(' .,;:-')
    
    return chunk


def normalize_case_name(name: Optional[str]) -> Optional[str]:
    """Final normalization with better consistency."""
    if not name:
        return None
    
    # Standardize v. variations
    name = re.sub(r'\s+[Vv][Ss]?\.?\s+', ' v. ', name)
    
    # Remove trailing "v." if hanging
    name = re.sub(r'\s+v\.?\s*$', '', name)
    
    # Remove multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Ensure first letter capitalized
    if name:
        name = name[0].upper() + name[1:] if len(name) > 1 else name.upper()
    
    return name if name else None


def make_case_name(appellants: List[str], respondents: List[str]) -> Optional[str]:
    """Build case name from party lists."""
    left = ", ".join(appellants) if appellants else ""
    right = ", ".join(respondents) if respondents else ""
    if left and right:
        return f"{left} v. {right}"
    return left or right or None


# Keep other functions from original selectors.py
def select_primary_case_number(case_numbers: List[str]) -> Optional[str]:
    """Choose the most informative case number."""
    if not case_numbers:
        return None
    cleaned = []
    seen = set()
    for c in case_numbers:
        c2 = c.strip()
        key = re.sub(r'\s+', ' ', c2).lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(c2)
    
    priorities = ["appeal", "crl", "crl.o.p", "w.p.", "c.a.", "c.c.", "crime no", "rcc", "case no", "civil appeal", "civil ap"]
    for p in priorities:
        for c in cleaned:
            if p in c.lower():
                return c
    return max(cleaned, key=len)


def select_primary_court(courts: List[str]) -> Optional[str]:
    """Choose most authoritative court."""
    if not courts:
        return None
    unique = []
    seen = set()
    for c in courts:
        if not c:
            continue
        c2 = re.sub(r'\s+', ' ', c.strip())
        key = c2.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(c2)

    def score(name: str) -> int:
        n = name.lower()
        if "supreme court of india" in n or "supreme court" in n:
            return 100
        if "high court of judicature" in n or re.search(r'high court of\b', n):
            return 80
        if "high court" in n:
            return 70
        if "district court" in n:
            return 40
        if "judicial magistrate" in n:
            return 30
        return 10

    best = max(unique, key=score)
    best = re.sub(r'\bSUPREME COURT OF INDIA\b', 'Supreme Court of India', best, flags=re.I)
    best = re.sub(r'\bHIGH COURT OF JUDICATURE AT\b', 'High Court of', best, flags=re.I)
    return best.strip()


def _try_parse_date(s: str) -> Optional[datetime]:
    """Parse date string."""
    s = s.strip()
    if not s:
        return None
    s = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', s, flags=re.I)
    fmts = [
        "%d %B %Y", "%d %b %Y", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y",
        "%d %B, %Y", "%d %b, %Y", "%d %m %Y",
        "%d.%m.%y", "%d/%m/%y", "%d-%m-%y",
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except Exception:
            continue
    
    m = re.search(r'(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})', s)
    if m:
        d, mon, y = m.groups()
        try:
            return datetime.strptime(f"{d} {mon} {y}", "%d %B %Y")
        except Exception:
            try:
                return datetime.strptime(f"{d} {mon} {y}", "%d %b %Y")
            except Exception:
                return None
    return None


def select_primary_date(dates: List[str], header_text: Optional[str] = None) -> Optional[str]:
    """Pick the judgment date."""
    if not dates:
        return None

    seen = set()
    candidates = []
    for d in dates:
        d2 = d.strip()
        if not d2:
            continue
        key = d2.lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(d2)

    if header_text:
        header_lower = header_text.lower()
        for d in candidates:
            if d.lower() in header_lower:
                return d

    parsed = []
    for d in candidates:
        dt = _try_parse_date(d)
        parsed.append((d, dt))
    
    now = datetime.now()
    valid = [(s, dt) for s, dt in parsed if dt is not None and dt <= now]
    if valid:
        chosen = max(valid, key=lambda x: x[1])[0]
        return chosen

    return candidates[0] if candidates else None