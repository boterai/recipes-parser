"""GPT-based recipe extraction validator"""

import json
import logging
from typing import Optional
from src.common.gpt.client import GPTClient

logger = logging.getLogger(__name__)

from src.stages.workflow.validation_models import FileValidationResult


class GPTRecipeValidator:
    """Validates recipe extraction using GPT API"""
    
    def __init__(self, gpt_client: Optional[GPTClient] = None):
        self.gpt_client = gpt_client or GPTClient()
    
    def validate_with_reference(
        self, 
        extracted_data: dict, 
        reference_data: dict, 
        site_name: str,
        filename: str
    ) -> FileValidationResult:
        """Validate extracted data against reference JSON"""
        system_prompt = self._build_reference_validation_prompt(site_name)
        user_prompt = self._build_reference_user_prompt(extracted_data, reference_data)
        
        return self._execute_validation(system_prompt, user_prompt, filename)
    
    def validate_with_html(
        self, 
        extracted_data: dict, 
        html_content: str, 
        site_name: str,
        filename: str
    ) -> FileValidationResult:
        """Validate extracted data against HTML text content"""
        system_prompt = self._build_html_validation_prompt(site_name)
        user_prompt = self._build_html_user_prompt(extracted_data, html_content)
        
        return self._execute_validation(system_prompt, user_prompt, filename)
    
    def _execute_validation(self, system_prompt: str, user_prompt: str, filename: str) -> FileValidationResult:
        """Execute GPT validation request with error handling"""
        schema = FileValidationResult.gpt_validation_schema()
        
        try:
            result = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                response_schema=schema,
                retry_attempts=5,
                timeout=60
            )
            logger.info(f"GPT validation result: {result.get('is_valid')}")
            
            return FileValidationResult.from_gpt_result(filename, result)
            
        except Exception as e:
            logger.error(f"System error in GPT validation: {e}")
            return FileValidationResult.system_error_fail(filename, str(e))
    
    _VALIDATION_RULES = """RULES:
- Not a recipe page -> is_valid:true, is_recipe:false
- REQUIRED non-empty: dish_name, ingredients, instructions. Missing any -> is_valid:false, add to missing_fields
- ingredients: PASS if same core ingredients (different names/units/amounts/language OK, minor omissions OK). FAIL only if fundamentally different dish
- instructions: PASS if same cooking process (different wording/detail/order OK, more detail is fine). FAIL only if completely different process
- dish_name: same dish (synonyms/translations OK)
- description & all other fields (prep_time, cook_time, tags, etc.): NEVER fail on differences
- More detailed extraction is always valid. Be lenient: pass if someone could cook the same dish."""

    def _build_reference_validation_prompt(self, site_name: str) -> str:
        """Build system prompt for reference-based validation"""
        return f"""Recipe extraction validator for {site_name}. Compare extracted data against reference.
{self._VALIDATION_RULES}

Return STRICT JSON:
{FileValidationResult.GPT_RESPONSE_FORMAT}"""
    
    def _build_html_validation_prompt(self, site_name: str) -> str:
        """Build system prompt for HTML-based validation"""
        return f"""Recipe extraction validator for {site_name}. Compare extracted data against page text.
{self._VALIDATION_RULES}

Return STRICT JSON:
{FileValidationResult.GPT_RESPONSE_FORMAT}"""
    
    def _build_reference_user_prompt(self, extracted_data: dict, reference_data: dict) -> str:
        """Build user prompt for reference-based validation"""
        return f"""Extracted:
{json.dumps(extracted_data, ensure_ascii=False)}

Reference:
{json.dumps(reference_data, ensure_ascii=False)}"""
    
    def _build_html_user_prompt(self, extracted_data: dict, html_content: str) -> str:
        """Build user prompt for HTML-based validation"""
        return f"""Extracted:
{json.dumps(extracted_data, ensure_ascii=False)}

Page text:
{html_content}"""
