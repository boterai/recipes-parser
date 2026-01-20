"""модуль для валидации скриптов, созданных chatgpt, для парсинга рецептов с сохранением"""

import os
import importlib
import json
import logging
import asyncio

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
2. Are the extracted fields matching the reference data?
3. Is the extraction quality acceptable?

IMPORTANT: If the page is clearly NOT a recipe (e.g. no ingredients, no instructions, generic content), 
then the extraction is VALID even if fields are empty - mark is_valid: true, is_recipe: false.

Return STRICT JSON format:
{{
    "is_valid": true/false,
    "is_recipe": true/false,
    "missing_fields": ["field1", "field2"],
    "incorrect_fields": ["field3"],
    "feedback": "Brief explanation"
}}

Validation rules:
- If page is NOT a recipe -> is_valid: true, is_recipe: false (empty extraction is correct)
- If page IS a recipe and dish_name, ingredients, instructions are present and mostly match reference -> is_valid: true, is_recipe: true
- If page IS a recipe but extraction is wrong/incomplete -> is_valid: false, is_recipe: true
- Minor differences are fully acceptable"""

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
                    "feedback": {"type": "string"}
                }
            }
            
            result = asyncio.run(
                self.gpt_client.async_request(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.1,
                    response_schema=schema,
                    retry_attempts=2
                )
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
                'feedback': f'GPT validation error: {str(e)}'
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
1. Analyze the HTML page and determine if it contains a recipe
2. Compare extracted data with the HTML content
3. Validate extraction quality
4. If data is missing, try to extract it from HTML

CRITICAL: If the HTML page is clearly NOT a recipe (e.g. homepage, category page, about page, no ingredients/instructions visible),
then empty extraction is CORRECT - mark is_valid: true, is_recipe: false.

Return STRICT JSON format:
{{
    "is_valid": true/false,
    "is_recipe": true/false,
    "missing_fields": ["field1", "field2"],
    "incorrect_fields": ["field3"],
    "feedback": "Brief explanation",
    "extracted_missing_data": {{"field1": "value from HTML", "field2": "value from HTML"}}
}}

Validation rules:
- If HTML is NOT a recipe page -> is_valid: true, is_recipe: false (empty/minimal extraction is correct)
- If HTML IS a recipe and extracted data matches -> is_valid: true, is_recipe: true
- If HTML IS a recipe but extraction is incomplete/wrong -> is_valid: false, is_recipe: true
- Minor formatting differences are acceptable
- For missing_fields, try to extract the data from HTML and put it in extracted_missing_data"""

        user_prompt = f"""Analyze the HTML and validate the extracted data.

Extracted data:
{json.dumps(extracted_data, ensure_ascii=False, indent=2)}

HTML content (first 3000 chars):
{html_content}

Is this a recipe page? If yes, is the extraction correct? If data is missing, extract it from HTML. Return JSON validation results."""

        try:
            schema = {
                "properties": {
                    "is_valid": {"type": "boolean"},
                    "is_recipe": {"type": "boolean"},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                    "incorrect_fields": {"type": "array", "items": {"type": "string"}},
                    "feedback": {"type": "string"},
                    "extracted_missing_data": {"type": "object"}
                }
            }
            
            result = asyncio.run(
                self.gpt_client.async_request(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.1,
                    response_schema=schema,
                    retry_attempts=2
                )
            )
            
            logger.info(f"GPT HTML validation result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка GPT HTML валидации: {e}")
            return {
                'is_valid': False,
                'is_recipe': True,
                'missing_fields': [],
                'incorrect_fields': [],
                'feedback': f'GPT HTML validation error: {str(e)}',
                'extracted_missing_data': {}
            }


    def validate(self, module_name: str, use_gpt: bool = False, required_fields: list[str] = None, use_gpt_on_errors_only: bool = True) -> dict:
        """
        Валидировать скрипт парсера рецептов
        :param module_name: имя модуля скрипта парсера
        :param use_gpt: использовать ли GPT для валидации 
        :param required_fields: список обязательных полей в результате парсинга (поля, которые не могут быть None)
        """
        test_data_dir = os.path.join("preprocessed", module_name)
        if not os.path.exists(test_data_dir) or not os.path.isdir(test_data_dir):
            logger.error(f"Директория с тестовыми данными не найдена: {test_data_dir}")
            return {
                'module': module_name,
                'total_files': 0,
                'passed': 0,
                'failed': 0,
                'details': [],
                'error': 'test_data_directory_not_found'
            }
        
        if len(os.listdir(test_data_dir)) == 0:
            logger.error(f"В директории с тестовыми данными нет файлов: {test_data_dir}")
            return {
                'module': module_name,
                'total_files': 0,
                'passed': 0,
                'failed': 0,
                'details': [],
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
                    if use_gpt_on_errors_only and use_gpt is False:
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

    folders = os.listdir("preprocessed")
    results = {}
    for folder in folders:
        # Пример: валидация с GPT
        if not os.path.exists(os.path.join(EXTRACTOR_FOLDER, folder + '.py')):
            continue
        result = vp.validate(
            module_name=folder,
            use_gpt=False,
            required_fields=['dish_name', 'ingredients', 'instructions'],
            use_gpt_on_errors_only=True
        )
        if result.get("total_files") == 0 or result.get("failed") != 0:
            results[folder] = result

    with open("fails.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
