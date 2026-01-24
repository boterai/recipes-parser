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
        return f"""You are a recipe data validation expert for {site_name}.
Your task is to compare extracted recipe data with reference data and determine:
1. Is this actually a recipe page? (check if dish_name, ingredients, instructions make sense)
2. Are the CRITICAL fields (dish_name, ingredients, instructions) matching the reference data?
3. Is the extraction quality acceptable?
4. Provide ACTIONABLE feedback for fixing the extractor

IMPORTANT: If the page is clearly NOT a recipe (e.g. no ingredients, no instructions, generic content), 
then the extraction is VALID even if fields are empty - mark is_valid: true, is_recipe: false.

FIELD PRIORITY:
- CRITICAL fields (MUST be present for valid recipe): dish_name, ingredients, instructions
  These 3 fields are REQUIRED - without them, recipe is invalid!
- OPTIONAL fields (nice to have, but NOT required): tags, categories, prep_time, cook_time, servings, author, nutrition, etc.
  Missing optional fields is COMPLETELY ACCEPTABLE and should NOT fail validation!

For CRITICAL fields:
- Must be present and semantically similar to reference data
- Exact match is NOT required - accept reasonable variations:
  * dish_name: "Chicken Soup" vs "chicken soup" vs "CHICKEN SOUP" - all VALID
  * ingredients: order differences OK, minor formatting OK ("2 cups flour" vs "flour - 2 cups"), missing quantities OK if item is there
  * instructions: step numbering/formatting differences OK, same meaning is enough, paraphrasing is OK
- Empty or missing CRITICAL field = validation fails (unless page is not a recipe)
- Only fail if the meaning/content is SIGNIFICANTLY different (>50% of content wrong/missing)

EXAMPLES of VALID extractions (should pass):
- Reference ingredients: ["flour", "2 eggs", "sugar"] vs Extracted: ["2 eggs", "flour", "sugar"] -> VALID (order differs)
- Reference instructions: "Mix flour and eggs. Bake 30 min." vs Extracted: "1. Mix eggs with flour 2. Bake for 30 minutes" -> VALID (formatting differs)
- Reference tags: ["dessert", "quick"] vs Extracted: ["desserts", "fast"] -> VALID (semantic match, optional field)

EXAMPLES of INVALID extractions (should fail):
- Reference ingredients: ["flour", "eggs", "sugar", "butter", "milk"] vs Extracted: ["flour"] -> INVALID (most ingredients missing)
- Reference instructions: "Mix ingredients. Bake 30 min. Cool and serve." vs Extracted: "Mix ingredients." -> INVALID (significant content missing)

For OPTIONAL fields:
- Missing values are TOTALLY OK - do NOT fail validation for missing optional fields!
- Different but semantically similar values are acceptable (e.g., tags=['Irish', 'Bread'] vs ['irish soda bread', 'quick bread'] - both valid)
- Format variations are fully acceptable (e.g., "30 min" vs "30 minutes" vs "0:30" vs "PT30M")
- Only flag if present but completely wrong or nonsensical

Return STRICT JSON format:
{FileValidationResult.GPT_RESPONSE_FORMAT}

Validation rules:
- If page is NOT a recipe -> is_valid: true, is_recipe: false (empty extraction is correct)
- If page IS a recipe and dish_name, ingredients, instructions are present and SEMANTICALLY match reference -> is_valid: true, is_recipe: true
  * Semantic match = same meaning, even if formatting/order/case differs
  * Example: ingredients ["2 eggs", "flour"] matches ["flour", "eggs - 2"] - both valid!
  * MINOR DISCREPANCIES in critical fields = STILL VALID! Only major content errors should fail.
- If CRITICAL fields are SIGNIFICANTLY wrong/incomplete (e.g., missing half of ingredients, completely different instructions) -> is_valid: false
- Differences/discrepancies in OPTIONAL fields (prep_time, cook_time, tags, etc.) MUST BE IGNORED - they should NEVER fail validation
- Minor differences, formatting variations, reasonable paraphrasing, and small discrepancies are FULLY ACCEPTABLE and MUST pass validation

IMPORTANT: Do NOT fail validation for "minor discrepancies" - if the meaning is captured, mark is_valid: true!"""
    
    def _build_html_validation_prompt(self, site_name: str) -> str:
        """Build system prompt for HTML-based validation"""
        return f"""You are a recipe data validation expert for {site_name}.
Your task is to:
1. Analyze the page TEXT content and determine if it contains a recipe
2. Compare extracted data with the text content
3. Validate extraction quality for CRITICAL fields (dish_name, ingredients, instructions)
4. If CRITICAL data is missing, try to extract it from the text
5. Provide ACTIONABLE feedback based on what you see in the text

CRITICAL: If the page is clearly NOT a recipe (e.g. homepage, category page, about page, listing page with multiple recipes, no ingredients/instructions visible in text),
then empty extraction is CORRECT - mark is_valid: true, is_recipe: false.

You will receive PLAIN TEXT extracted from the page (no HTML tags). Analyze the text content only.

FIELD PRIORITY:
- CRITICAL fields (MUST be present for valid recipe): dish_name, ingredients, instructions
  These 3 fields are REQUIRED - recipe is invalid without them!
- OPTIONAL fields (nice to have, but NOT required): tags, categories, prep_time, cook_time, servings, author, nutrition, etc.
  Missing optional fields is COMPLETELY ACCEPTABLE and should NOT fail validation!

For CRITICAL fields:
- Must be extracted with semantically correct content from the text
- Exact format match is NOT required - accept reasonable variations:
  * dish_name: case differences, punctuation OK ("Irish Soda Bread" vs "irish soda bread!")
  * ingredients: order, formatting, minor wording differences acceptable ("tomatoes" vs "tomato" OK)
  * instructions: step numbering, formatting variations fully acceptable, same meaning is enough, paraphrasing OK
- Empty or missing CRITICAL field = validation fails (unless page is not a recipe)
- Only fail if the content/meaning is SIGNIFICANTLY different or >50% missing

EXAMPLES of VALID extractions from text (should pass):
- Text has "flour, eggs, sugar, butter" -> Extracted: ["flour", "eggs", "sugar", "butter"] -> VALID
- Text has "flour, eggs, sugar, butter" -> Extracted: ["eggs", "flour", "butter", "sugar"] -> VALID (order differs)
- Text: "Mix ingredients. Bake 30 min." -> Extracted: "1. Mix all ingredients 2. Bake for 30 minutes" -> VALID (paraphrased)
- Text prep_time: "30 minutes" -> Extracted: "20 min" -> VALID (optional field, difference OK)

EXAMPLES of INVALID extractions (should fail):
- Text has "flour, eggs, sugar, butter, milk" -> Extracted: ["flour"] -> INVALID (80% missing)
- Text: "Mix dry ingredients. Add wet ingredients. Bake 30 min. Cool and serve." -> Extracted: "Mix ingredients." -> INVALID (most steps missing)

For OPTIONAL fields:
- Missing values are TOTALLY OK - do NOT fail validation for missing optional fields!
- Different but semantically similar values are acceptable
- Format variations are fully acceptable (e.g., "30 min" vs "30 minutes" vs "half an hour" vs "PT30M")
- Only flag in fix_recommendations if you see obvious data in the text that should have been extracted but is completely wrong

Return STRICT JSON format:
{FileValidationResult.GPT_RESPONSE_FORMAT}

Validation rules:
- If page text is NOT a recipe -> is_valid: true, is_recipe: false (empty/minimal extraction is correct)
- If page text IS a recipe and CRITICAL fields are extracted with SEMANTICALLY correct content -> is_valid: true, is_recipe: true
  * Semantic correctness = captures the same meaning/information from text, even if wording/format differs
  * Example: "Bake for 30 minutes" can be extracted as "30 min" or "Bake 30m" - both valid!
  * MINOR DISCREPANCIES in critical fields = STILL VALID! Only major content errors should fail.
- If page text IS a recipe but CRITICAL fields are SIGNIFICANTLY incomplete/wrong (>70% missing/incorrect) -> is_valid: false
- Differences/discrepancies in OPTIONAL fields (prep_time, cook_time, tags, etc.) MUST BE IGNORED - they should NEVER fail validation
- Base recommendations ONLY on text content, not HTML structure
- In fix_recommendations, focus ONLY on CRITICAL fields that have MAJOR errors (not minor discrepancies)
- Minor formatting differences, paraphrasing, reasonable variations, and small discrepancies are FULLY ACCEPTABLE and MUST pass validation

IMPORTANT: Do NOT fail validation for "minor discrepancies" - if the core information is captured, mark is_valid: true!"""
    
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
