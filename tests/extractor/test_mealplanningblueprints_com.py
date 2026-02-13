"""
Тесты для экстрактора mealplanningblueprints.com
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.mealplanningblueprints_com import MealPlanningBlueprintsExtractor


class TestMealPlanningBlueprintsExtractor(unittest.TestCase):
    """Тесты для MealPlanningBlueprintsExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "mealplanningblueprints_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/mealplanningblueprints_com")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MealPlanningBlueprintsExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MealPlanningBlueprintsExtractor(str(html_file))
        result = extractor.extract_all()
        
        self.assertIsInstance(result, dict)
    
    def test_extract_all_has_required_fields(self):
        """Тест что extract_all содержит все обязательные поля"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        required_fields = [
            'dish_name', 'description', 'ingredients', 'instructions',
            'category', 'prep_time', 'cook_time', 'total_time',
            'notes', 'tags', 'image_urls'
        ]
        
        html_file = self.html_files[0]
        extractor = MealPlanningBlueprintsExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Используем файл с полными данными
        html_file = None
        for f in self.html_files:
            if 'sample' in str(f) or 'chocolate' in str(f):
                html_file = f
                break
        
        if not html_file:
            html_file = self.html_files[0]
        
        extractor = MealPlanningBlueprintsExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_description_not_empty(self):
        """Тест что description извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Используем файл с полными данными
        html_file = None
        for f in self.html_files:
            if 'sample' in str(f) or 'chocolate' in str(f):
                html_file = f
                break
        
        if not html_file:
            html_file = self.html_files[0]
        
        extractor = MealPlanningBlueprintsExtractor(str(html_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_parse_ingredient_with_amount_and_unit(self):
        """Тест парсинга ингредиента с количеством и единицей"""
        extractor = MealPlanningBlueprintsExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient("2 tablespoons olive oil")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'olive oil')
        self.assertEqual(result['amount'], '2')
        self.assertEqual(result['unit'], 'tablespoons')
    
    def test_parse_ingredient_with_fraction(self):
        """Тест парсинга ингредиента с дробью"""
        extractor = MealPlanningBlueprintsExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient("1/2 cup sugar")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'sugar')
        self.assertEqual(result['amount'], '0.5')
        self.assertEqual(result['unit'], 'cup')
    
    def test_parse_ingredient_with_mixed_fraction(self):
        """Тест парсинга ингредиента со смешанной дробью"""
        extractor = MealPlanningBlueprintsExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient("1 1/2 cups flour")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'flour')
        self.assertEqual(result['amount'], '1.5')
        self.assertEqual(result['unit'], 'cups')
    
    def test_parse_ingredient_without_amount(self):
        """Тест парсинга ингредиента без количества"""
        extractor = MealPlanningBlueprintsExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient("salt to taste")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'salt')
        self.assertIsNone(result['amount'])
        self.assertIsNone(result['unit'])
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        # Используем файл с данными из JSON-LD
        test_file = None
        for html_file in self.html_files:
            if 'sample' in str(html_file).lower() or 'chocolate' in str(html_file).lower():
                test_file = html_file
                break
        
        if not test_file:
            self.skipTest("No suitable HTML file with ingredients found")
        
        extractor = MealPlanningBlueprintsExtractor(str(test_file))
        ingredients = extractor.extract_ingredients()
        
        if ingredients:
            # Проверяем что это валидный JSON
            parsed = json.loads(ingredients)
            self.assertIsInstance(parsed, list)
            
            # Проверяем структуру первого ингредиента
            if parsed:
                first_ing = parsed[0]
                self.assertIn('name', first_ing)
                self.assertIn('amount', first_ing)
                self.assertIn('unit', first_ing)
    
    def test_all_files_process_without_errors(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = MealPlanningBlueprintsExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
    
    def test_image_urls_format(self):
        """Тест формата image_urls (comma-separated)"""
        # Используем файл с изображениями
        test_file = None
        for html_file in self.html_files:
            if 'sample' in str(html_file).lower() or 'chocolate' in str(html_file).lower():
                test_file = html_file
                break
        
        if not test_file:
            self.skipTest("No suitable HTML file found")
        
        extractor = MealPlanningBlueprintsExtractor(str(test_file))
        image_urls = extractor.extract_image_urls()
        
        if image_urls:
            # Проверяем что это строка
            self.assertIsInstance(image_urls, str)
            # Проверяем что URL разделены запятыми без пробелов
            if ',' in image_urls:
                urls = image_urls.split(',')
                for url in urls:
                    self.assertNotIn(' ', url, "URLs should be comma-separated without spaces")


class TestMealPlanningBlueprintsExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "mealplanningblueprints_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = MealPlanningBlueprintsExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        extractor = MealPlanningBlueprintsExtractor(str(self.html_files[0]))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")
    
    def test_missing_fields_are_none(self):
        """Тест что отсутствующие поля возвращают None"""
        # Используем минимальный файл
        test_file = None
        for html_file in self.html_files:
            if 'minimal' in str(html_file).lower():
                test_file = html_file
                break
        
        if not test_file:
            self.skipTest("No minimal HTML file found")
        
        extractor = MealPlanningBlueprintsExtractor(str(test_file))
        result = extractor.extract_all()
        
        # Проверяем что некоторые поля будут None
        # (категория, время и т.д. отсутствуют в минимальном HTML)
        self.assertIsNone(result['category'])
        self.assertIsNone(result['prep_time'])
        self.assertIsNone(result['cook_time'])
    
    def test_parse_iso_duration(self):
        """Тест парсинга ISO 8601 duration"""
        extractor = MealPlanningBlueprintsExtractor(str(self.html_files[0]))
        
        # Тест различных форматов
        self.assertEqual(extractor.parse_iso_duration("PT15M"), "15 minutes")
        self.assertEqual(extractor.parse_iso_duration("PT1H"), "1 hour")
        self.assertEqual(extractor.parse_iso_duration("PT1H30M"), "1 hour 30 minutes")
        self.assertEqual(extractor.parse_iso_duration("PT2H"), "2 hours")
        self.assertIsNone(extractor.parse_iso_duration("invalid"))
        self.assertIsNone(extractor.parse_iso_duration(None))


if __name__ == '__main__':
    unittest.main()
