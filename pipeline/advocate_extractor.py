import re
from typing import Dict, List

def clean_advocate_name(name: str) -> str:
    """
    Cleans advocate name strings by removing role markers and normalizing spacing.
    Keeps honorifics like Dr., Mr., Ms., etc.
    """
    if not name:
        return ""

    # Remove leading slashes and colons (from "/State :" type patterns)
    name = re.sub(r"^[/:\-\s]+", "", name)
    
    # Remove "for Applicants/Respondents/State" prefixes first
    name = re.sub(r"^(?:for\s+(?:Applicants?|Respondents?|State|the\s+(?:Appellant|Respondent|Petitioner)))\s*[:\-]?\s*", "", name, flags=re.I)
    
    # Remove "/State" or "State" prefixes that might remain
    name = re.sub(r"^(?:/\s*)?State\s*[:\-]?\s*", "", name, flags=re.I)
    
    # Remove inline role markers like "Sr. Advs." but NOT if it's part of a name
    # Only remove if followed by comma or at end
    name = re.sub(r",?\s*\bSr\.?\s*Advs?\.?(?=\s*[,;.]|$)", "", name, flags=re.I)
    name = re.sub(r",?\s*\bA\.S\.G\.?(?=\s*[,;.]|$)", "", name, flags=re.I)
    name = re.sub(r",?\s*\bA\.A\.G\.?(?=\s*[,;.]|$)", "", name, flags=re.I)
    
    # Remove other role markers but keep titles
    roles_to_remove = (
        r"\b(Adv\.?(?!\s+[A-Z])|Advs\.?(?!\s+[A-Z])|Advocate"
        r"|Senior Advocate|learned counsel|learned senior counsel"
        r"|AOR|GA|AGA|SG|Counsel|Solicitor General|amicus curiae)\b"
    )
    name = re.sub(roles_to_remove, "", name, flags=re.I)

    # Remove trailing role markers in parentheses
    name = re.sub(r"\s*\(.*?\)$", "", name)
    
    # Remove phrases like "appearing for", "represented by"
    name = re.sub(r"\b(appearing\s+for|represented\s+by|for\s+the)\b.*$", "", name, flags=re.I)

    # Strip leading/trailing junk
    name = name.strip(" .,;:\n\t-")

    # Normalize internal whitespace (but preserve structure)
    name = re.sub(r'\s+', ' ', name).strip()

    # Remove standalone "APP" if it appears
    if name.upper() == "APP":
        return ""

    # Discard if too short
    if len(name) < 3:
        return ""
    
    # Must contain at least one letter to be valid
    if not re.search(r'[A-Za-z]', name):
        return ""

    return name


def split_names(block: str) -> List[str]:
    """Split a block of text into individual advocate names."""
    if not block:
        return []

    # Remove header markers more aggressively
    block = re.sub(
        r"^(Advs?\.?\s*for\s*(the\s*)?(Appellant|Respondent|Petitioner|Applicants?|State)"
        r"|Advocate\s*for\s*(Appellant|Respondent|Applicants?|State)"
        r"|Counsel\s*for\s*(Appellant|Respondent|State)"
        r"|APP\s*for\s*(Respondent(?:s)?(?:/State)?|State)"
        r"|By\s+Adv.*?|Represented\s+by"
        r")\s*[:\-]?\s*",
        "",
        block,
        flags=re.I | re.M,
    )

    # Remove role designations that appear inline
    block = re.sub(r",\s*Sr\.?\s*Advs?\.?\s*,", ",", block, flags=re.I)
    block = re.sub(r",\s*A\.S\.G\.?\s*,", ",", block, flags=re.I)
    block = re.sub(r",\s*A\.A\.G\.?\s*,", ",", block, flags=re.I)
    
    # First pass: split on commas and semicolons
    parts = re.split(r'\s*[,;]\s*', block)
    
    # Process parts to handle "and" separately and merge multi-part names
    processed_parts = []
    for part in parts:
        # Split on "and" but keep the parts separate
        and_parts = re.split(r'\s+and\s+', part, flags=re.I)
        processed_parts.extend(and_parts)
    
    # Also try to split on colons in case of "Respondent/State : Name" patterns
    final_parts = []
    for part in processed_parts:
        # If there's a colon, take everything after it if it looks like a name
        if ':' in part:
            colon_parts = part.split(':', 1)
            # Check if the part after colon looks like a name
            after_colon = colon_parts[1].strip()
            if after_colon and (re.match(r'^(?:Dr|Mr|Ms|Mrs|Shri|Smt)\.?\s+', after_colon, re.I) or 
                               re.match(r'^[A-Z]', after_colon)):
                final_parts.append(after_colon)
            else:
                final_parts.extend(colon_parts)
        else:
            final_parts.append(part)
    
    cleaned = []
    junk_phrases = {
        "advs for the appellant", "advs for the respondent",
        "appearances for parties", "advocate for applicants",
        "app for respondents", "for applicants", "for respondents",
        "for state", "sr. advs", "sr. adv", "a.s.g", "asg", "a.a.g", "aag",
        "state", "respondent", "appellant",
    }
    
    for part in final_parts:
        part = part.strip()
        
        # Skip empty or junk
        if not part or part.lower() in junk_phrases:
            continue
        
        # Skip if it's just a role marker
        if re.match(r'^(Sr\.?\s*Advs?\.?|A\.S\.G\.?|A\.A\.G\.?)$', part, re.I):
            continue
        
        cleaned_name = clean_advocate_name(part)
        
        if cleaned_name and len(cleaned_name) >= 3:
            # Check if it looks like a valid name
            # Valid names should have at least 2 characters or start with title
            if (re.match(r'^(?:Dr|Mr|Ms|Mrs|Shri|Smt)\.?\s+', cleaned_name, re.I) or 
                len(cleaned_name.split()) >= 2 or
                re.match(r'^[A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z]+)+$', cleaned_name)):
                
                cleaned.append(cleaned_name)

    # Deduplicate while preserving order
    seen, result = set(), []
    for x in cleaned:
        k = x.lower().strip()
        if k not in seen and len(k) > 2:
            seen.add(k)
            result.append(x)
    
    return result


