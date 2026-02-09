"""
Тесты для экстрактора food.ndtv.com
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.food_ndtv_com import FoodNdtvComExtractor


class TestFoodNdtvComExtractor(unittest.TestCase):
    """Тесты для FoodNdtvComExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "food_ndtv_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/food_ndtv_com")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodNdtvComExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = FoodNdtvComExtractor(str(html_file))
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
        extractor = FoodNdtvComExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Используем test_recipe.html для проверки
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
        self.assertEqual(dish_name, "Pav Bhaji")
    
    def test_extract_description_not_empty(self):
        """Тест что description извлекается и не пустое"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_extract_category(self):
        """Тест что category извлекается корректно"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        category = extractor.extract_category()
        
        self.assertIsNotNone(category)
        self.assertIsInstance(category, str)
        self.assertGreater(len(category), 0)
    
    def test_extract_tags(self):
        """Тест что tags извлекаются корректно"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        tags = extractor.extract_tags()
        
        self.assertIsNotNone(tags)
        self.assertIsInstance(tags, str)
        self.assertGreater(len(tags), 0)
        # Проверяем что теги разделены запятой
        self.assertIn(',', tags)
    
    def test_parse_ingredient_with_amount_and_unit(self):
        """Тест парсинга ингредиента с количеством и единицей"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        
        result = extractor.parse_ingredient("2 cups flour")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'flour')
        self.assertEqual(result['amount'], '2')
        self.assertEqual(result['unit'], 'cups')
    
    def test_parse_ingredient_without_amount(self):
        """Тест парсинга ингредиента без количества"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        
        result = extractor.parse_ingredient("salt to taste")
        
        self.assertIsNotNone(result)
        self.assertIn('salt', result['name'].lower())
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        ingredients = extractor.extract_ingredients()
        
        if ingredients:
            self.assertIsInstance(ingredients, list)
            
            # Проверяем структуру первого ингредиента
            if ingredients:
                first_ing = ingredients[0]
                self.assertIn('name', first_ing)
                self.assertIn('amount', first_ing)
                self.assertIn('unit', first_ing)
    
    def test_extract_all_ingredients_as_json_string(self):
        """Тест что в extract_all ингредиенты возвращаются как JSON строка"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        result = extractor.extract_all()
        
        if result['ingredients']:
            # Проверяем что это JSON строка
            self.assertIsInstance(result['ingredients'], str)
            
            # Парсим JSON
            parsed = json.loads(result['ingredients'])
            self.assertIsInstance(parsed, list)
            
            # Проверяем структуру
            if parsed:
                first_ing = parsed[0]
                self.assertIn('name', first_ing)
                self.assertIn('amount', first_ing)
                self.assertIn('unit', first_ing)
    
    def test_extract_time_fields(self):
        """Тест что поля времени извлекаются корректно"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        
        prep_time = extractor.extract_prep_time()
        cook_time = extractor.extract_cook_time()
        total_time = extractor.extract_total_time()
        
        # Проверяем что хотя бы одно из полей времени заполнено
        self.assertTrue(
            prep_time is not None or cook_time is not None or total_time is not None,
            "At least one time field should be extracted"
        )
    
    def test_extract_image_urls(self):
        """Тест что image_urls извлекаются корректно"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        image_urls = extractor.extract_image_urls()
        
        self.assertIsNotNone(image_urls)
        self.assertIsInstance(image_urls, str)
        # Проверяем что это похоже на URL
        self.assertTrue(
            'http' in image_urls.lower() or 'https' in image_urls.lower(),
            "Image URLs should contain http or https"
        )
    
    def test_all_files_process_without_errors(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = FoodNdtvComExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
    
    def test_html_only_extraction(self):
        """Тест извлечения данных только из HTML (без JSON-LD)"""
        test_file = self.test_dir / "test_recipe_html_only.html"
        if not test_file.exists():
            self.skipTest("test_recipe_html_only.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        result = extractor.extract_all()
        
        # Проверяем что хотя бы dish_name извлечено
        self.assertIsNotNone(result['dish_name'])
        self.assertGreater(len(result['dish_name']), 0)
    
    def test_minimal_html_handling(self):
        """Тест обработки минимального HTML с отсутствующими данными"""
        test_file = self.test_dir / "test_minimal.html"
        if not test_file.exists():
            self.skipTest("test_minimal.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        result = extractor.extract_all()
        
        # Проверяем что все поля присутствуют
        required_fields = [
            'dish_name', 'description', 'ingredients', 'instructions',
            'category', 'prep_time', 'cook_time', 'total_time',
            'notes', 'tags', 'image_urls'
        ]
        
        for field in required_fields:
            self.assertIn(field, result, f"Field {field} should be present even if None")


class TestFoodNdtvComExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "food_ndtv_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")
    
    def test_parse_iso_duration(self):
        """Тест парсинга ISO 8601 duration"""
        test_file = self.test_dir / "test_recipe.html"
        if not test_file.exists():
            self.skipTest("test_recipe.html not found")
        
        extractor = FoodNdtvComExtractor(str(test_file))
        
        # Тестируем различные форматы
        self.assertEqual(extractor.parse_iso_duration("PT15M"), "15 minutes")
        self.assertEqual(extractor.parse_iso_duration("PT1H"), "1 hour")
        self.assertEqual(extractor.parse_iso_duration("PT1H30M"), "1 hour 30 minutes")
        self.assertEqual(extractor.parse_iso_duration("PT2H"), "2 hours")
        self.assertIsNone(extractor.parse_iso_duration("Invalid"))
        self.assertIsNone(extractor.parse_iso_duration(None))


if __name__ == '__main__':
    unittest.main()
