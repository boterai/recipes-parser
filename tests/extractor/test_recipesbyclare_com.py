"""
Тесты для экстрактора recipesbyclare.com
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.recipesbyclare_com import RecipesbyclareComExtractor


class TestRecipesbyclareComExtractor(unittest.TestCase):
    """Тесты для RecipesbyclareComExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "recipesbyclare_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/recipesbyclare_com")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
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
        extractor = RecipesbyclareComExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_description_not_empty(self):
        """Тест что description извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_extract_ingredients_format(self):
        """Тест что ingredients возвращается в правильном формате"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        ingredients = extractor.extract_ingredients()
        
        self.assertIsNotNone(ingredients)
        self.assertIsInstance(ingredients, str)
        
        # Должно быть валидным JSON
        ingredients_list = json.loads(ingredients)
        self.assertIsInstance(ingredients_list, list)
        self.assertGreater(len(ingredients_list), 0)
        
        # Каждый ингредиент должен иметь структуру с name, units, amount
        for ingredient in ingredients_list:
            self.assertIsInstance(ingredient, dict)
            self.assertIn('name', ingredient)
            self.assertIn('units', ingredient)
            self.assertIn('amount', ingredient)
    
    def test_extract_instructions_not_empty(self):
        """Тест что instructions извлекаются и не пустые"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        self.assertIsNotNone(instructions)
        self.assertIsInstance(instructions, str)
        self.assertGreater(len(instructions), 0)
    
    def test_extract_category_not_empty(self):
        """Тест что category извлекается и не пустая"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        category = extractor.extract_category()
        
        self.assertIsNotNone(category)
        self.assertIsInstance(category, str)
        self.assertGreater(len(category), 0)
    
    def test_extract_prep_time(self):
        """Тест что prep_time извлекается"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        prep_time = extractor.extract_prep_time()
        
        # Может быть None или строка
        if prep_time is not None:
            self.assertIsInstance(prep_time, str)
            self.assertGreater(len(prep_time), 0)
    
    def test_extract_cook_time(self):
        """Тест что cook_time извлекается"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        cook_time = extractor.extract_cook_time()
        
        # Может быть None или строка
        if cook_time is not None:
            self.assertIsInstance(cook_time, str)
            self.assertGreater(len(cook_time), 0)
    
    def test_extract_notes(self):
        """Тест что notes извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        notes = extractor.extract_notes()
        
        # Может быть None или строка
        if notes is not None:
            self.assertIsInstance(notes, str)
            self.assertGreater(len(notes), 0)
    
    def test_extract_tags(self):
        """Тест что tags извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        # Может быть None или строка
        if tags is not None:
            self.assertIsInstance(tags, str)
            self.assertGreater(len(tags), 0)
    
    def test_extract_image_urls_format(self):
        """Тест что image_urls возвращается в правильном формате"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = RecipesbyclareComExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        # Может быть None или строка с URL
        if image_urls is not None:
            self.assertIsInstance(image_urls, str)
            # Если есть URL, они должны быть разделены запятыми
            urls = image_urls.split(',')
            for url in urls:
                self.assertTrue(url.startswith('http'), f"Invalid URL: {url}")
    
    def test_parse_iso_duration(self):
        """Тест парсинга ISO 8601 duration"""
        extractor_class = RecipesbyclareComExtractor
        
        # Тесты различных форматов
        self.assertEqual(extractor_class.parse_iso_duration('PT30M'), '30 minutes')
        self.assertEqual(extractor_class.parse_iso_duration('PT1H'), '1 hour')
        self.assertEqual(extractor_class.parse_iso_duration('PT1H30M'), '1 hour 30 minutes')
        self.assertEqual(extractor_class.parse_iso_duration('PT2H'), '2 hours')
        self.assertEqual(extractor_class.parse_iso_duration('PT15M'), '15 minutes')
        self.assertEqual(extractor_class.parse_iso_duration('PT50M'), '50 minutes')
        self.assertEqual(extractor_class.parse_iso_duration('PT10M'), '10 minutes')
        self.assertEqual(extractor_class.parse_iso_duration('PT60M'), '1 hour')
        self.assertIsNone(extractor_class.parse_iso_duration(''))
        self.assertIsNone(extractor_class.parse_iso_duration(None))
    
    def test_all_html_files_processable(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                extractor = RecipesbyclareComExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что вернулся словарь со всеми полями
                self.assertIsInstance(result, dict)
                required_fields = [
                    'dish_name', 'description', 'ingredients', 'instructions',
                    'category', 'prep_time', 'cook_time', 'total_time',
                    'notes', 'tags', 'image_urls'
                ]
                for field in required_fields:
                    self.assertIn(field, result)


if __name__ == '__main__':
    unittest.main()