def _extract_from_prose(text: str) -> Dict[str, List[str]]:
    """
    Extract advocate names from prose/body text using multiple patterns.
    """
    advocates = {"for_appellants": [], "for_respondent": []}
    
    # Pattern 1: "represented by learned senior counsel Mr. Name"
    pattern1 = r"represented\s+by\s+(?:learned\s+)?(?:senior\s+)?counsel\s+(?P<n>(?:Dr|Mr|Ms|Mrs|Shri|Smt)\.?\s+[A-Z][a-zA-Z\.\s]+?)(?=,|\s+filed|\s+and|\.|$)"
    
    # Pattern 2: "Solicitor General, Mr. Name, appearing for"
    pattern2 = r"(?:Solicitor\s+General|Attorney\s+General|Additional\s+Solicitor\s+General),\s*(?P<n>(?:Dr|Mr|Ms|Mrs|Shri|Smt)\.?\s+[A-Z][a-zA-Z\.\s]+?),\s+appearing\s+for"
    
    # Pattern 3: "amicus curiae Ms. Name"
    pattern3 = r"amicus\s+curiae\s+(?P<n>(?:Dr|Mr|Ms|Mrs|Shri|Smt)\.?\s+[A-Z][a-zA-Z\.\s]+?)(?=,|\s+who|\s+argued|$)"
    
    # Pattern 4: Ministry counsel pattern "appearing for the Ministry of X"
    pattern4 = r"(?P<n>(?:Dr|Mr|Ms|Mrs|Shri|Smt)\.?\s+[A-Z][a-zA-Z\.\s]+?),\s+appearing\s+for\s+(?:the\s+)?(?:Ministry|Union|State)"

    found_appellant = []
    found_respondent = []
    
    # Extract appellant advocates (represented by)
    for match in re.finditer(pattern1, text, re.IGNORECASE):
        name = clean_advocate_name(match.group("n"))
        if name and len(name) > 4:
            # Remove trailing verbs/prepositions
            name = re.sub(r"\s+(has|was|is|argued|submitted|filed).*$", "", name, flags=re.I).strip()
            if name:
                found_appellant.append(name)
    
    # Extract respondent advocates (Solicitor General, appearing for Ministry)
    for match in re.finditer(pattern2, text, re.IGNORECASE):
        name = clean_advocate_name(match.group("n"))
        if name and len(name) > 4:
            found_respondent.append(name)
    
    for match in re.finditer(pattern4, text, re.IGNORECASE):
        name = clean_advocate_name(match.group("n"))
        if name and len(name) > 4:
            found_respondent.append(name)
    
    # Amicus curiae - add to appellants if nothing else found
    for match in re.finditer(pattern3, text, re.IGNORECASE):
        name = clean_advocate_name(match.group("n"))
        if name and len(name) > 4:
            name = re.sub(r"\s+who.*$", "", name, flags=re.I).strip()
            if name and not found_appellant:
                found_appellant.append(name)
    
    advocates["for_appellants"] = list(dict.fromkeys(found_appellant))
    advocates["for_respondent"] = list(dict.fromkeys(found_respondent))

    return advocates


