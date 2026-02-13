"""
Тесты для экстрактора godare.se
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.godare_se import GodareSeExtractor


class TestGodareSeExtractor(unittest.TestCase):
    """Тесты для GodareSeExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "godare_se"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/godare_se")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = GodareSeExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = GodareSeExtractor(str(html_file))
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
        extractor = GodareSeExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name(self):
        """Тест извлечения названия блюда"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = GodareSeExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        # Проверяем что название не пустое
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_ingredients(self):
        """Тест извлечения ингредиентов"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = GodareSeExtractor(str(html_file))
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
                self.assertIn('unit', first_ing)
    
    def test_extract_instructions(self):
        """Тест извлечения инструкций"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = GodareSeExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        # Проверяем что инструкции извлечены
        if instructions:
            self.assertIsInstance(instructions, str)
            self.assertGreater(len(instructions), 0)
    
    def test_extract_category(self):
        """Тест извлечения категории"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = GodareSeExtractor(str(html_file))
        category = extractor.extract_category()
        
        # Категория должна быть "Main Course" согласно требованиям
        self.assertEqual(category, "Main Course")
    
    def test_extract_image_urls(self):
        """Тест извлечения URL изображений"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = GodareSeExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        # Проверяем что URL извлечены
        if image_urls:
            self.assertIsInstance(image_urls, str)
            # Проверяем что это похоже на URL
            self.assertTrue(image_urls.startswith('http'))
    
    def test_all_html_files_processable(self):
        """Тест что все HTML файлы можно обработать без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = GodareSeExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем базовую структуру
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('ingredients', result)
                self.assertIn('instructions', result)


if __name__ == '__main__':
    unittest.main()
