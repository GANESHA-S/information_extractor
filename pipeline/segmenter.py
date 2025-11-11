# segmenter.py
# Splits judgment text into header, body and order segments.
# Designed to accept plain text (not a PDF path) so PDF parsing happens only once.

import re
from typing import Dict


class Segmenter:
    """
    Usage:
        seg = Segmenter(text)
        segments = seg.split_segments()  # returns dict with 'header','body','order'
    """

    def __init__(self, source: str):
        """
        `source` should be the full text extracted from the PDF (string).
        """
        if source is None:
            source = ""
        self.text = source

    def _is_header_line(self, line: str) -> bool:
        """
        Heuristic to detect header lines: case captions, court names, case numbers, bench, date.
        """
        line = line.strip()
        if not line:
            return False
        # long uppercase lines often belong to header but exclude lines that look like long sentences
        if re.match(r'^[A-Z0-9 \.\-\(\)\,\:\[\]]{5,200}$', line) and len(line.split()) <= 12:
            return True
        # obvious header markers
        header_markers = [
            "IN THE SUPREME COURT", "CIVIL APPELLATE", "CRIMINAL APPELLATE",
            "IN THE HIGH COURT", "BENCH", "JUDGMENT", "CORAM", "CASE",
            "Crl.O.P", "CRLMC", "CRIMINAL APPLICATION", "CIVIL APPEAL",
            "Appearances for Parties", "Appearances", "Date of Judgment"
        ]
        for m in header_markers:
            if m.lower() in line.lower():
                return True
        # common caption pattern: "X v. Y" or "v." on its own line
        if re.search(r'\b v\.|\bv\s+v\b| v\.? $', line, re.I) or re.search(r'\b v\. \b', line):
            return True
        # case number shortforms
        if re.search(r'\b(No\.|CRL|Crl\.O\.P|Crime No|C\.A\.|C\.C\.)\b', line, re.I):
            return True
        return False

    def _looks_like_order_start(self, line: str) -> bool:
        """
        Detect start of final operative order section.
        """
        order_markers = [
            r'^\s*O R D E R\b', r'^\s*ORDER\b', r'^\s*Held:', r'^\s*DISPOSED\b',
            r'^\s*CONCLUSION\b', r'^\s*JUDGMENT\b', r'^\s*TAKE NOTICE\b'
        ]
        for pat in order_markers:
            if re.search(pat, line, re.I):
                return True
        return False

    def split_segments(self) -> Dict[str, str]:
        """
        Returns a dict: {"header": str, "body": str, "order": str}
        - header: document title, bench, case number, appearances, short preamble
        - body: opinion / reasoning
        - order: operative conclusion / order text
        """
        lines = self.text.splitlines()
        header_lines = []
        body_lines = []
        order_lines = []

        # We'll use a simple state machine:
        # state 'header' until we detect 'body' marker (Issue/Background/Heard)
        # state 'body' until we detect 'order' marker.
        state = "header"
        body_started_at = None

        for i, raw in enumerate(lines):
            line = raw.rstrip('\n')
            stripped = line.strip()
            if not stripped:
                # preserve single blank lines in body/order for readability
                if state == "body" and body_lines and body_lines[-1] != "":
                    body_lines.append("")
                continue

            # If we already think this is the order, dump everything there
            if self._looks_like_order_start(stripped):
                state = "order"

            # Detect transition from header -> body using heuristics
            if state == "header":
                # If we encounter words that typically start reasoning
                if re.search(r'^\s*(Issue for Consideration|Issue|Background|Facts|Background and Facts|From the Judgment|Judgment|Heard)', stripped, re.I):
                    state = "body"
                    body_started_at = i
                    body_lines.append(stripped)
                    continue
                # If header is getting long, and we see a paragraph like sentence, switch to body
                if len(header_lines) > 50:
                    state = "body"
                    body_started_at = i
                    body_lines.append(stripped)
                    continue
                # If a line doesn't look like header and contains verbs (thus likely prose), treat as body
                if not self._is_header_line(stripped) and re.search(r'\b(is|are|was|were|held|observed|submitted|submitted that|observed that)\b', stripped, re.I):
                    state = "body"
                    body_started_at = i
                    body_lines.append(stripped)
                    continue

            # Append line to appropriate buffer
            if state == "header":
                header_lines.append(stripped)
            elif state == "body":
                body_lines.append(stripped)
            else:
                order_lines.append(stripped)

        # Post-cleaning: trim leading/trailing blank lines
        header = "\n".join(h for h in header_lines).strip()
        body = "\n".join(b for b in body_lines).strip()
        order = "\n".join(o for o in order_lines).strip()

        # If 'order' is empty but body contains clear 'Held:' or 'Order' near end, split heuristically
        if not order and body:
            # look for 'Held:' or 'Order' inside body and split there
            m = re.search(r'(?:\n|^)(Held:|ORDER|O R D E R:|ORDER:)(.*)$', body, re.I | re.S)
            if m:
                before = body[:m.start()].strip()
                after = body[m.start():].strip()
                body = before
                order = after

        return {"header": header, "body": body, "order": order}
