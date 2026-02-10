"""
Тесты для экстрактора breadflavors.com
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.breadflavors_com import BreadFlavorsExtractor


class TestBreadFlavorsExtractor(unittest.TestCase):
    """Тесты для BreadFlavorsExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "breadflavors_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/breadflavors_com")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BreadFlavorsExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BreadFlavorsExtractor(str(html_file))
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
        extractor = BreadFlavorsExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BreadFlavorsExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_description_not_empty(self):
        """Тест что description извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BreadFlavorsExtractor(str(html_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_extract_category_not_empty(self):
        """Тест что category извлекается и не пустая"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BreadFlavorsExtractor(str(html_file))
        category = extractor.extract_category()
        
        self.assertIsNotNone(category)
        self.assertIsInstance(category, str)
        self.assertGreater(len(category), 0)
    
    def test_extract_tags_not_empty(self):
        """Тест что tags извлекаются и не пустые"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = BreadFlavorsExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        self.assertIsNotNone(tags)
        self.assertIsInstance(tags, str)
        self.assertGreater(len(tags), 0)
        # Проверяем что теги разделены запятой
        self.assertIn(',', tags)
    
    def test_parse_ingredient_with_amount_and_unit(self):
        """Тест парсинга ингредиента с количеством и единицей"""
        extractor = BreadFlavorsExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient("½ cup (100grams) light or dark brown sugar")
        
        self.assertIsNotNone(result)
        self.assertIn('light or dark brown sugar', result['name'].lower())
        self.assertEqual(result['amount'], '½')
        self.assertEqual(result['units'], 'cup')
    
    def test_parse_ingredient_with_compound_amount(self):
        """Тест парсинга ингредиента с составным количеством (1 and ½)"""
        extractor = BreadFlavorsExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient("1 and ½ teaspoon baking powder")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'baking powder')
        self.assertEqual(result['amount'], '1 and ½')
        self.assertEqual(result['units'], 'teaspoon')
    
    def test_parse_ingredient_without_unit(self):
        """Тест парсинга ингредиента без единицы измерения"""
        extractor = BreadFlavorsExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient("2 medium eggs")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'medium eggs')
        self.assertEqual(result['amount'], '2')
        self.assertIsNone(result['units'])
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = BreadFlavorsExtractor(str(html_file))
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
    
    def test_parse_iso_duration(self):
        """Тест парсинга ISO 8601 duration"""
        # PT10M -> 10 minutes
        result = BreadFlavorsExtractor.parse_iso_duration("PT10M")
        self.assertEqual(result, "10 minutes")
        
        # PT1H30M -> 1 hour 30 minutes
        result = BreadFlavorsExtractor.parse_iso_duration("PT1H30M")
        self.assertEqual(result, "1 hour 30 minutes")
        
        # PT65M -> 65 minutes
        result = BreadFlavorsExtractor.parse_iso_duration("PT65M")
        self.assertEqual(result, "65 minutes")
        
        # PT2H -> 2 hours
        result = BreadFlavorsExtractor.parse_iso_duration("PT2H")
        self.assertEqual(result, "2 hours")
    
    def test_extract_time_fields(self):
        """Тест извлечения временных полей"""
        html_file = self.html_files[0]
        extractor = BreadFlavorsExtractor(str(html_file))
        
        prep_time = extractor.extract_prep_time()
        cook_time = extractor.extract_cook_time()
        total_time = extractor.extract_total_time()
        
        # Хотя бы одно поле должно быть заполнено
        self.assertTrue(
            prep_time is not None or cook_time is not None or total_time is not None,
            "At least one time field should be extracted"
        )
    
    def test_extract_image_urls(self):
        """Тест извлечения URL изображений"""
        html_file = self.html_files[0]
        extractor = BreadFlavorsExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        if image_urls:
            self.assertIsInstance(image_urls, str)
            # Проверяем что это валидный URL
            self.assertTrue(
                image_urls.startswith('http://') or image_urls.startswith('https://'),
                "Image URL should start with http:// or https://"
            )
    
    def test_all_files_process_without_errors(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = BreadFlavorsExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)


class TestBreadFlavorsExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "breadflavors_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = BreadFlavorsExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        extractor = BreadFlavorsExtractor(str(self.html_files[0]))
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
