"""
Тесты для экстрактора mzss.hr
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.mzss_hr import MzssHrExtractor


class TestMzssHrExtractor(unittest.TestCase):
    """Тесты для MzssHrExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "mzss_hr"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/mzss_hr")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        result = extractor.extract_all()
        
        self.assertIsInstance(result, dict)
    
    def test_extract_all_has_required_fields(self):
        """Тест что extract_all возвращает все обязательные поля"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        required_fields = [
            'dish_name', 'description', 'ingredients', 'instructions',
            'category', 'prep_time', 'cook_time', 'total_time',
            'notes', 'tags', 'image_urls'
        ]
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name(self):
        """Тест извлечения названия блюда"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        # Проверяем что название извлечено
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_ingredients(self):
        """Тест извлечения ингредиентов"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        ingredients = extractor.extract_ingredients()
        
        # Проверяем что ингредиенты извлечены (может быть None если нет в HTML)
        if ingredients:
            self.assertIsInstance(ingredients, str)
            # Проверяем что это валидный JSON
            parsed = json.loads(ingredients)
            self.assertIsInstance(parsed, list)
            # Проверяем структуру первого ингредиента
            if parsed:
                first_ing = parsed[0]
                self.assertIn('name', first_ing)
                self.assertIn('amount', first_ing)
                self.assertIn('units', first_ing)
    
    def test_extract_instructions(self):
        """Тест извлечения инструкций"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        # Проверяем что инструкции извлечены (может быть None если нет в HTML)
        if instructions:
            self.assertIsInstance(instructions, str)
            self.assertGreater(len(instructions), 0)
    
    def test_extract_description(self):
        """Тест извлечения описания"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        description = extractor.extract_description()
        
        # Проверяем что описание извлечено (может быть None если нет в HTML)
        if description:
            self.assertIsInstance(description, str)
            self.assertGreater(len(description), 0)
    
    def test_extract_category(self):
        """Тест извлечения категории"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        category = extractor.extract_category()
        
        # Проверяем что категория извлечена
        if category:
            self.assertIsInstance(category, str)
            self.assertGreater(len(category), 0)
    
    def test_extract_tags(self):
        """Тест извлечения тегов"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        # Проверяем что теги извлечены
        if tags:
            self.assertIsInstance(tags, str)
            # Должны быть разделены запятыми
            self.assertIn(',', tags)
    
    def test_extract_image_urls(self):
        """Тест извлечения URL изображений"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        # Проверяем что URL извлечены
        if image_urls:
            self.assertIsInstance(image_urls, str)
            # Проверяем что это похоже на URL
            self.assertTrue('http' in image_urls.lower())
    
    def test_all_html_files_processable(self):
        """Тест что все HTML файлы можно обработать без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = MzssHrExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем базовую структуру
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('ingredients', result)
                self.assertIn('instructions', result)
    
    def test_ingredient_parsing(self):
        """Тест парсинга отдельных ингредиентов"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = MzssHrExtractor(str(html_file))
        
        # Тестируем различные форматы ингредиентов в хорватском
        test_cases = [
            ("1 velika glavica brokule", {"name": "brokule", "amount": "1", "units": "velika glavica"}),
            ("2 žlice maslinovog ulja", {"name": "maslinovog ulja", "amount": "2", "units": "žlice"}),
            ("3 češnja češnjaka, sitno sjeckana", {"name": "češnjaka", "amount": "3", "units": "češnja"}),
            ("sol i crni papar", {"name": "sol i crni papar", "amount": None, "units": None}),
            ("1/2 šalice ribanog parmezana", {"name": "ribanog parmezana", "amount": "1/2", "units": "šalice"}),
        ]
        
        for input_str, expected in test_cases:
            with self.subTest(input=input_str):
                result = extractor._parse_ingredient_text(input_str)
                self.assertEqual(result['name'], expected['name'], f"Name mismatch for '{input_str}'")
                self.assertEqual(result['amount'], expected['amount'], f"Amount mismatch for '{input_str}'")
                self.assertEqual(result['units'], expected['units'], f"Units mismatch for '{input_str}'")


if __name__ == '__main__':
    unittest.main()
