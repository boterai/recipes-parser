"""
Тесты для экстрактора hellotaste.ro
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.hellotaste_ro import HellotasteRoExtractor


class TestHellotasteRoExtractor(unittest.TestCase):
    """Тесты для HellotasteRoExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "hellotaste_ro"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/hellotaste_ro")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
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
        extractor = HellotasteRoExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name(self):
        """Тест извлечения названия блюда"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        # Проверяем что название не пустое
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
        # Проверяем что подзаголовок был удален (не должно быть точки в конце основного названия)
        self.assertNotIn('. ', dish_name, "Dish name should not contain subtitle after period")
    
    def test_extract_description(self):
        """Тест извлечения описания"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        description = extractor.extract_description()
        
        # Описание может быть None, но если есть - должно быть строкой
        if description is not None:
            self.assertIsInstance(description, str)
            self.assertGreater(len(description), 0)
    
    def test_extract_ingredients(self):
        """Тест извлечения ингредиентов"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        ingredients = extractor.extract_ingredients()
        
        # Проверяем что ингредиенты извлечены
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
                self.assertIn('units', first_ing)  # Note: "units" not "unit"
    
    def test_extract_instructions(self):
        """Тест извлечения инструкций"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        # Проверяем что инструкции извлечены
        if instructions:
            self.assertIsInstance(instructions, str)
            self.assertGreater(len(instructions), 0)
            # Проверяем что нет рекламных фраз
            self.assertNotIn('Descoperă și', instructions)
            self.assertNotIn('îți recomandăm', instructions)
    
    def test_extract_category(self):
        """Тест извлечения категории"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        category = extractor.extract_category()
        
        # Категория должна быть извлечена
        if category is not None:
            self.assertIsInstance(category, str)
            self.assertGreater(len(category), 0)
    
    def test_extract_cook_time(self):
        """Тест извлечения времени приготовления"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        cook_time = extractor.extract_cook_time()
        
        # Время приготовления должно быть извлечено и содержать "minutes"
        if cook_time:
            self.assertIsInstance(cook_time, str)
            self.assertIn('minutes', cook_time.lower())
    
    def test_extract_notes(self):
        """Тест извлечения заметок"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        notes = extractor.extract_notes()
        
        # Заметки могут быть None, но если есть - должны быть строкой
        if notes is not None:
            self.assertIsInstance(notes, str)
            self.assertGreater(len(notes), 0)
    
    def test_extract_tags(self):
        """Тест извлечения тегов"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        # Теги могут быть None, но если есть - должны быть строкой с запятыми без пробелов
        if tags:
            self.assertIsInstance(tags, str)
            # Проверяем формат: теги через запятую без пробелов после запятых
            if ',' in tags:
                parts = tags.split(',')
                for part in parts:
                    # Первая часть не должна начинаться с пробела, остальные - не должны
                    if parts.index(part) > 0:
                        self.assertFalse(part.startswith(' '), "Tags should not have spaces after commas")
    
    def test_extract_image_urls(self):
        """Тест извлечения URL изображений"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        # Проверяем что URL извлечены
        if image_urls:
            self.assertIsInstance(image_urls, str)
            # Проверяем что это похоже на URL
            self.assertTrue(image_urls.startswith('http'))
            # Проверяем формат: URLs через запятую без пробелов
            if ',' in image_urls:
                urls = image_urls.split(',')
                for url in urls:
                    self.assertTrue(url.startswith('http'), "Each URL should be valid")
    
    def test_all_html_files_processable(self):
        """Тест что все HTML файлы можно обработать без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = HellotasteRoExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем базовую структуру
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('ingredients', result)
                self.assertIn('instructions', result)
    
    def test_parse_ingredient(self):
        """Тест парсинга отдельного ингредиента"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = HellotasteRoExtractor(str(html_file))
        
        # Тест различных форматов ингредиентов
        test_cases = [
            ("500 g făină albă", {"name": "făină albă", "amount": 500, "units": "g"}),
            ("1 linguriță extract de vanilie", {"name": "extract de vanilie", "amount": 1, "units": "linguriță"}),
            ("sare", {"name": "sare", "amount": None, "units": None}),
        ]
        
        for ingredient_text, expected in test_cases:
            with self.subTest(ingredient=ingredient_text):
                result = extractor.parse_ingredient(ingredient_text)
                self.assertEqual(result['name'], expected['name'])
                self.assertEqual(result['amount'], expected['amount'])
                self.assertEqual(result['units'], expected['units'])


if __name__ == '__main__':
    unittest.main()
