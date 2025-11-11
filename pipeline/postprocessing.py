# postprocessing.py
# Merge BERT (with provenance) outputs and spaCy/regex outputs into canonical dict.
# Accepts the same inputs as your original app: bert_ents_list and spacy_regex_ents.

import re
from collections import defaultdict
from typing import List, Tuple, Dict


def _clean_whitespace(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip(' ,;:\n\t')


def _normalize_statute(s: str) -> str:
    s = s.strip()
    s = re.sub(r'\bNI Act\b', 'Negotiable Instruments Act, 1881', s, flags=re.I)
    s = re.sub(r'\bCrPC\b', 'Code of Criminal Procedure, 1973', s, flags=re.I)
    s = re.sub(r'\bIPC\b', 'Indian Penal Code, 1860', s, flags=re.I)
    s = re.sub(r'\bIT Act\b', 'Information Technology Act, 2000', s, flags=re.I)
    s = re.sub(r'\bBNS\b', 'Bharatiya Nyaya Sanhita, 2023', s, flags=re.I)
    return s


def _is_probable_lawyer(name: str) -> bool:
    if not name:
        return False
    parts = name.split()
    if len(parts) < 2:
        return False
    # Reject obvious organizations / states
    if re.search(r'\b(state|government|department|commission|bank|society|university|corporation|limited|pvt|ltd|company|union)\b', name, re.I):
        return False
    # Reject very short tokens
    if len(name) < 4:
        return False
    return True


def _clean_party_name(name: str) -> str:
    """
    Cleans noisy petitioner/respondent text blocks that contain headers,
    citations, or unrelated words.
    """
    name = _clean_whitespace(name)
    # Remove leading court / section headers
    name = re.sub(r'^(in the\s+supreme\s+court.*|before\s+the.*|civil\s+appellate\s+jurisdiction.*)', '', name, flags=re.I)
    # Remove labels like 'Petitioner:' / 'Respondent:'
    name = re.sub(r'^(petitioner|appellant|respondent|defendant|plaintiff)\s*[:\-]\s*', '', name, flags=re.I)
    # Remove citation-like tokens
    name = re.sub(r'\(?\d{4}\)?\s*(SCC|SCR|AIR|All ER).*', '', name, flags=re.I)
    # Truncate at "represented by", "through", etc.
    name = re.split(r'\brepresented by\b|\bthrough\b|\bfiled\b|\bunder\b', name, flags=re.I)[0]
    # Remove trailing role words
    name = re.sub(r'\b(petitioner|appellant|respondent|defendant|plaintiff)\b$', '', name, flags=re.I)
    name = name.strip(" ,;:-")
    return name


def _label_key(label: str) -> str:
    mapping = {
        "CASE_NUMBER": "case_number",
        "CASE": "case_number",
        "COURT": "court",
        "DATE": "date",
        "JUDGE": "coram",
        "CORAM": "coram",
        "PETITIONER": "petitioner",
        "APPELLANT": "petitioner",
        "RESPONDENT": "respondent",
        "PRECEDENT": "precedent",
        "PRECEDENTS": "precedent",
        "PROVISION": "provision",
        "STATUTE": "statute",
        "LAWYER": "lawyer",
        "GPE": "gpe",
        "ORGANIZATION": "organization",
    }
    return mapping.get(label.upper(), label.lower())


def _deduplicate_precedents(precedents: List[str]) -> List[str]:
    """
    Remove near-duplicate precedents using fuzzy matching
    """
    from difflib import SequenceMatcher

    if not precedents:
        return []

    unique = []
    seen_base_names = set()

    precedents_sorted = sorted(set(precedents), key=len, reverse=True)

    for prec in precedents_sorted:
        base = re.sub(r'\s*\(\d{4}\).*$', '', prec).strip()
        base = re.sub(r'\s+(SCC|SCR|AIR).*$', '', base, flags=re.I).strip()
        base_lower = base.lower()
        if len(base) < 10:
            continue
        is_duplicate = False
        for seen in seen_base_names:
            if SequenceMatcher(None, base_lower, seen).ratio() > 0.85:
                is_duplicate = True
                break
        if not is_duplicate:
            unique.append(prec)
            seen_base_names.add(base_lower)

    return unique[:15]


def merge_entities(bert_ents_list: List[Tuple[str, str]], spacy_regex_ents: List[Tuple[str, str]]) -> Dict[str, List[str]]:
    """
    Merge BERT and spaCy/regex entities into unified canonical dict.
    """
    accum = defaultdict(list)

    # 1) Collect BERT entities
    for label, raw in (bert_ents_list or []):
        lab = label.upper().strip()
        m = re.match(r'^(.*?)(?:\s*\[(header|body)\])?\s*$', raw or '')
        if m:
            val = _clean_whitespace(m.group(1) or "")
            prov = (m.group(2) or "").lower()
        else:
            val = _clean_whitespace(raw)
            prov = ""
        if not val:
            continue
        key = _label_key(lab)
        if key == "statute":
            val = _normalize_statute(val)
        if key == "coram":
            val = re.sub(r"Hon['’]?\s*ble\.?\s*", '', val, flags=re.I)
            val = re.sub(r'\bMr\.?\s+Justice\b', 'Justice', val)
        accum[key].append((val, prov or "bert"))

    # 2) Add spaCy/regex entities
    for label, val in (spacy_regex_ents or []):
        if not val:
            continue
        key = _label_key(label)
        v = _clean_whitespace(val)
        if key == "statute":
            v = _normalize_statute(v)
        accum[key].append((v, "spacy"))

    # 3) Prioritize and clean
    final = {}
    for key, items in accum.items():
        header_vals, bert_vals, spacy_vals = [], [], []
        for v, prov in items:
            prov_l = (prov or "").lower()
            if "header" in prov_l:
                header_vals.append(v)
            elif prov_l == "bert":
                bert_vals.append(v)
            else:
                spacy_vals.append(v)

        combined = header_vals + bert_vals + spacy_vals

        if key == "precedent":
            combined = _deduplicate_precedents(combined)

        cleaned = []
        seen = set()
        for v in combined:
            if not v:
                continue
            v2 = v.strip().strip('.,;:')
            if key == "coram":
                if re.match(r'^(and|&|-)$', v2, re.I):
                    continue
                if len(v2.split()) == 1 and not re.search(r'justice', v2, re.I):
                    if not ('.' in v2 or v2.isupper()):
                        continue
                v2 = re.sub(r"^(Hon['’]?\s*ble\.?\s*)", '', v2, flags=re.I).strip()

            if key in {"petitioner", "respondent"}:
                v2 = _clean_party_name(v2)
                if not v2 or len(v2.split()) < 2:
                    continue
            elif key == "organization":
                if re.match(r'^[A-Z\s]{3,200}$', v2) and len(v2.split()) > 2:
                    continue

            if key == "lawyer":
                v2 = re.sub(r'\b(Sr\.?\s*Adv|Advocate|Adv\.|A\.S\.G\.?|A\.A\.G\.?|AOR)\b', '', v2, flags=re.I).strip()
                if not _is_probable_lawyer(v2):
                    continue
            if key == "statute":
                if len(v2) < 6:
                    continue
            if key == "precedent":
                if len(v2) < 15:
                    continue

            k_lower = v2.lower()
            if k_lower in seen:
                continue
            seen.add(k_lower)
            cleaned.append(v2)

        final[key] = cleaned

    # 4) Ensure all expected keys exist
    expected = [
        "case_number", "court", "date", "coram", "petitioner", "respondent",
        "lawyer", "precedent", "provision", "statute", "gpe", "organization"
    ]
    for k in expected:
        if k not in final:
            final[k] = []

    # 5) Compatibility extras
    final["extra_case_numbers"] = final.get("case_number", [])[1:] if len(final.get("case_number", [])) > 1 else []
    final["extra_courts"] = final.get("court", [])[1:] if len(final.get("court", [])) > 1 else []
    final["extra_dates"] = final.get("date", [])[1:] if len(final.get("date", [])) > 1 else []

    # 6) Fallback: infer parties from case name
    def _infer_parties_from_case_name(case_name):
        if not case_name or " v" not in case_name.lower():
            return None, None
        parts = re.split(r'\s+v[.]?s?[.]?\s+', case_name, flags=re.I)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
        return None, None

    if not final.get("petitioner") and not final.get("respondent"):
        cname = ""
        if "case_name" in final and final["case_name"]:
            cname = final["case_name"][0]
        pet, resp = _infer_parties_from_case_name(cname)
        if pet:
            final["petitioner"].append(pet)
        if resp:
            final["respondent"].append(resp)

    return final
