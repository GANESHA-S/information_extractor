# spacy_pipeline.py
# Loads spaCy EntityRuler patterns (if available) and applies robust regex heuristics.
# Returns list of tuples (LABEL, value) to be merged by postprocessing.merge_entities.

import json
import re
from typing import List, Tuple, Optional

try:
    import spacy
except Exception:
    spacy = None  # spaCy may not be installed in some environments


def load_spacy_ruler(patterns_path: str = 'data/entityruler_patterns.jsonl'):
    """
    Return a spaCy nlp pipeline with entity_ruler loaded if possible.
    If spaCy or patterns file is not available, returns a minimal blank-like object
    with a .__call__ that yields no ents.
    """
    if spacy is None:
        # dummy object with minimal interface
        class DummyNLP:
            def __call__(self, text):
                class Doc:
                    ents = []
                return Doc()
        return DummyNLP()

    nlp = spacy.blank("en")
    try:
        ruler = nlp.add_pipe("entity_ruler")
        with open(patterns_path, "r", encoding="utf-8") as f:
            patterns = [json.loads(line) for line in f if line.strip()]
        ruler.add_patterns(patterns)
    except Exception:
        # if file missing or entity_ruler not available, return blank pipeline
        pass
    return nlp


def _anchor_block_after(text: str, anchor_list: List[str], max_chars: int = 600) -> Optional[str]:
    """
    Find first occurrence of any anchor phrase and return the following block (up to max_chars).
    """
    for a in anchor_list:
        pat = re.compile(r'(?im)'+re.escape(a)+r'\s*[:\-]?\s*(.+)')
        m = pat.search(text)
        if m:
            block = m.group(1).strip()
            # cut at newline double break or period after long string
            if len(block) > max_chars:
                block = block[:max_chars]
            return block
    return None


