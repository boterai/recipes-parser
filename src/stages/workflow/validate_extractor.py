"""модуль для валидации скриптов, созданных chatgpt, для парсинга рецептов с сохранением"""

import os
import importlib
import json
import logging

if __name__ == "__main__":
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


from src.common.gpt.client import GPTClient
from utils.html import extract_text_from_html


logger = logging.getLogger(__name__)

EXTRACTOR_FOLDER = "extractor"
EXTRACTE_JSON_EXTENSION = "_extracted.json"

class ValidateParser:
    """Класс для валидации парсеров рецептов, созданных ChatGPT"""
    def __init__(self, extractor_folder: str = EXTRACTOR_FOLDER, extracted_json_extension: str = EXTRACTE_JSON_EXTENSION):
        self.gpt_client = GPTClient()  # инициализация GPT клиента здесь
        self.extractor_folder = extractor_folder
        self.extracted_json_extension = extracted_json_extension

    def _import_extractor_module(self, module_name: str):
        """Динамически импортирует модуль экстрактора по имени"""
        extractor_path = os.path.join(self.extractor_folder, f'{module_name}.py')
        if not os.path.exists(extractor_path):
            logger.error(f"Модуль экстрактора {module_name} не найден по пути {extractor_path}")
            return None
        
        module = importlib.import_module(f"extractor.{module_name}")
        return module
    

    def _run_extractor_main(self, module_name: str):
        """Запускает функцию main экстрактора и возвращает результат"""
        module = self._import_extractor_module(module_name)
        if module is None:
            logger.error(f"Не удалось импортировать модуль экстрактора {module_name}")
            return
        
        if not hasattr(module, "main"):
            logger.error(f"Модуль экстрактора {module_name} не содержит функцию main")
            return

        main_func = getattr(module, "main")
        logger.info(f"Запуск экстрактора {module_name}")
        result = main_func()
        return result


    def _validate_required_fields(self, parsed_data: dict, required_fields: list[str]) -> bool:
        """Проверяет наличие обязательных полей в распарсеных данных"""
        for field in required_fields:
            if field not in parsed_data or parsed_data[field] is None:
                logger.error(f"Отсутствует обязательное поле: {field}")
                return False
        return True
    

    def _validate_with_gpt(self, extracted_data: dict, reference_data: dict, site_name: str) -> dict:
        """
        Валидирует извлеченные данные с помощью GPT, сравнивая с эталонным JSON
        
        Args:
            extracted_data: Извлеченные данные из _extracted.json
            reference_data: Эталонные данные из .json (без _extracted)
            site_name: Название сайта (для контекста)
        
        Returns:
            Словарь с результатами валидации:
            {
                'is_valid': bool,
                'missing_fields': list[str],
                'incorrect_fields': list[str],
                'feedback': str,
                'is_recipe': bool
            }
        """
        system_prompt = f"""You are a recipe data validation expert for {site_name}.
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
{{
    "is_valid": true/false,
    "is_recipe": true/false,
    "missing_fields": ["field1", "field2"],
    "incorrect_fields": ["field3"],
    "feedback": "Brief explanation focusing on critical fields",
    "fix_recommendations": [
        {{
            "field": "field_name",
            "issue": "what's wrong",
            "expected_value": "what should be extracted (from reference)",
            "actual_value": "what was extracted",
            "fix_suggestion": "how to fix the extractor (e.g., check CSS selector, parsing logic)"
        }}
    ]
}}

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

        user_prompt = f"""Compare extracted data with reference data.

Extracted data:
{json.dumps(extracted_data, ensure_ascii=False, indent=2)}

Reference data:
{json.dumps(reference_data, ensure_ascii=False, indent=2)}