def extract_advocates(text: str) -> Dict[str, List[str]]:
    """
    Extract advocates grouped by party side with support for multiple formats.
    """
    advocates = {"for_appellants": [], "for_respondent": []}
    if not text:
        return advocates

    # === STRATEGY 1: Block-based markers (Supreme Court & High Court format) ===
    app_markers = [
        r"Advs?\.?\s*for\s*the\s*Appellant(?:s)?",
        r"For\s*Petitioner(?:s)?",
        r"Counsel\s*for\s*Appellant(?:s)?",
        r"Advocate\s*for\s*Applicant(?:s)?",
    ]
    resp_markers = [
        r"Advs?\.?\s*for\s*the\s*Respondent(?:s)?",
        r"For\s*Respondent(?:s)?",
        r"Counsel\s*for\s*Respondent(?:s)?",
        r"APP\s*for\s*Respondent(?:s)?(?:/State)?",
        r"APP\s*for\s*State",
    ]

    def capture_block(markers: List[str], opposite_markers: List[str]) -> str:
        # Capture full advocate blocks including multi-line names
        all_stop_markers = opposite_markers + ["JUDGMENT", "ORDER", "Date", "PER COURT", "Bench"]
        
        for m in markers:
            # Try multi-line capture that stops at the next section
            pattern = rf"{m}\s*[:\-]?\s*((?:.|\n)+?)(?=(?:{'|'.join(all_stop_markers)})|$)"
            match = re.search(pattern, text, re.IGNORECASE)
            
            if match:
                captured = match.group(1).strip()
                
                # Limit to first few lines (usually advocates are listed in 2-5 lines)
                lines = captured.split('\n')
                relevant_lines = []
                for line in lines[:10]:  # Max 10 lines
                    line = line.strip()
                    if not line:
                        continue
                    # Stop if we hit a section marker
                    if re.match(r'^(JUDGMENT|ORDER|PER COURT|Bench|Date\s*:|CORAM)', line, re.I):
                        break
                    relevant_lines.append(line)
                
                if relevant_lines:
                    # Join lines with comma to preserve proper splitting
                    captured = ', '.join(relevant_lines)
                    return captured
        return ""

    app_block = capture_block(app_markers, resp_markers)
    resp_block = capture_block(resp_markers, app_markers)

    if app_block:
        advocates["for_appellants"] = split_names(app_block)
    if resp_block:
        advocates["for_respondent"] = split_names(resp_block)

    # === STRATEGY 2: Direct line-based extraction (failsafe for simple formats) ===
    if not advocates["for_appellants"]:
        # Try: "Advocate for Applicants : Name"
        app_line = re.search(r"Advocate\s*for\s*Applicants?\s*[:\-]\s*([^\n\r]+)", text, re.I)
        if app_line:
            advocates["for_appellants"] = split_names(app_line.group(1))
    
    if not advocates["for_respondent"]:
        # Try: "APP for Respondents/State : Name"
        resp_line = re.search(r"APP\s*for\s*(?:Respondents?(?:/State)?|State)\s*[:\-]\s*([^\n\r]+)", text, re.I)
        if resp_line:
            advocates["for_respondent"] = split_names(resp_line.group(1))
    
    # === STRATEGY 3: Prose-based extraction for scattered mentions ===
    if not advocates["for_appellants"] or not advocates["for_respondent"]:
        prose_results = _extract_from_prose(text)
        
        if not advocates["for_appellants"]:
            advocates["for_appellants"] = prose_results["for_appellants"]
        if not advocates["for_respondent"]:
            advocates["for_respondent"] = prose_results["for_respondent"]

    # Final cleanup: remove empty strings and deduplicate
    advocates["for_appellants"] = [a for a in advocates["for_appellants"] if a and len(a) > 2]
    advocates["for_respondent"] = [a for a in advocates["for_respondent"] if a and len(a) > 2]
    
    advocates["for_appellants"] = list(dict.fromkeys(advocates["for_appellants"]))
    advocates["for_respondent"] = list(dict.fromkeys(advocates["for_respondent"]))

    return advocates