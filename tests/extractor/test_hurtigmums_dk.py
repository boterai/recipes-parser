"""
Тесты для экстрактора hurtigmums.dk
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.hurtigmums_dk import HurtigmumsDkExtractor


class TestHurtigmumsDkExtractor(unittest.TestCase):
    """Тесты для HurtigmumsDkExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "hurtigmums_dk"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/hurtigmums_dk")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HurtigmumsDkExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HurtigmumsDkExtractor(str(html_file))
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
        extractor = HurtigmumsDkExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Используем burger_1.html так как мы знаем что там есть данные
        html_file = self.test_dir / "burger_1.html"
        if not html_file.exists():
            html_file = self.html_files[0]
        
        extractor = HurtigmumsDkExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_description_not_empty(self):
        """Тест что description извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "burger_1.html"
        if not html_file.exists():
            html_file = self.html_files[0]
        
        extractor = HurtigmumsDkExtractor(str(html_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        for html_file in self.html_files:
            # Пропускаем print файлы, они могут иметь другую структуру
            if 'print' in html_file.name:
                continue
                
            with self.subTest(file=html_file.name):
                extractor = HurtigmumsDkExtractor(str(html_file))
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
        extractor = HurtigmumsDkExtractor(str(self.html_files[0]))
        
        # PT10M -> 10 minutes
        result = extractor.parse_iso_duration("PT10M")
        self.assertEqual(result, "10 minutes")
        
        # PT1H30M -> 1 hour 30 minutes
        result = extractor.parse_iso_duration("PT1H30M")
        self.assertEqual(result, "1 hour 30 minutes")
        
        # PT20M -> 20 minutes
        result = extractor.parse_iso_duration("PT20M")
        self.assertEqual(result, "20 minutes")
        
        # PT2H -> 2 hours
        result = extractor.parse_iso_duration("PT2H")
        self.assertEqual(result, "2 hours")
    
    def test_extract_time_fields(self):
        """Тест извлечения временных полей"""
        html_file = self.test_dir / "burger_1.html"
        if not html_file.exists():
            html_file = self.html_files[0]
        
        extractor = HurtigmumsDkExtractor(str(html_file))
        
        prep_time = extractor.extract_prep_time()
        total_time = extractor.extract_total_time()
        
        # Для burger должны быть prep_time и total_time
        if 'burger' in str(html_file):
            self.assertIsNotNone(prep_time)
            self.assertIsNotNone(total_time)
    
    def test_extract_image_urls(self):
        """Тест извлечения URL изображений"""
        html_file = self.test_dir / "burger_1.html"
        if not html_file.exists():
            html_file = self.html_files[0]
        
        extractor = HurtigmumsDkExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        if image_urls:
            self.assertIsInstance(image_urls, str)
            # Должно быть несколько URL через запятую
            urls = image_urls.split(',')
            for url in urls:
                self.assertTrue(
                    url.startswith('http://') or url.startswith('https://'),
                    f"Image URL should start with http:// or https://, got: {url}"
                )
    
    def test_extract_tags_format(self):
        """Тест формата тегов"""
        html_file = self.test_dir / "burger_1.html"
        if not html_file.exists():
            html_file = self.html_files[0]
        
        extractor = HurtigmumsDkExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        if tags:
            self.assertIsInstance(tags, str)
            # Теги должны быть разделены запятой с пробелом
            if ',' in tags:
                self.assertIn(', ', tags)
    
    def test_all_files_process_without_errors(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = HurtigmumsDkExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
    
    def test_extract_json_ld_recipe(self):
        """Тест извлечения Recipe из JSON-LD"""
        html_file = self.test_dir / "burger_1.html"
        if not html_file.exists():
            html_file = self.html_files[0]
        
        extractor = HurtigmumsDkExtractor(str(html_file))
        recipe_data = extractor.extract_json_ld_recipe()
        
        self.assertIsNotNone(recipe_data)
        self.assertIsInstance(recipe_data, dict)
        self.assertEqual(recipe_data.get('@type'), 'Recipe')


class TestHurtigmumsDkExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "hurtigmums_dk"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = HurtigmumsDkExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        extractor = HurtigmumsDkExtractor(str(self.html_files[0]))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")
    
    def test_dish_name_simplified(self):
        """Тест что dish_name упрощается корректно"""
        html_file = self.test_dir / "burger_1.html"
        if not html_file.exists():
            self.skipTest("burger_1.html not found")
        
        extractor = HurtigmumsDkExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        # Должно быть просто "Burger", а не "Traditionel burger opskrift"
        self.assertEqual(dish_name, "Burger")
    
    def test_ingredients_from_first_group_only(self):
        """Тест что извлекаются только ингредиенты из первой группы"""
        html_file = self.test_dir / "burger_1.html"
        if not html_file.exists():
            self.skipTest("burger_1.html not found")
        
        extractor = HurtigmumsDkExtractor(str(html_file))
        ingredients = extractor.extract_ingredients()
        
        if ingredients:
            parsed = json.loads(ingredients)
            # В burger_1 должно быть около 12-13 ингредиентов в первой группе
            # А не 32+ (которые включают ингредиенты для булочек)
            self.assertLess(len(parsed), 20,
                          "Should extract only from first ingredient group")


if __name__ == '__main__':
    unittest.main()
