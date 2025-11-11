# pipeline/validators.py
from typing import Dict, List, Any, Optional
from datetime import datetime
import re


class ExtractionValidator:
    """Validates extracted legal document data and generates quality reports."""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info_messages = []
        
    def reset(self):
        """Reset validation state."""
        self.errors = []
        self.warnings = []
        self.info_messages = []
    
    def validate_case_name(self, data: Dict) -> None:
        """Validate case name."""
        case_name = data.get("case_name")
        
        if not case_name:
            self.errors.append("Case name is missing")
        elif len(str(case_name)) < 5:
            self.warnings.append("Case name appears too short")
        elif len(str(case_name)) > 500:
            self.warnings.append("Case name appears unusually long")
        
        # Check for common patterns
        if case_name and not any(word in str(case_name).lower() 
                                  for word in ['vs', 'v.', 'versus', 'and']):
            self.warnings.append("Case name may be malformed (missing 'vs' or 'v.')")
    
    def validate_appeal_number(self, data: Dict) -> None:
        """Validate appeal/case number."""
        appeal_num = data.get("appeal_number")
        
        if not appeal_num:
            self.warnings.append("Appeal number not found")
            return
        
        appeal_str = str(appeal_num)
        
        # Check for year pattern
        if not re.search(r'(19|20)\d{2}', appeal_str):
            self.warnings.append("Appeal number missing year component")
        
        # Check for number pattern
        if not re.search(r'\d+', appeal_str):
            self.errors.append("Appeal number missing numeric component")
        
        if len(appeal_str) > 100:
            self.warnings.append("Appeal number appears unusually long")
    
    def validate_court(self, data: Dict) -> None:
        """Validate court name."""
        court = data.get("court")
        
        if not court:
            self.errors.append("Court name is missing - critical field")
        elif len(str(court)) < 5:
            self.warnings.append("Court name appears too short")
        
        # Check for valid court indicators
        if court:
            court_lower = str(court).lower()
            valid_indicators = [
                'supreme court', 'high court', 'district', 'tribunal', 
                'court', 'commission', 'authority'
            ]
            if not any(indicator in court_lower for indicator in valid_indicators):
                self.warnings.append("Court name may not be a valid court entity")
    
    def validate_date(self, data: Dict) -> None:
        """Validate judgment date."""
        date_str = data.get("date_of_judgment")
        
        if not date_str:
            self.warnings.append("Judgment date not found")
            return
        
        # Check date format patterns
        date_patterns = [
            r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',  # DD-MM-YYYY or MM-DD-YYYY
            r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',     # YYYY-MM-DD
            r'\d{1,2}\s+\w+\s+\d{4}',            # DD Month YYYY
            r'\w+\s+\d{1,2},?\s+\d{4}'           # Month DD, YYYY
        ]
        
        if not any(re.search(pattern, str(date_str)) for pattern in date_patterns):
            self.warnings.append("Date format appears non-standard")
        
        # Check for future dates or very old dates
        current_year = datetime.now().year
        year_match = re.search(r'(19|20)(\d{2})', str(date_str))
        if year_match:
            year = int(year_match.group(0))
            if year > current_year:
                self.errors.append(f"Judgment date is in the future: {year}")
            elif year < 1947:  # Before Indian independence
                self.warnings.append(f"Judgment date is very old: {year}")
    
    def validate_coram(self, data: Dict) -> None:
        """Validate judges/coram."""
        coram = data.get("coram")
        
        if not coram:
            self.warnings.append("Coram (judges) not found")
            return
        
        if isinstance(coram, list):
            if len(coram) == 0:
                self.warnings.append("Coram list is empty")
            elif len(coram) > 11:  # Constitutional benches are typically max 11
                self.warnings.append(f"Unusually large bench: {len(coram)} judges")
            
            # Check for valid judge name patterns
            for judge in coram:
                judge_str = str(judge)
                if len(judge_str) < 3:
                    self.warnings.append(f"Invalid judge name: '{judge_str}'")
                elif not re.search(r'[A-Z]', judge_str):
                    self.warnings.append(f"Judge name lacks capitalization: '{judge_str}'")
    
    def validate_parties(self, data: Dict) -> None:
        """Validate appellants and respondents."""
        appellants = data.get("appellants")
        respondent = data.get("respondent")
        
        if not appellants:
            self.warnings.append("Appellants not found")
        elif isinstance(appellants, list):
            if len(appellants) == 0:
                self.errors.append("Appellants list is empty")
            elif len(appellants) > 50:
                self.warnings.append(f"Unusually high appellant count: {len(appellants)}")
            
            # Check for duplicates
            if len(appellants) != len(set(str(a).lower() for a in appellants)):
                self.warnings.append("Duplicate appellants detected")
        
        if not respondent:
            self.warnings.append("Respondent not found")
    
    def validate_advocates(self, data: Dict) -> None:
        """Validate advocate information."""
        advocates = data.get("advocates")
        
        if not advocates:
            self.info_messages.append("Advocate information not extracted")
            return
        
        if isinstance(advocates, dict):
            for_appellants = advocates.get("for_appellants", [])
            for_respondent = advocates.get("for_respondent", [])
            
            if not for_appellants and not for_respondent:
                self.warnings.append("No advocates listed for either party")
            
            if len(for_appellants) > 20:
                self.warnings.append(f"Unusually many advocates for appellants: {len(for_appellants)}")
            
            if len(for_respondent) > 20:
                self.warnings.append(f"Unusually many advocates for respondent: {len(for_respondent)}")
    
    def validate_legal_references(self, data: Dict) -> None:
        """Validate precedents, provisions, and statutes."""
        # Precedents
        precedents = data.get("precedents")
        if precedents:
            if isinstance(precedents, dict):
                total_precedents = sum(
                    len(v) if isinstance(v, list) else 1 
                    for v in precedents.values()
                )
            elif isinstance(precedents, list):
                total_precedents = len(precedents)
            else:
                total_precedents = 1
            
            if total_precedents > 100:
                self.warnings.append(
                    f"Very high precedent count ({total_precedents}) - possible over-extraction"
                )
            elif total_precedents == 0:
                self.info_messages.append("No precedents extracted")
        
        # Provisions
        provisions = data.get("provisions")
        if provisions and isinstance(provisions, list):
            if len(provisions) > 50:
                self.warnings.append(f"Very high provision count: {len(provisions)}")
            
            # Check for malformed provisions
            for prov in provisions[:10]:  # Sample first 10
                prov_str = str(prov)
                if len(prov_str) < 3:
                    self.warnings.append(f"Malformed provision: '{prov_str}'")
        
        # Statutes
        statutes = data.get("statutes")
        if statutes and isinstance(statutes, list):
            if len(statutes) > 30:
                self.warnings.append(f"High statute count: {len(statutes)}")
    
    def validate_citations(self, data: Dict) -> None:
        """Validate legal citations."""
        citations = data.get("citations")
        
        if not citations:
            self.info_messages.append("No citations extracted")
            return
        
        if isinstance(citations, dict):
            total_citations = sum(
                len(v) if isinstance(v, list) else 1 
                for v in citations.values()
            )
            
            if total_citations > 50:
                self.warnings.append(f"Very high citation count: {total_citations}")
    
    def validate_content(self, data: Dict) -> None:
        """Validate content information."""
        content = data.get("content_info")
        
        if not content:
            self.info_messages.append("No content information extracted")
            return
        
        if isinstance(content, dict):
            # Validate issues
            issues = content.get("issues")
            if issues and isinstance(issues, list):
                if len(issues) > 20:
                    self.warnings.append(f"Unusually high issue count: {len(issues)}")
                
                for issue in issues[:5]:  # Sample first 5
                    if len(str(issue)) < 10:
                        self.warnings.append("Some issues appear too short")
                        break
            
            # Validate background facts
            bg_facts = content.get("background_facts")
            if bg_facts and isinstance(bg_facts, list):
                if len(bg_facts) > 30:
                    self.warnings.append(f"Very high background fact count: {len(bg_facts)}")
            
            # Validate order summary
            order = content.get("order_summary")
            if order and isinstance(order, dict):
                if not order.get("result") and not order.get("decision"):
                    self.warnings.append("Order summary lacks result or decision")
    
    def calculate_completeness(self, data: Dict) -> Dict[str, Any]:
        """Calculate completeness score based on extracted fields."""
        # Critical fields (must have)
        critical_fields = [
            "case_name", "court", "date_of_judgment"
        ]
        
        # Important fields (should have)
        important_fields = [
            "appeal_number", "coram", "appellants", "respondent"
        ]
        
        # Optional fields (nice to have)
        optional_fields = [
            "advocates", "precedents", "provisions", "statutes", 
            "citations", "content_info"
        ]
        
        critical_present = sum(1 for f in critical_fields if data.get(f))
        important_present = sum(1 for f in important_fields if data.get(f))
        optional_present = sum(1 for f in optional_fields if data.get(f))
        
        # Weighted scoring
        critical_score = (critical_present / len(critical_fields)) * 50
        important_score = (important_present / len(important_fields)) * 30
        optional_score = (optional_present / len(optional_fields)) * 20
        
        total_score = critical_score + important_score + optional_score
        
        return {
            "completeness_percentage": round(total_score, 2),
            "critical_fields": {
                "present": critical_present,
                "total": len(critical_fields),
                "score": round(critical_score, 2)
            },
            "important_fields": {
                "present": important_present,
                "total": len(important_fields),
                "score": round(important_score, 2)
            },
            "optional_fields": {
                "present": optional_present,
                "total": len(optional_fields),
                "score": round(optional_score, 2)
            },
            "missing_critical": [f for f in critical_fields if not data.get(f)],
            "missing_important": [f for f in important_fields if not data.get(f)]
        }
    
    def get_overall_grade(self, completeness: float, error_count: int, warning_count: int) -> str:
        """Calculate overall quality grade."""
        # Start with completeness grade
        if completeness >= 90:
            grade = "A"
        elif completeness >= 80:
            grade = "B"
        elif completeness >= 70:
            grade = "C"
        elif completeness >= 60:
            grade = "D"
        else:
            grade = "F"
        
        # Adjust for errors and warnings
        if error_count > 5:
            grade = chr(min(ord(grade) + 2, ord('F')))  # Drop 2 grades
        elif error_count > 2:
            grade = chr(min(ord(grade) + 1, ord('F')))  # Drop 1 grade
        
        if warning_count > 10:
            grade = chr(min(ord(grade) + 1, ord('F')))  # Drop 1 grade
        
        # Add plus/minus
        if completeness >= 95 and error_count == 0 and warning_count <= 2:
            return f"{grade}+"
        elif completeness < 65 or error_count > 3 or warning_count > 8:
            return f"{grade}-"
        
        return grade