def apply_spacy_and_regex(text: str, spacy_nlp) -> List[Tuple[str, str]]:
    """
    Returns list like: [("CASE_NUMBER","..."), ("DATE","..."), ("LAWYER","..."), ...]
    """
    entities: List[Tuple[str, str]] = []

    # 1) spaCy entity ruler (if loaded)
    try:
        doc = spacy_nlp(text)
        for ent in getattr(doc, "ents", []) or []:
            label = getattr(ent, "label_", None)
            txt = getattr(ent, "text", None)
            if label and txt:
                entities.append((label.upper(), txt.strip()))
    except Exception:
        # ignore if spaCy not configured
        pass

    # 2) CASE numbers (comprehensive patterns)
    case_patts = [
        r'\bW\.P\.\s*\(C\)\s*No\.?\s*\d{1,6}(?:/\d{2,4}|\s+of\s+\d{4})?\b',
        r'\bW\.A\.\s*No\.?\s*\d{1,6}\b',
        r'\bCrl\.A?\.?\s*No\.?\s*\d{1,6}\b',
        r'\bC\.A\.?\s*No\.?\s*\d{1,6}\b',
        r'\bSLP\s*No\.?\s*\d{1,6}\b',
        r'\bI\.A\.?\s*No\.?\s*\d{1,6}\b',
        r'\bCrl\.?\.?O\.?P\.?\.?No\.?\s*\d+\b',
        r'\bCrime\s+No\.?\s*\d+\b',
        r'\bC\.?C\.?\.?\s*No\.?\s*\d+\b',
        r'\b(?:Case\s+)?No\.?\s*\d{1,6}(?:/\d{2,4})?\b',
    ]
    for pat in case_patts:
        for m in re.finditer(pat, text, re.I):
            entities.append(("CASE_NUMBER", m.group(0).strip()))

    # 3) DATES (robust)
    date_patts = [
        r'\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b',
        r'\b\d{1,2}(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
        r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2,4}\b',
        r'\b\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s*,?\s*\d{4}\b',
    ]
    for pat in date_patts:
        for m in re.finditer(pat, text, re.I):
            val = m.group(0).strip()
            # skip short numeric tokens that are likely not dates
            if re.search(r'\b(SCC|SCR|Vol|No\.)\b', val, re.I):
                continue
            entities.append(("DATE", val))

    # 4) COURTS
    court_pattern = r'(Supreme Court(?: of India)?|High Court of Judicature at [A-Za-z ]+|High Court(?: of [A-Za-z ]+)?|District Court(?: of [A-Za-z ]+)?)'
    for m in re.finditer(court_pattern, text, re.I):
        entities.append(("COURT", m.group(0).strip()))

    # 5) CORAM / JUDGES: restrict to header-ish area (first ~1200 chars)
    header_snippet = text[:1200]
    # patterns like "[B.V. Nagarathna and Satish Chandra Sharma, JJ.]" or "CORAM: Justice X, Justice Y"
    match_coram = re.search(r'\[([^\]]{2,400})\]', header_snippet)
    if match_coram:
        block = match_coram.group(1)
        # remove trailing JJ or J.
        block = re.sub(r'\bJJ?\.?\b', '', block, flags=re.I)
        parts = re.split(r',|\band\b|&', block)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            # ensure it's not plain 'and'
            if re.match(r'^(and|&)$', p, re.I):
                continue
            # if it's a short single token like "and" or "Mehta", keep only if it looks like a name
            if len(p.split()) == 1 and not re.search(r'\b[A-Z][a-z]+', p):
                continue
            entities.append(("JUDGE", p))
    else:
        # fallback: look for "Coram" or "Coram:" lines
        for m in re.finditer(r'(?im)^\s*Coram[:\s\-]?\s*(.+)$', header_snippet):
            block = m.group(1).strip()
            block = re.sub(r'\bJJ?\.?\b', '', block, flags=re.I)
            for p in re.split(r',|\band\b|&', block):
                p = p.strip()
                if p and not re.match(r'^(and|&)$', p, re.I):
                    entities.append(("JUDGE", p))

    # 6) LAWYERS: anchored blocks first ("Advs. for the Appellant", "For Petitioner", etc.)
    anchor_variants = [
        'Advs. for the Appellant', 'Advs. for the Respondent', 'Advocate for Applicants',
        'Advocate for Respondent', 'For Petitioner', 'For Respondent', 'For Appellant',
        'Appearances for Parties', 'Appearances'
    ]
    for anchor in anchor_variants:
        block = _anchor_block_after(text, [anchor], max_chars=800)
        if block:
            # split common separators
            parts = re.split(r',\s*|\s+and\s+|;|\n', block)
            for p in parts:
                p = p.strip().strip('.')
                # keep those that look like person names or have honorifics
                if re.match(r'^(Mr|Ms|Mrs|Shri|Smt|Dr|Adv)\.?', p, re.I) or re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', p):
                    # remove trailing role words like 'Sr. Advs.' etc
                    p2 = re.sub(r'\b(Sr\.?\s*Adv|Sr\.?\s*Advocate|Sr Advs|Adv\.?)\b', '', p, flags=re.I).strip()
                    if p2 and not re.search(r'\b(State of|Union of|Government)\b', p2, re.I):
                        entities.append(("LAWYER", p2))

    # generic honorific search as fallback (avoid capturing "State of ...")
    for m in re.finditer(r'\b(Mr|Ms|Mrs|Shri|Smt|Dr|Adv)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b', text):
        candidate = m.group(0).strip()
        if not re.search(r'\b(State of|Union of|Government|Registry|Court)\b', candidate, re.I):
            entities.append(("LAWYER", candidate))

    # 7) PRECEDENTS: IMPROVED - validate both sides and filter junk
    precedent_pattern = r'\b([A-Z][A-Za-z.\-&\s]{3,50})\s+v\.?\s+([A-Z][A-Za-z.\-&\s]{3,50})(?:\s*\((\d{4})\))?\b'
    for m in re.finditer(precedent_pattern, text):
        left = m.group(1).strip()
        right = m.group(2).strip()
        year = m.group(3)
        
        # Validate both sides are substantial
        if len(left.split()) >= 2 and len(right.split()) >= 2:
            # Reject if both sides are generic words
            if not (left.lower() in ['state', 'union'] and right.lower() in ['state', 'union', 'india']):
                case_name = f"{left} v. {right}"
                if year:
                    case_name += f" ({year})"
                entities.append(("PRECEDENT", case_name))

    # 8) PROVISIONS
    for m in re.finditer(r'\bSection\s+\d+[A-Za-z]?(?:\s*\([a-z0-9]+\))?(?:\s+read with\s+Section\s+\d+[A-Za-z]?)?', text, re.I):
        entities.append(("PROVISION", m.group(0).strip()))

    # 9) STATUTES (explicit list for higher precision)
    statutes_list = [
        "Indian Penal Code", "Negotiable Instruments Act", "Code of Criminal Procedure",
        "Companies Act", "Information Technology Act", "Bharatiya Nyaya Sanhita",
        "Dowry Prohibition Act", "Constitution"
    ]
    for statute in statutes_list:
        for m in re.finditer(re.escape(statute) + r'(?:,?\s*\d{4})?', text, re.I):
            entities.append(("STATUTE", m.group(0).strip()))

    # 10) PETITIONER / RESPONDENT anchored header lines
    party_patterns = [
        (r'^\s*Petitioner(?:\(s\))?\s*[:\-]?\s*(.+)$', "PETITIONER"),
        (r'^\s*Appellant(?:\(s\))?\s*[:\-]?\s*(.+)$', "PETITIONER"),
        (r'^\s*Respondent(?:\(s\))?\s*[:\-]?\s*(.+)$', "RESPONDENT"),
    ]
    for pat, lab in party_patterns:
        for m in re.finditer(pat, text, re.I | re.M):
            line = m.group(1).strip()
            parts = re.split(r',\s*|\s+and\s+|\s*&\s*|;', line)
            for p in parts:
                p = p.strip().strip(':-.,')
                # skip uppercase banner lines
                if re.match(r'^[A-Z\s]{3,200}$', p) and len(p.split()) > 2:
                    continue
                if len(p) >= 3:
                    entities.append((lab, p))

    # 11) GPE seeds (small list)
    for city in ["Delhi", "Mumbai", "Bhopal", "Jaora", "Guna", "Gwalior", "Chennai", "Hyderabad", "Bengaluru", "Pune", "Aurangabad", "Vaniyambadi"]:
        if re.search(r'\b' + re.escape(city) + r'\b', text):
            entities.append(("GPE", city))

    # Final dedupe while preserving order
    seen = set()
    out = []
    for lab, val in entities:
        key = f"{lab}||{val}".lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((lab, val))
    return out