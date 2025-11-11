# pipeline/content_extractor.py
"""
Extracts structured narrative content from judgment segments
"""

import re
from typing import List, Dict, Optional


def clean_text(text: str) -> str:
    """Clean and normalize text"""
    if not text:
        return ""
    
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove page numbers
    text = re.sub(r'\bPage\s+\d+\s+of\s+\d+\b', '', text, flags=re.I)
    
    # Remove multiple dots/dashes
    text = re.sub(r'\.{3,}', '...', text)
    text = re.sub(r'-{3,}', '---', text)
    
    return text.strip()


def extract_background_facts(body_text: str) -> List[str]:
    """
    Extract background facts from the body of judgment
    
    Returns:
        List of fact paragraphs
    """
    if not body_text:
        return []
    
    facts = []
    
    # Common section headers for facts
    fact_markers = [
        r'(?:Background|Facts?|Factual Background|Brief Facts?)',
        r'(?:Facts? of the Case|Facts? in Brief)',
        r'(?:Factual Matrix|Genesis of the Case)',
        r'(?:Brief History|History of the Case)',
    ]
    
    # Try to find facts section
    for marker in fact_markers:
        # Look for section starting with marker
        pattern = rf'(?i)(?:^|\n)\s*(?:{marker})[:\s\-]*\n?((?:.|\n)*?)(?=\n\s*(?:Issue|Argument|Submission|Contention|Analysis|Discussion|Held|ORDER|\Z))'
        match = re.search(pattern, body_text, re.IGNORECASE | re.MULTILINE)
        
        if match:
            facts_text = match.group(1).strip()
            if facts_text:
                # Split into paragraphs (by double newline or numbered points)
                paragraphs = re.split(r'\n\s*\n+|\n\s*\d+\.', facts_text)
                
                for para in paragraphs:
                    para = clean_text(para)
                    # Keep substantial paragraphs (at least 50 characters)
                    if len(para) >= 50 and not re.match(r'^[\d\.\s]+$', para):
                        facts.append(para)
                
                if facts:
                    return facts[:10]  # Limit to first 10 paragraphs
    
    # Fallback: Extract first few substantial paragraphs from body
    if not facts:
        # Get text from start until "Issue" or "Argument" section
        early_text = body_text[:3000]  # First ~3000 chars
        paragraphs = re.split(r'\n\s*\n+', early_text)
        
        for para in paragraphs[:5]:
            para = clean_text(para)
            # Skip headers and very short paragraphs
            if len(para) >= 100 and not re.match(r'^[A-Z\s]+$', para):
                facts.append(para)
        
        return facts[:5]  # Return max 5 paragraphs
    
    return facts


def extract_issues(body_text: str) -> List[str]:
    """
    Extract issues for consideration from the body
    
    Returns:
        List of issues
    """
    if not body_text:
        return []
    
    issues = []
    
    # Common issue markers
    issue_markers = [
        r'Issues? for (?:Consideration|Determination|Decision)',
        r'Questions? (?:of Law|for Consideration|Raised)',
        r'Points? for (?:Consideration|Determination)',
        r'Issues? Raised',
        r'Issues? Arising',
    ]
    
    for marker in issue_markers:
        # Look for issues section
        pattern = rf'(?i)(?:^|\n)\s*(?:{marker})[:\s\-]*\n?((?:.|\n)*?)(?=\n\s*(?:Argument|Submission|Discussion|Analysis|Background|Facts?|Held|ORDER|\Z))'
        match = re.search(pattern, body_text, re.IGNORECASE | re.MULTILINE)
        
        if match:
            issues_text = match.group(1).strip()
            
            # Extract numbered or lettered points
            # Pattern 1: "1.", "2.", etc.
            numbered = re.findall(r'(?:^|\n)\s*\d+\.\s*(.+?)(?=\n\s*\d+\.|\n\s*[A-Z][a-z]+:|\Z)', issues_text, re.DOTALL)
            
            if numbered:
                for issue in numbered:
                    issue = clean_text(issue)
                    if len(issue) >= 30:  # Substantial issue
                        issues.append(issue)
                return issues[:10]  # Max 10 issues
            
            # Pattern 2: "(i)", "(ii)", etc.
            roman = re.findall(r'(?:^|\n)\s*\([ivxIVX]+\)\s*(.+?)(?=\n\s*\([ivxIVX]+\)|\n\s*[A-Z][a-z]+:|\Z)', issues_text, re.DOTALL)
            
            if roman:
                for issue in roman:
                    issue = clean_text(issue)
                    if len(issue) >= 30:
                        issues.append(issue)
                return issues[:10]
            
            # Pattern 3: "Whether..." questions
            questions = re.findall(r'(?i)(?:^|\n)\s*(Whether\s+.+?)(?=\n\s*(?:Whether|\d+\.|\([ivxIVX]+\)|[A-Z][a-z]+:)|\Z)', issues_text, re.DOTALL)
            
            if questions:
                for q in questions:
                    q = clean_text(q)
                    if len(q) >= 30:
                        issues.append(q)
                return issues[:10]
            
            # Fallback: Split by newlines if structured list
            lines = [l.strip() for l in issues_text.split('\n') if l.strip()]
            for line in lines:
                line = clean_text(line)
                if len(line) >= 50 and not re.match(r'^[A-Z\s]+$', line):
                    issues.append(line)
            
            if issues:
                return issues[:10]
    
    # Fallback: Look for "Whether" questions anywhere in early body
    early_body = body_text[:2000]
    whether_questions = re.findall(
        r'(?i)(?:^|\n)\s*(Whether\s+.+?[.?])(?=\s*(?:\n|$))',
        early_body,
        re.MULTILINE
    )
    
    for q in whether_questions[:5]:
        q = clean_text(q)
        if len(q) >= 30:
            issues.append(q)
    
    return issues


