# pipeline/custom_patterns.py
#
# High-priority, header-aware rules for Indian judgments.
# These rules will always be applied BEFORE the 25k base rules.
# Keep this file small (20–100 lines max).
# Add new rules ONLY when you see repeated extraction errors.

PATTERNS = [

    # -----------------------------
    # Case Numbers
    # -----------------------------
    {"label": "CASE_NUMBER", "pattern": {"regex": "(?i)\\b(?:W\\.P\\.|Crl\\.A\\.|SLP|C\\.A\\.|I\\.A\\.|Appeal|O\\.S\\.|RCC|Complaint)\\s*No\\.?\\s*\\d+(?:/\\d{4}|\\s+of\\s+\\d{4})?\\b"}},

    {"label": "CASE_NUMBER", "pattern": {"regex": "(?i)\\b(?:Criminal|Civil)\\s+(?:Appeal|Application)\\s+No\\.?\\s*\\d+(?:/\\d{4})?\\b"}},

    # -----------------------------
    # Courts
    # -----------------------------
    {"label": "COURT", "pattern": {"regex": "(?i)\\bSupreme Court of India\\b"}},
    {"label": "COURT", "pattern": {"regex": "(?i)\\bHigh Court of [A-Za-z ]+\\b"}},

    # -----------------------------
    # Dates
    # -----------------------------
    {"label": "DATE", "pattern": {"regex": "(?i)\\b\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}\\b"}},         # 12-01-2025 or 12/01/2025
    {"label": "DATE", "pattern": {"regex": "(?i)\\b\\d{1,2}\\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\s+\\d{4}\\b"}},  # 12 Jan 2025

    # -----------------------------
    # Judges
    # -----------------------------
    {"label": "JUDGE", "pattern": {"regex": "(?i)^\\s*Coram[:].+$"}},
    {"label": "JUDGE", "pattern": {"regex": "(?i)^\\s*Before\\s+Hon'?ble.*$"}},
    {"label": "JUDGE", "pattern": {"regex": "(?i)Hon'?ble\\s+Mr\\.?\\s+Justice\\s+[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*"}},
    {"label": "JUDGE", "pattern": {"regex": "(?i)Hon'?ble\\s+Ms\\.?\\s+Justice\\s+[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*"}},
    {"label": "JUDGE", "pattern": {"regex": "(?i)Justice\\s+[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*"}},

    # -----------------------------
    # Petitioners
    # -----------------------------
    {"label": "PETITIONER", "pattern": {"regex": "(?i)^\\s*Petitioner[s]?:\\s+.+$"}},
    {"label": "PETITIONER", "pattern": {"regex": "(?i)Appellant[s]?:\\s+.+$"}},

    # -----------------------------
    # Respondents
    # -----------------------------
    {"label": "RESPONDENT", "pattern": {"regex": "(?i)^\\s*Respondent[s]?:\\s+.+$"}},
    {"label": "RESPONDENT", "pattern": {"regex": "(?i)Defendant[s]?:\\s+.+$"}},

    # -----------------------------
    # Lawyers
    # -----------------------------
    {"label": "LAWYER", "pattern": {"regex": "(?i)^\\s*For\\s+Petitioner[s]?:\\s+.+$"}},
    {"label": "LAWYER", "pattern": {"regex": "(?i)^\\s*For\\s+Respondent[s]?:\\s+.+$"}},
    {"label": "LAWYER", "pattern": {"regex": "(?i)Advocate[s]?:\\s+.+$"}},

    # -----------------------------
    # Extras
    # -----------------------------
    {"label": "PETITIONER", "pattern": {"regex": "(?i)Appellant[s]?:\\s+.+$"}},
    {"label": "RESPONDENT", "pattern": {"regex": "(?i)Opposite Party[s]?:\\s+.+$"}}
]