def validate_extraction(structured: Dict) -> Dict[str, List[str]]:
    """
    Validate extracted data and return warnings/errors.
    
    Args:
        structured: Extracted legal document data
        
    Returns:
        Dictionary with 'errors' and 'warnings' lists
    """
    validator = ExtractionValidator()
    validator.reset()
    
    # Run all validations
    validator.validate_case_name(structured)
    validator.validate_appeal_number(structured)
    validator.validate_court(structured)
    validator.validate_date(structured)
    validator.validate_coram(structured)
    validator.validate_parties(structured)
    validator.validate_advocates(structured)
    validator.validate_legal_references(structured)
    validator.validate_citations(structured)
    validator.validate_content(structured)
    
    return {
        "errors": validator.errors,
        "warnings": validator.warnings,
        "info": validator.info_messages
    }


def generate_quality_report(structured: Dict) -> Dict[str, Any]:
    """
    Generate comprehensive quality report for extracted data.
    
    Args:
        structured: Extracted legal document data
        
    Returns:
        Detailed quality report with grade, completeness, and issues
    """
    validator = ExtractionValidator()
    validator.reset()
    
    # Run all validations
    validator.validate_case_name(structured)
    validator.validate_appeal_number(structured)
    validator.validate_court(structured)
    validator.validate_date(structured)
    validator.validate_coram(structured)
    validator.validate_parties(structured)
    validator.validate_advocates(structured)
    validator.validate_legal_references(structured)
    validator.validate_citations(structured)
    validator.validate_content(structured)
    
    # Calculate completeness
    completeness_data = validator.calculate_completeness(structured)
    
    # Calculate grade
    overall_grade = validator.get_overall_grade(
        completeness_data["completeness_percentage"],
        len(validator.errors),
        len(validator.warnings)
    )
    
    # Build report
    report = {
        "overall_grade": overall_grade,
        "completeness": completeness_data,
        "validation_results": {
            "errors": validator.errors,
            "warnings": validator.warnings,
            "info": validator.info_messages
        },
        "summary": {
            "total_errors": len(validator.errors),
            "total_warnings": len(validator.warnings),
            "total_info": len(validator.info_messages),
            "has_critical_issues": len(validator.errors) > 0,
            "quality_status": _get_quality_status(overall_grade)
        },
        "field_analysis": {
            "total_fields_extracted": len(structured),
            "critical_fields_present": completeness_data["critical_fields"]["present"],
            "important_fields_present": completeness_data["important_fields"]["present"],
            "optional_fields_present": completeness_data["optional_fields"]["present"]
        },
        "recommendations": _generate_recommendations(
            validator.errors, 
            validator.warnings,
            completeness_data
        )
    }
    
    return report


