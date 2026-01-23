"""модуль для валидации скриптов, созданных chatgpt, для парсинга рецептов с сохранением"""

import os
import importlib
import json
import logging

if __name__ == "__main__":
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


from src.stages.workflow.gpt_recipe_validator import GPTRecipeValidator
from utils.html import extract_text_from_html
from src.stages.workflow.validation_models import ValidationReport, FileValidationResult

logger = logging.getLogger(__name__)

EXTRACTOR_FOLDER = "extractor"
EXTRACTE_JSON_EXTENSION = "_extracted.json"

class ValidateParser:
    """Класс для валидации парсеров рецептов, созданных ChatGPT"""
    def __init__(self, extractor_folder: str = EXTRACTOR_FOLDER, extracted_json_extension: str = EXTRACTE_JSON_EXTENSION):
        self.gpt_validator = GPTRecipeValidator()
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
    
    def validate(self, module_name: str, use_gpt: bool = False, required_fields: list[str] = None, use_gpt_on_missing_fields: bool = True) -> ValidationReport:
        """
        Валидировать скрипт парсера рецептов
        Args:
            module_name: имя модуля скрипта парсера
            use_gpt: использовать ли GPT для валидации 
            required_fields: список обязательных полей в результате парсинга (поля, которые не могут быть None)
            use_gpt_on_missing_fields: использовать ли GPT для валидации при отсутствии обязательных полей

        Returns:
            ValidationReport с результатами валидации
        """
        test_data_dir = os.path.join("preprocessed", module_name)
        validation_report = ValidationReport(module=module_name, total_files=0, failed=0, details=[])
        if not os.path.exists(test_data_dir) or not os.path.isdir(test_data_dir):
            logger.error(f"Директория с тестовыми данными не найдена: {test_data_dir}")
            system_error_result = FileValidationResult.system_error_fail(
                filepath=test_data_dir,
                reason="test_data_directory_not_found"
            )
            validation_report.details.append(system_error_result)
            return validation_report
        
        if len(os.listdir(test_data_dir)) == 0:
            logger.error(f"В директории с тестовыми данными нет файлов: {test_data_dir}")
            sys_error = FileValidationResult.system_error_fail(
                filepath=test_data_dir,
                reason="test_data_directory_empty"
            )
            validation_report.details.append(sys_error)
            return validation_report
        
        # запуск экстрактора для получения распарсеных данных
        self._run_extractor_main(module_name)

        extracted = [i for i in os.listdir(test_data_dir) if i.endswith(self.extracted_json_extension)]
        
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
                    
                            gpt_result = self.gpt_validator.validate_with_html(parsed_data, html_content, module_name, filename=filepath)
                            
                            if gpt_result.is_valid:
                                logger.info(f"✓ Валидация пройдена для {filepath} с помощью GPT")
                                validation_report.passed += 1
                            else:
                                # в реузльтаты записываем только если валидация не пройдена
                                logger.warning(f"✗ Валидация не пройдена для {filepath} с помощью GPT: {gpt_result.feedback}")
                                validation_report.add_result(gpt_result)
                            continue

                    logger.error(f"Валидация не пройдена для файла {filepath}")
                    validation_report.add_result(FileValidationResult(
                        file=filepath,
                        status='failed',
                        is_valid=False,
                        reason='missing_required_fields',
                        feedback='Missing required fields'
                    ))
                    continue
            
            # GPT валидация
            if use_gpt:
                # Находим эталонный JSON файл (без _extracted)
                reference_filename = filename.replace(self.extracted_json_extension, '.json')
                reference_filepath = os.path.join(test_data_dir, reference_filename)
                
                if not os.path.exists(reference_filepath):
                    logger.warning(f"Эталонный JSON файл не найден: {reference_filepath}")
                    validation_report.add_result(FileValidationResult(
                        file=filepath,
                        status='skipped',
                        reason='reference_json_not_found',
                        feedback='Skipped: reference JSON file not found'
                    ))
                    continue
                
                # Читаем эталонный JSON
                with open(reference_filepath, "r", encoding="utf-8") as f:
                    reference_data = json.load(f)
                
                # Валидируем через GPT
                gpt_result = self.gpt_validator.validate_with_reference(parsed_data, reference_data, module_name, filename=filepath)
                
                if gpt_result.is_valid:
                    logger.info(f"✓ Валидация пройдена для {filepath}")
                    validation_report.passed += 1
                else:
                    logger.warning(f"✗ Валидация не пройдена для {filepath}: {gpt_result.feedback}")
                    validation_report.add_result(gpt_result)
            else:
                # Без GPT просто считаем как пройденную
                logger.info(f"✓ Валидация пройдена для {filepath} (без GPT)")
                validation_report.passed += 1
        # Итоговый результат
        total = len(extracted)
        
        logger.info(f"Валидация завершена: {validation_report.passed}/{total} файлов прошли проверку")
        
        return validation_report
    
if __name__ == '__main__':    
    import shutil
    vp = ValidateParser()

    folders = os.listdir("preprocessed")
    folders = sorted([f for f in folders if os.path.isdir(os.path.join("preprocessed", f))])
    
    for folder in folders:
        if folder == "xrysoskoufaki_gr":
            continue
        logger.info(f"\n\n=== ВАЛИДАЦИЯ ПАРСЕРА: {folder} ===")
        result = vp.validate(
            module_name=folder,
            use_gpt=False,
            required_fields=['dish_name', 'ingredients', 'instructions'],
            use_gpt_on_missing_fields=True
        )
        if result.failed == 0 and result.passed > 0:
            logger.info(f"ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО ДЛЯ {folder}!\n")
            shutil.rmtree(os.path.join("preprocessed", folder))
        else:
            logger.info(f"РЕЗУЛЬТАТЫ ВАЛИДАЦИИ ДЛЯ {folder}:\n")
            print(result.to_dict())

    
