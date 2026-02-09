"""
Тесты для экстрактора beatosvirtuve.lt
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.beatosvirtuve_lt import BeatosvirtuveLtExtractor


class TestBeatosvirtuveLtExtractor(unittest.TestCase):
    """Тесты для BeatosvirtuveLtExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "beatosvirtuve_lt"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/beatosvirtuve_lt")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BeatosvirtuveLtExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BeatosvirtuveLtExtractor(str(html_file))
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
        extractor = BeatosvirtuveLtExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BeatosvirtuveLtExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_description_not_empty(self):
        """Тест что description извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BeatosvirtuveLtExtractor(str(html_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_extract_ingredients_not_empty(self):
        """Тест что ingredients извлекаются и не пустые"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BeatosvirtuveLtExtractor(str(html_file))
        ingredients = extractor.extract_ingredients()
        
        self.assertIsNotNone(ingredients)
        self.assertIsInstance(ingredients, str)
        # Проверяем что это валидный JSON
        parsed = json.loads(ingredients)
        self.assertIsInstance(parsed, list)
        self.assertGreater(len(parsed), 0)
    
    def test_extract_instructions_not_empty(self):
        """Тест что instructions извлекаются и не пустые"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BeatosvirtuveLtExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        self.assertIsNotNone(instructions)
        self.assertIsInstance(instructions, str)
        self.assertGreater(len(instructions), 0)
    
    def test_parse_ingredient_with_amount_and_unit(self):
        """Тест парсинга ингредиента с количеством и единицей"""
        extractor = BeatosvirtuveLtExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_from_text("800 g kiaulienos nugarinės")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'kiaulienos nugarinės')
        self.assertEqual(result['amount'], 800.0)
        self.assertEqual(result['units'], 'g')
    
    def test_parse_ingredient_without_unit(self):
        """Тест парсинга ингредиента без единицы"""
        extractor = BeatosvirtuveLtExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_from_text("2 svogūnų")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'svogūnų')
        self.assertEqual(result['amount'], 2.0)
        self.assertIsNone(result['units'])
    
    def test_parse_ingredient_with_range(self):
        """Тест парсинга ингредиента с диапазоном"""
        extractor = BeatosvirtuveLtExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_from_text("1-1.5 l vandens")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'vandens')
        self.assertEqual(result['amount'], 1.5)  # Берем максимум из диапазона
        self.assertEqual(result['units'], 'liters')
    
    def test_parse_ingredient_removes_parentheses(self):
        """Тест что скобки удаляются при парсинге"""
        extractor = BeatosvirtuveLtExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_from_text("800 g kiaulienos (sprandinė taip pat tinka)")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'kiaulienos')
        self.assertEqual(result['amount'], 800.0)
        self.assertEqual(result['units'], 'g')
    
    def test_parse_iso_duration_minutes(self):
        """Тест парсинга ISO duration только с минутами"""
        extractor = BeatosvirtuveLtExtractor(str(self.html_files[0]))
        
        result = extractor.parse_iso_duration("PT45M")
        
        self.assertEqual(result, "45 minutes")
    
    def test_parse_iso_duration_hours_and_minutes(self):
        """Тест парсинга ISO duration с часами и минутами"""
        extractor = BeatosvirtuveLtExtractor(str(self.html_files[0]))
        
        result = extractor.parse_iso_duration("PT1H30M")
        
        self.assertEqual(result, "1 hours 30 minutes")
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        extractor = BeatosvirtuveLtExtractor(str(self.html_files[0]))
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
                self.assertIn('units', first_ing)
    
    def test_all_files_process_without_errors(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = BeatosvirtuveLtExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
                self.assertIn('instructions', result)


class TestBeatosvirtuveLtExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "beatosvirtuve_lt"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = BeatosvirtuveLtExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        extractor = BeatosvirtuveLtExtractor(str(self.html_files[0]))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")


if __name__ == '__main__':
    unittest.main()