def _get_quality_status(grade: str) -> str:
    """Get quality status description from grade."""
    if grade.startswith('A'):
        return "Excellent - High quality extraction"
    elif grade.startswith('B'):
        return "Good - Minor issues present"
    elif grade.startswith('C'):
        return "Fair - Several issues to review"
    elif grade.startswith('D'):
        return "Poor - Many issues present"
    else:
        return "Failed - Critical extraction problems"


def _generate_recommendations(errors: List[str], warnings: List[str], 
                              completeness: Dict) -> List[str]:
    """Generate actionable recommendations based on validation results."""
    recommendations = []
    
    if len(errors) > 0:
        recommendations.append(
            "CRITICAL: Address all errors before using this extraction in production"
        )
    
    if completeness["completeness_percentage"] < 70:
        recommendations.append(
            "Low completeness score - consider re-extracting with improved preprocessing"
        )
    
    if completeness.get("missing_critical"):
        recommendations.append(
            f"Missing critical fields: {', '.join(completeness['missing_critical'])} - "
            "Manual verification required"
        )
    
    if len(warnings) > 10:
        recommendations.append(
            "High warning count - review extraction quality and consider document preprocessing"
        )
    
    if not errors and not warnings and completeness["completeness_percentage"] >= 90:
        recommendations.append(
            "Extraction quality is excellent - ready for use"
        )
    
    if not recommendations:
        recommendations.append(
            "Review warnings and verify extracted data before use"
        )
    
    return recommendations


