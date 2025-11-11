# ner_predictor.py
import re
from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline


def load_legalbert_model(model_path='model/legalbert2.0'):
    """
    Load the fine-tuned LegalBERT model/pipeline.
    """
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForTokenClassification.from_pretrained(model_path)
    nlp = pipeline("ner", model=model, tokenizer=tokenizer)
    return nlp


# Cleaned-up label set (no Witness/Actor)
ALL_LABELS = [
    "CASE_NUMBER", "COURT", "DATE", "JUDGE", "PETITIONER", "RESPONDENT",
    "PRECEDENT", "PROVISION", "STATUTE", "LAWYER", "ORGANIZATION", "GPE"
]


def normalize_entity(label, value):
    """
    Lightweight normalization that is safe to run pre-merge.
    Heavier normalization happens in postprocessing.
    """
    if label == "organization":
        value = value.replace("Ltd", "Limited").replace("Pvt", "Private").replace("&", "and")
        if value.startswith("In "):
            value = value[3:]
        if value.startswith("This Court in"):
            value = value.replace("This Court in", "").strip()
        if value.strip() == "Private. Limited":
            return ""
    if label == "statute":
        if "NI Act" in value or "Negotiable Instrument" in value:
            value = "Negotiable Instruments Act, 1881"
        if "CrPC" in value:
            value = "Code of Criminal Procedure, 1973"
    return value.strip()


def clean_bert_output(entities):
    """
    Keep only reasonable spans and standardize capitalization for a few labels.
    Input: list of (LABEL, VALUE)
    """
    clean_entities = []
    for label, value in entities:
        value = value.strip()
        value = re.sub(r'^[\W_]+', '', value)
        if not value or len(value) < 3:
            continue
        if label in {"JUDGE", "PRECEDENT", "PETITIONER", "RESPONDENT"} and len(value) > 1:
            value = value[0].upper() + value[1:]
        clean_entities.append((label, value))
    return clean_entities


def _flush_current_span(buffer, text, grouped):
    """
    Internal helper to flush the current token-span buffer.
    """
    if buffer["entity"]:
        span = text[buffer["start"]:buffer["end"]]
        span = re.sub(r'\s+', ' ', span.replace('\n', ' ')).strip(' ,.;:')
        if len(span) > 1:
            grouped.append((buffer["entity"], span))
    buffer.update({"entity": None, "start": None, "end": None})


