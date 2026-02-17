"""
Тесты для экстрактора sendeyapsana.com
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.sendeyapsana_com import SendeyapsanaExtractor


class TestSendeyapsanaExtractor(unittest.TestCase):
    """Тесты для SendeyapsanaExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "sendeyapsana_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/sendeyapsana_com")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = SendeyapsanaExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = SendeyapsanaExtractor(str(html_file))
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
        extractor = SendeyapsanaExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name(self):
        """Тест что dish_name извлекается"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Используем файл с JSON-LD данными
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
        self.assertEqual(dish_name, "Starbucks Kurabiye")
    
    def test_extract_description(self):
        """Тест что description извлекается"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_extract_ingredients_structure(self):
        """Тест структуры ингредиентов"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
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
    
    def test_parse_turkish_numbers(self):
        """Тест парсинга турецких числительных (Yarım = 0.5)"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        ingredients = extractor.extract_ingredients()
        
        if ingredients:
            ingredients_list = json.loads(ingredients)
            # Проверяем что "Yarım su bardağı" корректно парсится как 0.5
            half_ingredients = [ing for ing in ingredients_list if ing.get('amount') == '0.5']
            self.assertGreater(len(half_ingredients), 0, "Should have ingredients with amount 0.5 (from Yarım)")
    
    def test_extract_instructions(self):
        """Тест что instructions извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        self.assertIsNotNone(instructions)
        self.assertIsInstance(instructions, str)
        self.assertGreater(len(instructions), 0)
    
    def test_extract_category(self):
        """Тест что category извлекается"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        category = extractor.extract_category()
        
        self.assertIsNotNone(category)
        self.assertIsInstance(category, str)
        self.assertEqual(category, "Kurabiye")
    
    def test_extract_times(self):
        """Тест что времена извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        
        prep_time = extractor.extract_prep_time()
        cook_time = extractor.extract_cook_time()
        total_time = extractor.extract_total_time()
        
        self.assertIsNotNone(prep_time)
        self.assertIsNotNone(cook_time)
        self.assertIsNotNone(total_time)
        
        self.assertEqual(prep_time, "20 minutes")
        self.assertEqual(cook_time, "30 minutes")
        self.assertEqual(total_time, "50 minutes")
    
    def test_parse_iso_duration(self):
        """Тест парсинга ISO 8601 duration"""
        # PT20M -> 20 minutes
        result = SendeyapsanaExtractor.parse_iso_duration("PT20M")
        self.assertEqual(result, "20 minutes")
        
        # PT1H -> 1 hour
        result = SendeyapsanaExtractor.parse_iso_duration("PT1H")
        self.assertEqual(result, "1 hour")
        
        # PT1H30M -> 1 hour 30 minutes
        result = SendeyapsanaExtractor.parse_iso_duration("PT1H30M")
        self.assertEqual(result, "1 hour 30 minutes")
        
        # PT2H -> 2 hours
        result = SendeyapsanaExtractor.parse_iso_duration("PT2H")
        self.assertEqual(result, "2 hours")
        
        # PT50M -> 50 minutes
        result = SendeyapsanaExtractor.parse_iso_duration("PT50M")
        self.assertEqual(result, "50 minutes")
    
    def test_extract_notes(self):
        """Тест что notes извлекаются из секции с пюф-нотами"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        notes = extractor.extract_notes()
        
        self.assertIsNotNone(notes)
        self.assertIsInstance(notes, str)
        self.assertGreater(len(notes), 0)
        # Проверяем что текст содержит советы
        self.assertIn("Tereyağını", notes)
    
    def test_extract_tags(self):
        """Тест что tags извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        self.assertIsNotNone(tags)
        self.assertIsInstance(tags, str)
        # Проверяем формат тегов (через ", ")
        self.assertIn(",", tags)
    
    def test_extract_image_urls(self):
        """Тест что image_urls извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.test_dir / "starbucks-kurabiye-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        self.assertIsNotNone(image_urls)
        self.assertIsInstance(image_urls, str)
        # Проверяем что это URL
        self.assertTrue(image_urls.startswith("http"))
        # Проверяем формат (через запятую без пробелов)
        if "," in image_urls:
            urls = image_urls.split(",")
            for url in urls:
                self.assertTrue(url.startswith("http"))
    
    def test_extract_all_on_all_files(self):
        """Тест extract_all на всех доступных HTML файлах"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = SendeyapsanaExtractor(str(html_file))
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
    
    def test_handles_missing_json_ld(self):
        """Тест что парсер корректно обрабатывает отсутствие JSON-LD данных"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Файл tavada-kirpik-borek не имеет полных JSON-LD данных
        html_file = self.test_dir / "tavada-kirpik-borek-tarifi_1.html"
        if not html_file.exists():
            self.skipTest("Test file not found")
        
        extractor = SendeyapsanaExtractor(str(html_file))
        result = extractor.extract_all()
        
        # Проверяем что парсер не падает и возвращает словарь
        self.assertIsInstance(result, dict)
        
        # Проверяем что все поля присутствуют (могут быть None)
        required_fields = [
            'dish_name', 'description', 'ingredients', 'instructions',
            'category', 'prep_time', 'cook_time', 'total_time',
            'notes', 'tags', 'image_urls'
        ]
        for field in required_fields:
            self.assertIn(field, result)


if __name__ == '__main__':
    unittest.main()
