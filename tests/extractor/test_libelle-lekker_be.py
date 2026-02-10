"""
Тесты для экстрактора libelle-lekker.be
"""

import unittest
import sys
import json
import importlib
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Импортируем модуль с дефисом через importlib
libelle_lekker_module = importlib.import_module('extractor.libelle-lekker_be')
LibelleLekkerExtractor = libelle_lekker_module.LibelleLekkerExtractor


class TestLibelleLekkerExtractor(unittest.TestCase):
    """Тесты для LibelleLekkerExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "libelle-lekker_be"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/libelle-lekker_be")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = LibelleLekkerExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = LibelleLekkerExtractor(str(html_file))
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
        extractor = LibelleLekkerExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = LibelleLekkerExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_category_not_empty(self):
        """Тест что category извлекается и не пустая"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = LibelleLekkerExtractor(str(html_file))
        category = extractor.extract_category()
        
        self.assertIsNotNone(category)
        self.assertIsInstance(category, str)
        self.assertGreater(len(category), 0)
    
    def test_extract_tags_not_empty(self):
        """Тест что tags извлекаются и не пустые"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = LibelleLekkerExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        self.assertIsNotNone(tags)
        self.assertIsInstance(tags, str)
        self.assertGreater(len(tags), 0)
        # Проверяем что теги разделены запятой
        self.assertIn(',', tags)
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = LibelleLekkerExtractor(str(html_file))
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
    
    def test_extract_cook_time_with_hours_and_minutes(self):
        """Тест извлечения времени в формате '1 uur en 20 minuten'"""
        # Найдем файл vacherin (который содержит "1 uur en 20 minuten")
        test_file = None
        for html_file in self.html_files:
            if 'vacherin' in str(html_file).lower():
                test_file = html_file
                break
        
        if not test_file:
            self.skipTest("No vacherin HTML file found")
        
        extractor = LibelleLekkerExtractor(str(test_file))
        cook_time = extractor.extract_cook_time()
        
        self.assertIsNotNone(cook_time)
        self.assertEqual(cook_time, "80 minutes")
    
    def test_all_files_process_without_errors(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = LibelleLekkerExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        extractor = LibelleLekkerExtractor(str(self.html_files[0]))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")
    
    def test_compare_with_expected_json(self):
        """Тест сравнения с эталонными JSON файлами"""
        for html_file in self.html_files:
            # Ищем соответствующий JSON файл
            json_file = html_file.with_suffix('.json')
            if not json_file.exists():
                continue
            
            with self.subTest(file=html_file.name):
                extractor = LibelleLekkerExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Загружаем ожидаемые данные
                with open(json_file, 'r', encoding='utf-8') as f:
                    expected = json.load(f)
                
                # Проверяем основные поля
                self.assertEqual(result['dish_name'], expected.get('dish_name'))
                self.assertEqual(result['category'], expected.get('category'))
                
                # Проверяем количество ингредиентов
                if result.get('ingredients') and expected.get('ingredients'):
                    result_ing = json.loads(result['ingredients'])
                    expected_ing = json.loads(expected['ingredients'])
                    self.assertEqual(len(result_ing), len(expected_ing),
                                   f"Ingredient count mismatch in {html_file.name}")


class TestLibelleLekkerExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "libelle-lekker_be"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = LibelleLekkerExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_rmg_recipe_data_extraction(self):
        """Тест извлечения данных из rmg_recipe_data"""
        extractor = LibelleLekkerExtractor(str(self.html_files[0]))
        
        recipe_data = extractor._get_rmg_recipe_data()
        self.assertIsNotNone(recipe_data)
        self.assertIsInstance(recipe_data, dict)
        
        # Проверяем наличие ожидаемых полей
        self.assertIn('courses', recipe_data)
        self.assertIn('cuisines', recipe_data)
    
    def test_data_attribute_ingredients_extraction(self):
        """Тест извлечения ингредиентов из data-атрибута"""
        extractor = LibelleLekkerExtractor(str(self.html_files[0]))
        
        ingredients = extractor._get_data_attribute_ingredients()
        self.assertIsNotNone(ingredients)
        self.assertIsInstance(ingredients, list)
        self.assertGreater(len(ingredients), 0)
        
        # Проверяем структуру первого ингредиента
        first_ing = ingredients[0]
        self.assertIn('name', first_ing)
        self.assertIn('amount', first_ing)
        self.assertIn('units', first_ing)


if __name__ == '__main__':
    unittest.main()