def validate_batch_extractions(extractions: List[Dict]) -> Dict[str, Any]:
    """
    Validate multiple extractions and generate batch report.
    
    Args:
        extractions: List of extracted document data
        
    Returns:
        Batch quality report
    """
    batch_results = []
    
    for i, extraction in enumerate(extractions):
        report = generate_quality_report(extraction)
        batch_results.append({
            "document_index": i,
            "grade": report["overall_grade"],
            "completeness": report["completeness"]["completeness_percentage"],
            "errors": len(report["validation_results"]["errors"]),
            "warnings": len(report["validation_results"]["warnings"])
        })
    
    # Calculate batch statistics
    total_docs = len(extractions)
    avg_completeness = sum(r["completeness"] for r in batch_results) / total_docs
    total_errors = sum(r["errors"] for r in batch_results)
    total_warnings = sum(r["warnings"] for r in batch_results)
    
    grade_distribution = {}
    for result in batch_results:
        grade = result["grade"][0]  # Get letter without +/-
        grade_distribution[grade] = grade_distribution.get(grade, 0) + 1
    
    return {
        "batch_summary": {
            "total_documents": total_docs,
            "average_completeness": round(avg_completeness, 2),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "grade_distribution": grade_distribution
        },
        "individual_results": batch_results,
        "batch_recommendations": _generate_batch_recommendations(
            avg_completeness, 
            total_errors, 
            total_warnings,
            total_docs
        )
    }


def _generate_batch_recommendations(avg_completeness: float, total_errors: int,
                                   total_warnings: int, total_docs: int) -> List[str]:
    """Generate recommendations for batch processing."""
    recommendations = []
    
    error_rate = total_errors / total_docs if total_docs > 0 else 0
    warning_rate = total_warnings / total_docs if total_docs > 0 else 0
    
    if avg_completeness < 70:
        recommendations.append(
            "Batch has low average completeness - review document quality and extraction pipeline"
        )
    
    if error_rate > 2:
        recommendations.append(
            f"High error rate ({error_rate:.1f} errors/doc) - investigate extraction issues"
        )
    
    if warning_rate > 5:
        recommendations.append(
            f"High warning rate ({warning_rate:.1f} warnings/doc) - consider preprocessing improvements"
        )
    
    if avg_completeness >= 85 and error_rate < 1:
        recommendations.append(
            "Batch quality is good - suitable for production use"
        )
    
    return recommendations