def extract_order_summary(order_text: str) -> Dict[str, any]:
    """
    Extract structured information from the order/conclusion section
    
    Returns:
        Dictionary with decision, directions, and result
    """
    if not order_text:
        return {
            "decision": "",
            "directions": [],
            "result": "Not found",
            "full_text": ""
        }
    
    order_text = clean_text(order_text)
    
    # Extract decision (usually starts with "Held:")
    decision = ""
    held_match = re.search(r'(?i)Held\s*:\s*(.+?)(?=\n\s*(?:\d+\.|Therefore|Accordingly|In view|ORDER|Directions?:)|\Z)', order_text, re.DOTALL)
    if held_match:
        decision = clean_text(held_match.group(1))
    
    # If no "Held:", take first substantial paragraph
    if not decision:
        paragraphs = re.split(r'\n\s*\n+', order_text)
        for para in paragraphs[:3]:
            para = clean_text(para)
            if len(para) >= 100:
                decision = para
                break
    
    # Extract directions/orders
    directions = []
    
    # Look for numbered directions
    direction_patterns = [
        r'(?:^|\n)\s*\d+\.\s*(.+?)(?=\n\s*\d+\.|\Z)',
        r'(?:^|\n)\s*\([a-z]\)\s*(.+?)(?=\n\s*\([a-z]\)|\Z)',
        r'(?i)(?:^|\n)\s*(?:It is )?(?:ordered|directed|held)\s+that[:\s]*(.+?)(?=\n\s*(?:It is|ORDER|\Z))',
    ]
    
    for pattern in direction_patterns:
        matches = re.findall(pattern, order_text, re.DOTALL)
        if matches:
            for match in matches:
                direction = clean_text(match)
                if len(direction) >= 20:
                    directions.append(direction)
            if directions:
                break
    
    # Determine result
    result = "Not determined"
    
    result_patterns = [
        (r'(?i)\b(?:appeal|petition|application)\s+(?:is\s+)?(?:allowed|partly allowed|dismissed|disposed of)\b', 'extracted'),
        (r'(?i)\bappeal.*?allowed\b', 'Appeal Allowed'),
        (r'(?i)\bappeal.*?dismissed\b', 'Appeal Dismissed'),
        (r'(?i)\bappeal.*?partly allowed\b', 'Appeal Partly Allowed'),
        (r'(?i)\bpetition.*?allowed\b', 'Petition Allowed'),
        (r'(?i)\bpetition.*?dismissed\b', 'Petition Dismissed'),
        (r'(?i)\bdisposed of\b', 'Disposed Of'),
    ]
    
    for pattern, result_text in result_patterns:
        match = re.search(pattern, order_text)
        if match:
            if result_text == 'extracted':
                result = clean_text(match.group(0)).title()
            else:
                result = result_text
            break
    
    return {
        "decision": decision[:1000] if decision else "Not found",  # Limit length
        "directions": directions[:10],  # Max 10 directions
        "result": result,
        "full_text": order_text[:2000] if order_text else ""  # First 2000 chars
    }


def extract_conclusion(order_text: str) -> str:
    """
    Extract a brief conclusion statement
    
    Returns:
        Single string summarizing the conclusion
    """
    if not order_text:
        return "Conclusion not found"
    
    # Look for conclusion markers
    conclusion_patterns = [
        r'(?i)(?:In\s+)?(?:conclusion|result|view of the above)[:\s,]*(.+?)(?=\n\s*ORDER|\Z)',
        r'(?i)(?:Accordingly|Therefore|Thus|Hence)[,:\s]+(.+?)(?=\n|\Z)',
        r'(?i)(?:We|The Court)\s+(?:accordingly|therefore|thus)\s+(.+?)(?=\n|\Z)',
    ]
    
    for pattern in conclusion_patterns:
        match = re.search(pattern, order_text, re.DOTALL)
        if match:
            conclusion = clean_text(match.group(1))
            if len(conclusion) >= 30:
                return conclusion[:500]  # Max 500 chars
    
    # Fallback: last substantial paragraph
    paragraphs = re.split(r'\n\s*\n+', order_text)
    for para in reversed(paragraphs):
        para = clean_text(para)
        if len(para) >= 50:
            return para[:500]
    
    return "Conclusion not found"