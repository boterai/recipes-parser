
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, ClassVar

@dataclass
class FieldValidation:
    """Validation details for a specific field"""
    field: str
    issue: str
    actual_extracted_value: Optional[str] = None
    correct_value_from_text: Optional[str] = None
    text_context: Optional[str] = None
    pattern_hint: Optional[str] = None
    fix_suggestion: Optional[str] = None
    

@dataclass
class FileValidationResult:
    """Validation result for a single file"""
    file: str
    status: str  # 'passed', 'failed', 'system_error', 'skipped'
    is_valid: bool = False
    is_recipe: bool = True
    missing_fields: list[str] = field(default_factory=list)
    incorrect_fields: list[str] = field(default_factory=list)
    feedback: Optional[str] = None
    fix_recommendations: list[FieldValidation] = field(default_factory=list)
    system_error: bool = False
    reason: Optional[str] = None
    GPT_RESPONSE_FORMAT: ClassVar[str] = """
{
    "is_valid": true/false,
    "is_recipe": true/false,
    "missing_fields": ["field1", "field2"],
    "incorrect_fields": ["field3"],
    "feedback": "Brief explanation focusing on critical fields",
    "fix_recommendations": [
        {
            "field": "field_name",
            "issue": "what's wrong (e.g., 'not extracted', 'incomplete', 'incorrect')",
            "correct_value_from_text": "actual correct value you found in the page text",
            "actual_extracted_value": "what was extracted (or empty/null)",
            "text_context": "surrounding text where this data appears (quote 1-2 sentences)",
            "pattern_hint": "describe the pattern/location in text (e.g., 'appears after \"Ingredients:\"", \"listed as bullet points\", \"in the title section\"')",
            "fix_suggestion": "how to improve extraction logic (e.g., 'look for text after \"Ingredients:\" heading', 'extract list items', 'parse cooking time from \"30 min\" pattern')"
        }
    ]
}
"""
    
    @classmethod
    def from_gpt_result(cls, filepath: str, gpt_result: dict[str, Any]) -> 'FileValidationResult':
        """Create FileValidationResult from GPT validation response"""
        # Parse fix_recommendations into FieldValidation objects
        fix_recs = []
        for rec in gpt_result.get('fix_recommendations', []):
            fix_recs.append(FieldValidation(**rec))
        
        status = 'system_error' if gpt_result.get('system_error') else \
                 ('passed' if gpt_result.get('is_valid') else 'failed')
        
        return cls(
            file=filepath,
            status=status,
            is_valid=gpt_result.get('is_valid', False),
            is_recipe=gpt_result.get('is_recipe', True),
            missing_fields=gpt_result.get('missing_fields', []),
            incorrect_fields=gpt_result.get('incorrect_fields', []),
            feedback=gpt_result.get('feedback'),
            fix_recommendations=fix_recs,
            system_error=gpt_result.get('system_error', False)
        )
    
    @classmethod
    def system_error_fail(cls, filepath: str, reason: str) -> 'FileValidationResult':
        """Create a failed validation result"""
        return cls(
            file=filepath,
            status='system_error',
            reason=reason,
            feedback=f"System error: {reason}",
            system_error=True,
            is_valid=False
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'file': self.file,
            'status': self.status,
            'is_valid': self.is_valid,
            'is_recipe': self.is_recipe,
            'missing_fields': self.missing_fields,
            'incorrect_fields': self.incorrect_fields,
            'feedback': self.feedback,
            'fix_recommendations': [
                {k: v for k, v in vars(rec).items() if v is not None}
                for rec in self.fix_recommendations
            ],
            'system_error': self.system_error,
            'reason': self.reason
        }
    
    @classmethod
    def gpt_validation_schema(cls) -> dict:
        """Get JSON schema for validation response"""
        return {
            "properties": {
                "is_valid": {"type": "boolean"},
                "is_recipe": {"type": "boolean"},
                "missing_fields": {"type": "array", "items": {"type": "string"}},
                "incorrect_fields": {"type": "array", "items": {"type": "string"}},
                "feedback": {"type": "string"},
                "fix_recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "issue": {"type": "string"},
                            "expected_value": {"type": "string"},
                            "actual_value": {"type": "string"},
                            "fix_suggestion": {"type": "string"},
                            "correct_value_from_text": {"type": "string"},
                            "actual_extracted_value": {"type": "string"},
                            "text_context": {"type": "string"},
                            "pattern_hint": {"type": "string"}
                        }
                    }
                }
            }
        }


@dataclass
class ValidationReport:
    """Complete validation report for a module"""
    module: str
    total_files: int
    passed: int = 0
    failed: int = 0
    system_errors: int = 0
    skipped: int = 0
    details: list[FileValidationResult] = field(default_factory=list)
    error: Optional[str] = None
    
    def add_result(self, result: FileValidationResult):
        """Add a file validation result and update counters"""
        self.details.append(result)
        
        if result.status == 'passed':
            self.passed += 1
        elif result.status == 'failed':
            self.failed += 1
        elif result.status == 'system_error':
            self.system_errors += 1
        elif result.status == 'skipped':
            self.skipped += 1
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate (passed / total)"""
        if self.total_files == 0:
            return 0.0
        return (self.passed / self.total_files) * 100
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {
            'module': self.module,
            'total_files': self.total_files,
            'passed': self.passed,
            'failed': self.failed,
            'system_errors': self.system_errors,
            'skipped': self.skipped,
            'success_rate': round(self.success_rate, 2),
            'details': [detail.to_dict() for detail in self.details]
        }
        
        if self.error:
            result['error'] = self.error
        
        return result
    
    @classmethod
    def error_report(cls, module: str, error_message: str) -> 'ValidationReport':
        """Create an error report"""
        return cls(
            module=module,
            total_files=0,
            error=error_message
        )