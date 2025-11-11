# party_extractor.py - IMPROVED VERSION

import re
from typing import List, Tuple


def _clean_party_chunk(chunk: str) -> str:
    """Clean a party name chunk from noise, metadata, and trailing junk."""
    if not chunk:
        return ""
    
    # Remove common suffixes
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
    chunk = re.sub(r'\bCrl\.?O\.?P\.?\b.*$', '', chunk, flags=re.I)
    
    # Remove "Rep. by" and similar
    chunk = re.sub(r'\bRep(?:resented)?\.?\s+by\b.*$', '', chunk, flags=re.I)
    chunk = re.sub(r'\bThrough\b.*$', '', chunk, flags=re.I)
    
    # Remove trailing prepositions
    chunk = re.sub(r'\s+(?:in|of|the|at|to)\s*$', '', chunk, flags=re.I)
    
    # Clean whitespace
    chunk = re.sub(r'\s+', ' ', chunk).strip(' .,;:-')
    
    return chunk


def _extract_names_from_block(block: str) -> List[str]:
    """Extract individual names from a cleaned block."""
    if not block:
        return []
    
    # Split on delimiters
    parts = re.split(r'\s*(?:,|;|\band\b|\&)\s*', block, flags=re.I)
    
    names = []
    for part in parts:
        part = _clean_party_chunk(part)
        
        if part and len(part) >= 3:
            # Skip if doesn't start with capital
            if not re.match(r'^[A-Z]', part):
                continue
            
            # Skip if contains case number markers
            if re.search(r'\bNo\.?\s*\d+', part, re.I):
                continue
            
            names.append(part)
    
    # Deduplicate
    seen = set()
    unique = []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            unique.append(n)
    
    return unique


def extract_parties(header_text: str, entities: dict) -> Tuple[List[str], List[str]]:
    """
    Multi-strategy party extraction with VERSUS pattern support.
    
    Returns:
        Tuple of (appellants_list, respondents_list)
    """
    if not header_text:
        return [], []
    
    appellants, respondents = [], []
    
    # === STRATEGY 1: VERSUS Pattern (for formats like Sample 4) ===
    # Look for "NAME(S)\nVERSUS\nNAME(S)" pattern
    versus_pattern = re.compile(
        r'^([A-Z][A-Z\s\.,&]+?)\s*\n\s*(?:VERSUS|V[Ss]?\.?)\s*\n\s*([A-Z][A-Z\s\.,&]+?)(?:\n|$)',
        re.MULTILINE | re.IGNORECASE
    )
    
    versus_match = versus_pattern.search(header_text)
    if versus_match:
        app_block = versus_match.group(1).strip()
        resp_block = versus_match.group(2).strip()
        
        appellants = _extract_names_from_block(app_block)
        respondents = _extract_names_from_block(resp_block)
        
        if appellants and respondents:
            return appellants, respondents
    
    # === STRATEGY 2: Inline versus pattern (e.g., "Name v. Name") ===
    inline_versus = re.compile(
        r'([A-Z][A-Za-z\s\.,&]{3,60}?)\s+v\.?s?\.?\s+([A-Z][A-Za-z\s\.,&]{3,60}?)(?=\s*(?:Petitioner|Respondent|Appellant|\(|IN THE|CORAM|Date|$))',
        re.IGNORECASE
    )
    
    inline_match = inline_versus.search(header_text)
    if inline_match and not appellants:
        left = _clean_party_chunk(inline_match.group(1).strip())
        right = _clean_party_chunk(inline_match.group(2).strip())
        
        if left and right and len(left) >= 3 and len(right) >= 3:
            appellants = [left]
            respondents = [right]
            return appellants, respondents
    
    # === STRATEGY 3: Labeled Header Lines ===
    app_match = re.search(
        r'^\s*(?:Petitioner|Appellant)(?:\(s\))?\s*[:\-]\s*(.+?)$',
        header_text,
        re.IGNORECASE | re.MULTILINE
    )
    
    resp_match = re.search(
        r'^\s*Respondent(?:\(s\))?\s*[:\-]\s*(.+?)$',
        header_text,
        re.IGNORECASE | re.MULTILINE
    )
    
    if app_match:
        block = app_match.group(1).strip()
        appellants = _extract_names_from_block(block)
    
    if resp_match:
        block = resp_match.group(1).strip()
        respondents = _extract_names_from_block(block)
    
    # === STRATEGY 4: Multi-line Blocks After Label ===
    if not appellants:
        app_block_match = re.search(
            r'(?:Petitioner|Appellant)(?:\(s\))?\s*[:\-]\s*'
            r'((?:.|\n)*?)'
            r'(?=\n\s*(?:Respondent|v\.|CORAM|Date|Advocate|$))',
            header_text,
            re.IGNORECASE
        )
        if app_block_match:
            block = app_block_match.group(1).strip()
            appellants = _extract_names_from_block(block)
    
    if not respondents:
        resp_block_match = re.search(
            r'Respondent(?:\(s\))?\s*[:\-]\s*'
            r'((?:.|\n)*?)'
            r'(?=\n\s*(?:CORAM|Date|Advocate|Appearances|$))',
            header_text,
            re.IGNORECASE
        )
        if resp_block_match:
            block = resp_block_match.group(1).strip()
            respondents = _extract_names_from_block(block)
    
    return appellants[:5], respondents[:3]