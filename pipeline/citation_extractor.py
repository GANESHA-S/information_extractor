# pipeline/citation_extractor.py
"""
Extract and structure legal citations from judgment text
"""

import re
from typing import List, Dict, Optional
from collections import defaultdict


def extract_citations(text: str) -> Dict[str, List[str]]:
    """
    Extract structured citations from judgment text.
    
    Returns:
        Dict with citation types: SCC, SCR, AIR, etc.
    """
    if not text:
        return {}
    
    citations = defaultdict(list)
    
    # SCC citations: (2023) 5 SCC 123
    scc_pattern = r'\(\d{4}\)\s*\d+\s*SCC\s*\d+(?:\s*\([A-Z]+\))?'
    for match in re.finditer(scc_pattern, text):
        citations['SCC'].append(match.group(0).strip())
    
    # SCR citations: (2023) 2 SCR 456
    scr_pattern = r'\(\d{4}\)\s*\d+\s*SCR\s*\d+'
    for match in re.finditer(scr_pattern, text):
        citations['SCR'].append(match.group(0).strip())
    
    # AIR citations: AIR 2023 SC 789
    air_pattern = r'AIR\s+\d{4}\s+(?:SC|Supreme Court|Delhi|Bombay|Calcutta|Madras|[A-Z]{2,})\s+\d+'
    for match in re.finditer(air_pattern, text, re.IGNORECASE):
        citations['AIR'].append(match.group(0).strip())
    
    # Supreme Court Reports: 2023 SCC OnLine SC 1234
    online_pattern = r'\d{4}\s+SCC\s+OnLine\s+(?:SC|[A-Z]{2,})\s+\d+'
    for match in re.finditer(online_pattern, text):
        citations['SCC_Online'].append(match.group(0).strip())
    
    # Deduplicate
    for key in citations:
        citations[key] = list(dict.fromkeys(citations[key]))
    
    return dict(citations)


def extract_legal_references(text: str) -> Dict[str, List[str]]:
    """
    Extract references to legal texts (Constitution, statutes, etc.)
    
    Returns:
        Dict with reference types
    """
    references = defaultdict(list)
    
    # Constitution articles: Article 14, Art. 21
    article_pattern = r'\b(?:Article|Art\.?)\s+\d+[A-Z]?(?:\(\d+\))?(?:\s+of\s+the\s+Constitution)?'
    for match in re.finditer(article_pattern, text, re.IGNORECASE):
        ref = match.group(0).strip()
        # Normalize format
        ref = re.sub(r'\bArt\.?\s+', 'Article ', ref, flags=re.I)
        references['Constitution'].append(ref)
    
    # Sections with act names: Section 138 of NI Act
    section_act_pattern = r'Section\s+\d+[A-Z]?(?:\s*\([a-z0-9]+\))?\s+(?:of\s+(?:the\s+)?)?([A-Z][A-Za-z\s,]+Act(?:\s*,?\s*\d{4})?)'
    for match in re.finditer(section_act_pattern, text):
        section = match.group(0).strip()
        act = match.group(1).strip()
        references['Sections'].append(section)
        references['Acts'].append(act)
    
    # Deduplicate
    for key in references:
        references[key] = list(dict.fromkeys(references[key]))
    
    return dict(references)


def structure_precedent(precedent_str: str) -> Optional[Dict[str, str]]:
    """
    Parse a precedent string into structured format.
    
    Example: "Ram v. Shyam (2023) 5 SCC 123" ->
    {
        "case_name": "Ram v. Shyam",
        "citation": "(2023) 5 SCC 123",
        "year": "2023"
    }
    """
    if not precedent_str:
        return None
    
    # Extract case name (before citation)
    case_pattern = r'^(.+?)\s*(?:\(\d{4}\)|\bAIR\b|\d{4}\s+SCC)'
    case_match = re.search(case_pattern, precedent_str)
    
    if not case_match:
        return {"case_name": precedent_str.strip(), "citation": "", "year": ""}
    
    case_name = case_match.group(1).strip()
    
    # Extract citation
    citation_patterns = [
        r'\(\d{4}\)\s*\d+\s*SCC\s*\d+',
        r'AIR\s+\d{4}\s+\w+\s+\d+',
        r'\d{4}\s+SCC\s+OnLine\s+\w+\s+\d+'
    ]
    
    citation = ""
    year = ""
    
    for pattern in citation_patterns:
        cit_match = re.search(pattern, precedent_str)
        if cit_match:
            citation = cit_match.group(0).strip()
            # Extract year
            year_match = re.search(r'\d{4}', citation)
            if year_match:
                year = year_match.group(0)
            break
    
    return {
        "case_name": case_name,
        "citation": citation,
        "year": year
    }


def categorize_precedents(precedents: List[str]) -> Dict[str, List[Dict]]:
    """
    Categorize precedents by court level.
    
    Returns:
        Dict with "supreme_court", "high_courts", "other"
    """
    categorized = {
        "supreme_court": [],
        "high_courts": [],
        "other": []
    }
    
    for prec in precedents:
        structured = structure_precedent(prec)
        if not structured:
            continue
        
        citation = structured.get("citation", "").lower()
        
        # Supreme Court indicators
        if any(marker in citation for marker in ['scc', 'scr', 'air.*sc', 'scc online sc']):
            categorized["supreme_court"].append(structured)
        # High Court indicators
        elif any(marker in citation for marker in ['air.*delhi', 'air.*bombay', 'air.*madras', 'air.*calcutta']):
            categorized["high_courts"].append(structured)
        else:
            categorized["other"].append(structured)
    
    return categorized


def extract_footnotes(text: str) -> List[Dict[str, str]]:
    """
    Extract footnote references and their content.
    
    Returns:
        List of dicts with footnote number and text
    """
    footnotes = []
    
    # Pattern: superscript number followed by content
    # Example: "¹ See Ram v. Shyam (2023) 5 SCC 123"
    footnote_pattern = r'[¹²³⁴⁵⁶⁷⁸⁹⁰]+\s*(.+?)(?=[¹²³⁴⁵⁶⁷⁸⁹⁰]|\n\n|\Z)'
    
    for i, match in enumerate(re.finditer(footnote_pattern, text, re.DOTALL), 1):
        content = match.group(1).strip()
        if len(content) > 10:  # Substantial footnote
            footnotes.append({
                "number": str(i),
                "content": content[:500]  # Limit length
            })
    
    return footnotes