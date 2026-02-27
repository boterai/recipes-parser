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
    
    def _build_reference_validation_prompt(self, site_name: str) -> str:
        """Build system prompt for reference-based validation"""
        return f"""You are a recipe extraction validator for {site_name}.
Compare extracted recipe data against reference data.

RULES:
- If the page is NOT a recipe -> is_valid: true, is_recipe: false (empty extraction is correct)
- CRITICAL fields: dish_name, ingredients, instructions — must be present and semantically similar to reference
  * Order, formatting, case, minor wording differences are OK
  * Fail only if >50% of content is missing or completely wrong
- OPTIONAL fields (prep_time, cook_time, tags, etc.) — ignore differences, never fail for these

Return STRICT JSON:
{FileValidationResult.GPT_RESPONSE_FORMAT}"""
    
    def _build_html_validation_prompt(self, site_name: str) -> str:
        """Build system prompt for HTML-based validation"""
        return f"""You are a recipe extraction validator for {site_name}.
You receive plain text from a page and extracted recipe data. Validate the extraction.

RULES:
- If the page is NOT a recipe (homepage, category page, no ingredients/instructions) -> is_valid: true, is_recipe: false
- CRITICAL fields: dish_name, ingredients, instructions — must be present and match page content semantically
  * Order, formatting, case, paraphrasing are OK
  * Fail only if >50% of content is missing or completely wrong
- OPTIONAL fields (prep_time, cook_time, tags, servings, author, etc.) — ignore differences, never fail for these

Return STRICT JSON:
{FileValidationResult.GPT_RESPONSE_FORMAT}"""
    
    def _build_reference_user_prompt(self, extracted_data: dict, reference_data: dict) -> str:
        """Build user prompt for reference-based validation"""
        return f"""Compare extracted data with reference data.

Extracted data:
{json.dumps(extracted_data, ensure_ascii=False, indent=2)}

Reference data:
{json.dumps(reference_data, ensure_ascii=False, indent=2)}

Validate the extraction quality and return JSON with validation results."""
    
    def _build_html_user_prompt(self, extracted_data: dict, html_content: str) -> str:
        """Build user prompt for HTML-based validation"""
        return f"""Analyze the page TEXT content and validate the extracted data.

Extracted data:
{json.dumps(extracted_data, ensure_ascii=False, indent=2)}

Page text content (may be truncated):
{html_content}

Return JSON validation results."""
