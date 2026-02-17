"""
Тесты для экстрактора foodhunting.nl
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.foodhunting_nl import FoodhuntingNlExtractor


class TestFoodhuntingNlExtractor(unittest.TestCase):
    """Тесты для FoodhuntingNlExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "foodhunting_nl"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/foodhunting_nl")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodhuntingNlExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodhuntingNlExtractor(str(html_file))
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
        extractor = FoodhuntingNlExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodhuntingNlExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_description_not_empty(self):
        """Тест что description извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodhuntingNlExtractor(str(html_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_extract_ingredients_not_empty(self):
        """Тест что ingredients извлекаются и не пустые"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodhuntingNlExtractor(str(html_file))
        ingredients = extractor.extract_ingredients()
        
        self.assertIsNotNone(ingredients)
        self.assertIsInstance(ingredients, str)
        
        # Проверяем что это валидный JSON
        ingredients_list = json.loads(ingredients)
        self.assertIsInstance(ingredients_list, list)
        self.assertGreater(len(ingredients_list), 0)
        
        # Проверяем структуру первого ингредиента
        first_ingredient = ingredients_list[0]
        self.assertIn('name', first_ingredient)
        self.assertIn('units', first_ingredient)
        self.assertIn('amount', first_ingredient)
    
    def test_extract_instructions_not_empty(self):
        """Тест что instructions извлекаются и не пустые"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodhuntingNlExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        self.assertIsNotNone(instructions)
        self.assertIsInstance(instructions, str)
        self.assertGreater(len(instructions), 0)
    
    def test_extract_category_not_empty(self):
        """Тест что category извлекается"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodhuntingNlExtractor(str(html_file))
        category = extractor.extract_category()
        
        self.assertIsNotNone(category)
        self.assertIsInstance(category, str)
        self.assertGreater(len(category), 0)
    
    def test_extract_times(self):
        """Тест что времена извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodhuntingNlExtractor(str(html_file))
        
        prep_time = extractor.extract_prep_time()
        cook_time = extractor.extract_cook_time()
        total_time = extractor.extract_total_time()
        
        # Хотя бы одно время должно быть извлечено
        times = [prep_time, cook_time, total_time]
        self.assertTrue(any(t is not None for t in times))
    
    def test_parse_iso_duration(self):
        """Тест парсинга ISO 8601 duration"""
        # PT15M -> 15 minutes
        result = FoodhuntingNlExtractor.parse_iso_duration("PT15M")
        self.assertEqual(result, "15 minutes")
        
        # PT1H -> 1 hour
        result = FoodhuntingNlExtractor.parse_iso_duration("PT1H")
        self.assertEqual(result, "1 hour")
        
        # PT1H30M -> 1 hour 30 minutes
        result = FoodhuntingNlExtractor.parse_iso_duration("PT1H30M")
        self.assertEqual(result, "1 hour 30 minutes")
        
        # PT2H -> 2 hours
        result = FoodhuntingNlExtractor.parse_iso_duration("PT2H")
        self.assertEqual(result, "2 hours")
        
        # PT60M -> 1 hour (автоматическая конвертация)
        result = FoodhuntingNlExtractor.parse_iso_duration("PT60M")
        self.assertEqual(result, "1 hour")
        
        # PT100M -> 1 hour 40 minutes (автоматическая конвертация)
        result = FoodhuntingNlExtractor.parse_iso_duration("PT100M")
        self.assertEqual(result, "1 hour 40 minutes")
    
    def test_extract_image_urls(self):
        """Тест что image_urls извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodhuntingNlExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        # Может быть None или строка с URL
        if image_urls is not None:
            self.assertIsInstance(image_urls, str)
            # Проверяем что URL валидный
            self.assertTrue(image_urls.startswith('http'))
    
    def test_extract_all_on_all_files(self):
        """Тест extract_all на всех доступных HTML файлах"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = FoodhuntingNlExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат - словарь
                self.assertIsInstance(result, dict)
                
                # Проверяем наличие всех обязательных полей
                required_fields = [
                    'dish_name', 'description', 'ingredients', 'instructions',
                    'category', 'prep_time', 'cook_time', 'total_time',
                    'notes', 'tags', 'image_urls'
                ]
                for field in required_fields:
                    self.assertIn(field, result, f"Missing field {field} in {html_file.name}")


if __name__ == '__main__':
    unittest.main()
