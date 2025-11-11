import re
from typing import List


def clean_judge_name(name: str) -> str:
    """
    Clean a single judge name by removing honorifics, suffixes, and extra punctuation.
    """
    if not name:
        return ""

    # Remove honorifics and titles
    name = re.sub(
        r"\b(Hon'?ble|Honorable|Justice|Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Shri|Smt\.?|Lordship|His Lordship|Her Ladyship)\b",
        "",
        name,
        flags=re.I,
    )

    # Remove trailing J., JJ., etc.
    name = re.sub(r"\bJ{1,2}\.?$", "", name.strip(), flags=re.I)

    # Normalize whitespace
    name = re.sub(r"\s+", " ", name).strip()

    return name


def extract_coram(header: str) -> List[str]:
    """
    Extract judge names from the header using multiple strategies.
    """
    judges = []

    if not header:
        return judges

    # --- 1. Primary Clue: Text inside square brackets
    bracket_match = re.findall(r"\[(.*?)\]", header, flags=re.S)
    if bracket_match:
        for block in bracket_match:
            parts = re.split(r",| and ", block)
            for part in parts:
                name = clean_judge_name(part)
                if name:
                    judges.append(name)

    # --- 2. Secondary Clue: Look for explicit "Coram" or "Bench" lines
    if not judges:
        for line in header.splitlines():
            if re.search(r"\b(Coram|Bench)\b", line, flags=re.I):
                parts = re.split(r",| and ", line)
                for part in parts:
                    name = clean_judge_name(part)
                    if name:
                        judges.append(name)

    # --- 3. Tertiary Clue: Look for lines starting with Hon'ble Justice
    if not judges:
        for line in header.splitlines():
            if re.match(r"^\s*Hon'?ble\s+Justice", line, flags=re.I):
                parts = re.split(r",| and ", line)
                for part in parts:
                    name = clean_judge_name(part)
                    if name:
                        judges.append(name)

    # Deduplicate while preserving order
    seen, final = set(), []
    for j in judges:
        if j.lower() not in seen:
            seen.add(j.lower())
            final.append(j)

    return final
