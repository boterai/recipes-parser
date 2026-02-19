"""
Тесты для экстрактора chefexperto.com
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.chefexperto_com import ChefExpertoExtractor


class TestChefExpertoExtractor(unittest.TestCase):
    """Тесты для ChefExpertoExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "chefexperto_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/chefexperto_com")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ChefExpertoExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ChefExpertoExtractor(str(html_file))
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
        extractor = ChefExpertoExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name(self):
        """Тест что dish_name извлекается"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Test with tortilla file
        tortilla_file = self.test_dir / "espana_receta-de-tortilla-de-patatas_1.html"
        if tortilla_file.exists():
            extractor = ChefExpertoExtractor(str(tortilla_file))
            dish_name = extractor.extract_dish_name()
            
            self.assertIsNotNone(dish_name)
            self.assertIsInstance(dish_name, str)
            self.assertEqual(dish_name, "Tortilla de Patatas")
    
    def test_extract_ingredients_tortilla(self):
        """Тест что ingredients извлекаются для tortilla"""
        tortilla_file = self.test_dir / "espana_receta-de-tortilla-de-patatas_1.html"
        if not tortilla_file.exists():
            self.skipTest("Tortilla HTML file not found")
        
        extractor = ChefExpertoExtractor(str(tortilla_file))
        ingredients = extractor.extract_ingredients()
        
        self.assertIsNotNone(ingredients)
        self.assertIsInstance(ingredients, str)
        
        # Проверяем что это валидный JSON
        parsed = json.loads(ingredients)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 5)
        
        # Проверяем что все ингредиенты есть
        ingredient_names = [ing['name'] for ing in parsed]
        expected_names = ['Patatas', 'Huevos', 'Cebolla', 'Aceite de oliva', 'Sal']
        for name in expected_names:
            self.assertIn(name, ingredient_names)
    
    def test_extract_ingredients_sopa(self):
        """Тест что ingredients извлекаются для sopa"""
        sopa_file = self.test_dir / "espana_receta-de-sopa-castellana_1.html"
        if not sopa_file.exists():
            self.skipTest("Sopa HTML file not found")
        
        extractor = ChefExpertoExtractor(str(sopa_file))
        ingredients = extractor.extract_ingredients()
        
        self.assertIsNotNone(ingredients)
        self.assertIsInstance(ingredients, str)
        
        # Проверяем что это валидный JSON
        parsed = json.loads(ingredients)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 7)
        
        # Проверяем основные ингредиенты
        ingredient_names = [ing['name'] for ing in parsed]
        self.assertIn('Pan', ingredient_names)
        self.assertIn('Ajo', ingredient_names)
        self.assertIn('Pimentón', ingredient_names)
    
    def test_extract_instructions(self):
        """Тест что instructions извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ChefExpertoExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        # Instructions могут быть None для некоторых файлов
        if instructions:
            self.assertIsInstance(instructions, str)
            self.assertGreater(len(instructions), 0)
    
    def test_extract_category(self):
        """Тест что category извлекается"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ChefExpertoExtractor(str(html_file))
        category = extractor.extract_category()
        
        self.assertIsNotNone(category)
        self.assertEqual(category, "Main Course")
    
    def test_extract_tags(self):
        """Тест что tags извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ChefExpertoExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        # Tags могут быть None или строкой
        if tags:
            self.assertIsInstance(tags, str)
            self.assertIn(',', tags)  # Теги разделены запятыми
    
    def test_extract_image_urls(self):
        """Тест что image_urls извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ChefExpertoExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        # Image URLs должны быть
        if image_urls:
            self.assertIsInstance(image_urls, str)
            # Проверяем что это валидные URL
            urls = image_urls.split(',')
            for url in urls:
                self.assertTrue(url.startswith('http'))
    
    def test_parse_ingredient(self):
        """Тест парсинга ингредиента"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        extractor = ChefExpertoExtractor(str(self.html_files[0]))
        
        # Тест с двоеточием
        result = extractor.parse_ingredient("Patatas: Opta por patatas de calidad")
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'Patatas')
        self.assertIsNone(result['amount'])
        self.assertIsNone(result['units'])
        
        # Тест без двоеточия
        result = extractor.parse_ingredient("Huevos frescos")
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'Huevos frescos')
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        tortilla_file = self.test_dir / "espana_receta-de-tortilla-de-patatas_1.html"
        if not tortilla_file.exists():
            self.skipTest("Tortilla HTML file not found")
        
        extractor = ChefExpertoExtractor(str(tortilla_file))
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
                extractor = ChefExpertoExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
                self.assertIn('instructions', result)
                self.assertIn('category', result)


class TestChefExpertoExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "chefexperto_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = ChefExpertoExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        extractor = ChefExpertoExtractor(str(self.html_files[0]))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")
    
    def test_ingredients_no_duplicates(self):
        """Тест что ингредиенты не дублируются"""
        tortilla_file = self.test_dir / "espana_receta-de-tortilla-de-patatas_1.html"
        if not tortilla_file.exists():
            self.skipTest("Tortilla HTML file not found")
        
        extractor = ChefExpertoExtractor(str(tortilla_file))
        ingredients = extractor.extract_ingredients()
        
        if ingredients:
            parsed = json.loads(ingredients)
            names = [ing['name'] for ing in parsed]
            # Проверяем что нет дубликатов
            self.assertEqual(len(names), len(set(names)))


if __name__ == '__main__':
    unittest.main()