Validate the extraction quality and return JSON with validation results."""

        try:
            schema = {
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
                                "fix_suggestion": {"type": "string"}
                            }
                        }
                    }
                }
            }
            
            result = self.gpt_client.request(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.1,
                    response_schema=schema,
                    retry_attempts=2
                )
            
            logger.info(f"GPT validation result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка GPT валидации: {e}")
            return {
                'is_valid': False,
                'is_recipe': True,
                'missing_fields': [],
                'incorrect_fields': [],
                'feedback': f'GPT validation error: {str(e)}',
                'fix_recommendations': []
            }


    def _validate_with_gpt_html(self, extracted_data: dict, html_content: str, site_name: str) -> dict:
        """
        Валидирует извлеченные данные с помощью GPT, сравнивая с HTML страницей
        
        Args:
            extracted_data: Извлеченные данные из _extracted.json
            html_content: Содержимое оригинального HTML файла
            site_name: Название сайта (для контекста)
        
        Returns:
            Словарь с результатами валидации:
            {
                'is_valid': bool,
                'is_recipe': bool,
                'missing_fields': list[str],
                'incorrect_fields': list[str],
                'feedback': str,
                'extracted_missing_data': dict
            }
        """
        system_prompt = f"""You are a recipe data validation expert for {site_name}.
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
{{
    "is_valid": true/false,
    "is_recipe": true/false,
    "missing_fields": ["field1", "field2"],
    "incorrect_fields": ["field3"],
    "feedback": "Brief explanation focusing on critical fields",
    "fix_recommendations": [
        {{
            "field": "field_name",
            "issue": "what's wrong (e.g., 'not extracted', 'incomplete', 'incorrect')",
            "correct_value_from_text": "actual correct value you found in the page text",
            "actual_extracted_value": "what was extracted (or empty/null)",
            "text_context": "surrounding text where this data appears (quote 1-2 sentences)",
            "pattern_hint": "describe the pattern/location in text (e.g., 'appears after \"Ingredients:\"", \"listed as bullet points\", \"in the title section\"')",
            "fix_suggestion": "how to improve extraction logic (e.g., 'look for text after \"Ingredients:\" heading', 'extract list items', 'parse cooking time from \"30 min\" pattern')"
        }}
    ]
}}

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

        user_prompt = f"""Analyze the page TEXT content and validate the extracted data.

Extracted data:
{json.dumps(extracted_data, ensure_ascii=False, indent=2)}

Page text content (may be truncated):
{html_content}

Task:
1. Is this a recipe page? (look for recipe-specific content like dish name, ingredients list, cooking instructions)
2. If YES and extraction is wrong/incomplete: provide fix_recommendations with text patterns and context
3. If NO (not a recipe): mark is_valid=true, is_recipe=false
4. Extract missing data from text into extracted_missing_data

IMPORTANT: Base your analysis ONLY on the text content above. Do NOT suggest HTML selectors or CSS classes.

Return JSON validation results."""

        try:
            schema = {
                "properties": {
                    "is_valid": {"type": "boolean"},
                    "is_recipe": {"type": "boolean"},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                    "incorrect_fields": {"type": "array", "items": {"type": "string"}},
                    "feedback": {"type": "string"},
                    "extracted_missing_data": {"type": "object"},
                    "fix_recommendations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "issue": {"type": "string"},
                                "correct_value_from_text": {"type": "string"},
                                "actual_extracted_value": {"type": "string"},
                                "text_context": {"type": "string"},
                                "pattern_hint": {"type": "string"},
                                "fix_suggestion": {"type": "string"}
                            }
                        }
                    }
                }
            }
            
            result = self.gpt_client.request(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.1,
                    response_schema=schema,
                    retry_attempts=2
                )
                        
            logger.info(f"GPT HTML validation result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка GPT HTML валидации: {e}")
            return {
                'is_valid': False,
                'is_recipe': True,
                'feedback': f'GPT HTML validation error: {str(e)}',
            }


    def validate(self, module_name: str, use_gpt: bool = False, required_fields: list[str] = None, use_gpt_on_missing_fields: bool = True) -> dict:
        """
        Валидировать скрипт парсера рецептов
        :param module_name: имя модуля скрипта парсера
        :param use_gpt: использовать ли GPT для валидации 
        :param required_fields: список обязательных полей в результате парсинга (поля, которые не могут быть None)
        :param use_gpt_on_missing_fields: использовать ли GPT для валидации при отсутствии обязательных полей
        """
        test_data_dir = os.path.join("preprocessed", module_name)
        if not os.path.exists(test_data_dir) or not os.path.isdir(test_data_dir):
            logger.error(f"Директория с тестовыми данными не найдена: {test_data_dir}")
            return {
                'module': module_name,
                'error': 'test_data_directory_not_found'
            }
        
        if len(os.listdir(test_data_dir)) == 0:
            logger.error(f"В директории с тестовыми данными нет файлов: {test_data_dir}")
            return {
                'module': module_name,
                'error': 'test_data_directory_empty'
            }


        # запуск экстрактора для получения распарсеных данных
        self._run_extractor_main(module_name)

        extracted = [i for i in os.listdir(test_data_dir) if i.endswith(self.extracted_json_extension)]
        failed_results = []
        
        for filename in extracted:
            filepath = os.path.join(test_data_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                parsed_data = json.load(f)
            
            # Проверка обязательных полей
            if required_fields:
                if not self._validate_required_fields(parsed_data, required_fields):
                    if use_gpt_on_missing_fields:
                        html_filepath = filepath.replace(self.extracted_json_extension, '.html')
                        html_content = extract_text_from_html(html_filepath, max_chars=30000)
                        if html_content:
                    
                            gpt_result = self._validate_with_gpt_html(parsed_data, html_content, module_name)
                            
                            if gpt_result.get('is_valid'):
                                logger.info(f"✓ Валидация пройдена для {filepath} с помощью GPT")
                            else:
                                # в реузльтаты записываем только если валидация не пройдена
                                logger.warning(f"✗ Валидация не пройдена для {filepath} с помощью GPT: {gpt_result.get('feedback')}")
                                failed_results.append({ 
                                    'file': filepath,
                                    'status': 'passed' if gpt_result.get('is_valid') else 'failed',
                                    'gpt_validation': gpt_result
                                })
                            continue

                    logger.error(f"Валидация не пройдена для файла {filepath}")
                    failed_results.append({
                        'file': filepath,
                        'status': 'failed',
                        'reason': 'missing_required_fields'
                    })
                    continue
            
            # GPT валидация
            if use_gpt:
                # Находим эталонный JSON файл (без _extracted)
                reference_filename = filename.replace(self.extracted_json_extension, '.json')
                reference_filepath = os.path.join(test_data_dir, reference_filename)
                
                if not os.path.exists(reference_filepath):
                    logger.warning(f"Эталонный JSON файл не найден: {reference_filepath}")
                    failed_results.append({
                        'file': filepath,
                        'status': 'skipped',
                        'reason': 'reference_json_not_found'
                    })
                    continue
                
                # Читаем эталонный JSON
                with open(reference_filepath, "r", encoding="utf-8") as f:
                    reference_data = json.load(f)
                
                # Валидируем через GPT
                gpt_result = self._validate_with_gpt(parsed_data, reference_data, module_name)
                
                if gpt_result.get('is_valid'):
                    logger.info(f"✓ Валидация пройдена для {filepath}")
                else:
                    logger.warning(f"✗ Валидация не пройдена для {filepath}: {gpt_result.get('feedback')}")
                    failed_results.append({
                    'file': filepath,
                    'status': 'passed' if gpt_result.get('is_valid') else 'failed',
                    'gpt_validation': gpt_result
                })
        
        # Итоговый результат
        total = len(extracted)
        
        logger.info(f"Валидация завершена: {total-len(failed_results)}/{total} файлов прошли проверку")
        
        return {
            'module': module_name,
            'total_files': total,
            'failed': len(failed_results),
            'details': failed_results
        }
    
if __name__ == '__main__':    
    vp = ValidateParser()

    result = vp.validate(
        module_name="nutrip_gr",
        use_gpt=True,
        required_fields=['dish_name', 'ingredients', 'instructions'],
        use_gpt_on_missing_fields=True
    )
    pass

    