def post_process_ner(text, raw_preds):
    """
    Group BERT token predictions into spans and enrich with fallback regex.
    Returns: dict[label -> sorted(list(values))]
    Implements Quick Wins:
      - Expanded DATE patterns (ordinals, abbreviated months).
      - Expanded CASE_NUMBER patterns (W.P.(C), Crl.A., etc.).
      - Anchored Petitioner/Respondent splitting via headers.
    """
    # ---------- 1) Group BERT token-level predictions into spans ----------
    grouped = []
    current = {"entity": None, "start": None, "end": None}

    for token in raw_preds:
        entity = token.get("entity", "O").split("-")[-1]
        if entity == "O":
            _flush_current_span(current, text, grouped)
            continue

        # Continue the same entity
        if current["entity"] == entity:
            current["end"] = token["end"]
        else:
            _flush_current_span(current, text, grouped)
            current.update({"entity": entity, "start": token["start"], "end": token["end"]})

    _flush_current_span(current, text, grouped)

    # ---------- 2) Fallback Regex (expanded) ----------
    fallback_matches = []

    # === CASE_NUMBER (Expanded) ===
    # Capture common Indian case styles and canonical abbreviations
    case_patterns = [
        # Specific forms first
        r"\bW\.P\.\s*\(C\)\s*No\.?\s*\d{1,6}(?:/\d{2,4}|\s+of\s+\d{4})?\b",
        r"\bW\.A\.\s*No\.?\s*\d{1,6}(?:/\d{2,4}|\s+of\s+\d{4})?\b",
        r"\bCrl\.A\.?\s*No\.?\s*\d{1,6}(?:/\d{2,4}|\s+of\s+\d{4})?\b",
        r"\bC\.A\.?\s*No\.?\s*\d{1,6}(?:/\d{2,4}|\s+of\s+\d{4})?\b",
        r"\bSLP(?:\s*\(C\))?\s*No\.?\s*\d{1,6}(?:/\d{2,4}|\s+of\s+\d{4})?\b",
        r"\bI\.A\.?\s*No\.?\s*\d{1,6}(?:/\d{2,4}|\s+of\s+\d{4})?\b",
        r"\bCrl\.?\.?O\.?P\.?\.?No\.?\s*\d+\s*(?:of\s*\d{4})?\b",  # Crl.O.P.No.20644 of 2025
        r"\bCrime\s+No\.?\s*\d+\s*(?:of\s*\d{4})?\b",              # Crime No.160 of 2025

        # Generic families (keep at end)
        r"\b(?:Criminal|Civil)?\s*(?:Appeal|W\.?P\.?|Complaint|RCC|SLP|I\.?A\.?|Crl\.A\.|C\.?C\.?|C\.?R\.?P\.?)\s*No\.?\s*\d{1,6}(?:/\d{2,4}|\s+of\s+\d{4})?\b",
        r"\b(?:Case\s+)?No\.?\s*\d{1,6}(?:/\d{2,4})?\b",
    ]
    for pattern in case_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            val = m.group(0).strip()
            fallback_matches.append(("CASE_NUMBER", val))

    # === PROVISION ===
    provision_pattern = r"Section\s+\d+[A-Za-z]?(?:\s*\([a-z0-9]+\))?(?:\s+read with\s+Section\s+\d+[A-Za-z]?)?"
    for m in re.finditer(provision_pattern, text, re.IGNORECASE):
        fallback_matches.append(("PROVISION", m.group(0).strip()))

    # === DATE (Expanded: ordinals + abbreviated months) ===
    date_patterns = [
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",  # 12.03.2025, 12-03-25
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",  # 15th March 2025
        r"\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2,4}\b",  # 15 Aug 23/2023
        r"\b\d{1,2}-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4}\b",      # 15-Aug-23
    ]
    for pattern in date_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            val = m.group(0).strip()
            # light noise filter (avoid SCC citations, money etc.)
            if not re.search(r"\b(SCC|SCR|lakhs?|lakh|crore)\b", val, re.IGNORECASE):
                fallback_matches.append(("DATE", val))

    # === COURT (basic) ===
    court_pattern = r"(Supreme Court(?: of India)?|High Court(?: of [A-Za-z ]+)?|High Court of Judicature at [A-Za-z ]+|District Court(?: of [A-Za-z ]+)?|Judicial Magistrate Court, [A-Za-z ]+)"
    for m in re.finditer(court_pattern, text, re.IGNORECASE):
        fallback_matches.append(("COURT", m.group(0).strip()))

    # === JUDGE ===
    judge_patterns = [
        r"\bHon[’']?ble\s*(?:Mr\.?|Ms\.?)?\s*Justice\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b",
        r"\bJustice\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b",
        r"\bMr\.?\s+Justice\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b",
        r"\bMs\.?\s+Justice\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b",
        r"\bCoram\s*:\s*(?:Hon[’']?ble\s*)?(?:Mr\.?|Ms\.?)?\s*Justice\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b",
        r"\bBefore\s*:\s*(?:Hon[’']?ble\s*)?(?:Mr\.?|Ms\.?)?\s*Justice\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b",
        r"\b(A|B|C|D|E|F|G|H|I|J|K|L|M|N|O|P|Q|R|S|T|U|V|W|X|Y|Z)[a-z]+(?:\s+[A-Z][a-z]+)+\s*,?\s*J\.\b",
    ]
    for pattern in judge_patterns:
        for m in re.finditer(pattern, text):
            fallback_matches.append(("JUDGE", m.group(0).strip()))

    # === LAWYER === (anchored blocks and generic honorifics)
    # Anchored: "For Petitioner: ..." / "For Respondent: ..."
    for block in re.findall(r"(?:For\s+(?:Petitioner|Respondent)[^:]*:\s*)([^\n]+)", text, re.IGNORECASE):
        names = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[A-Z]\.\s?[A-Z][a-z]+", block)
        for name in names:
            n = name.strip()
            if len(n.split()) >= 2 and n.lower() not in {"information technology"}:
                fallback_matches.append(("LAWYER", n))

    generic_lawyer = r"\b(?:Mr|Ms|Mrs|Adv|Advocate|Shri|Smt)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b"
    for m in re.finditer(generic_lawyer, text):
        fallback_matches.append(("LAWYER", m.group(0).strip()))

    # === PRECEDENT ===
    precedent_pattern = r"\b[A-Z][A-Za-z.\-&\s]+?\s+v\.?\s+[A-Z][A-Za-z.\-&\s]+?(?:\s*\(\d{4}\)\s*\d+\s*SCC\s*\d+)?\b"
    for m in re.finditer(precedent_pattern, text):
        fallback_matches.append(("PRECEDENT", m.group(0).strip()))

    # === STATUTE ===
    statute_pattern = r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+)?(?:Act|Code|Rules|Regulations|Constitution)(?:,\s*\d{4})?\b"
    for m in re.finditer(statute_pattern, text):
        val = m.group(0).strip()
        if len(val.split()) > 2 and len(val) < 100 and val.lower() not in {"supreme court reports"}:
            fallback_matches.append(("STATUTE", val))

    # === GPE (very light list, just to seed) ===
    for city in ["Delhi", "Mumbai", "Bhopal", "Jaora", "Guna", "Gwalior", "Madhya Pradesh", "Chennai", "Hyderabad"]:
        if city.lower() in text.lower():
            fallback_matches.append(("GPE", city))

    # === PETITIONER / RESPONDENT (Quick Win splitter via anchored headers) ===
    # Example lines:
    #   Petitioner(s): A, B & C
    #   Respondent(s): State of Tamil Nadu; D and E
    header_specs = [
        ("PETITIONER", r"^\s*Petitioner\(s\)?:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
        ("RESPONDENT", r"^\s*Respondent\(s\)?:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    ]
    for label, pat, flags in header_specs:
        for line in re.findall(pat, text, flags):
            # split by comma, ' and ', '&'
            parts = re.split(r",\s*|\s+and\s+|\s*&\s*", line)
            for p in parts:
                candidate = p.strip().strip(":-;.,")
                # drop role-words inside the chunk
                candidate = re.sub(r"\b(Petitioner|Respondent|Appellant|Defendant|Complainant)\b", "", candidate, flags=re.IGNORECASE).strip()
                if len(candidate) >= 3:
                    fallback_matches.append((label, candidate))

    # ---------- 3) Merge BERT + Regex ----------
    entity_dict = {label: set() for label in ALL_LABELS}

    # BERT groups first
    for label, span in grouped:
        lab = label.upper().strip()
        value = re.sub(r'\s+', ' ', span.replace('\n', ' ')).strip(' ,.;:\n')
        value = normalize_entity(lab.lower(), value)
        if value and lab in entity_dict:
            entity_dict[lab].add(value)

    # Regex fallbacks
    for label, span in fallback_matches:
        lab = label.upper().strip()
        value = re.sub(r'\s+', ' ', span.replace('\n', ' ')).strip(' ,.;:\n')
        value = normalize_entity(lab.lower(), value)
        if value and lab in entity_dict:
            entity_dict[lab].add(value)

    # Convert to lowercase keys for downstream postprocessing.merge
    final = {label.lower(): sorted(list(values)) for label, values in entity_dict.items() if values}
    return final
