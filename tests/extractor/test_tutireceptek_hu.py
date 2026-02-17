"""
Тесты для экстрактора tutireceptek.hu
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.tutireceptek_hu import TutireceptekExtractor


class TestTutireceptekExtractor(unittest.TestCase):
    """Тесты для TutireceptekExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "tutireceptek_hu"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/tutireceptek_hu")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = TutireceptekExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = TutireceptekExtractor(str(html_file))
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
        extractor = TutireceptekExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = TutireceptekExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_category_not_empty(self):
        """Тест что category извлекается и не пустая"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = TutireceptekExtractor(str(html_file))
        category = extractor.extract_category()
        
        self.assertIsNotNone(category)
        self.assertIsInstance(category, str)
        self.assertGreater(len(category), 0)
    
    def test_parse_ingredient_with_amount_and_unit(self):
        """Тест парсинга ингредиента с количеством и единицей"""
        extractor = TutireceptekExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_line("20 dkg burgonya")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'burgonya')
        self.assertEqual(result['amount'], '20')
        self.assertEqual(result['unit'], 'dkg')
    
    def test_parse_ingredient_with_fej(self):
        """Тест парсинга ингредиента с единицей 'fej'"""
        extractor = TutireceptekExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_line("1 fej vöröshagyma")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'vöröshagyma')
        self.assertEqual(result['amount'], '1')
        self.assertEqual(result['unit'], 'fej')
    
    def test_parse_ingredient_without_space(self):
        """Тест парсинга ингредиента без пробела между числом и единицей"""
        extractor = TutireceptekExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_line("30dkg búzaliszt")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'búzaliszt')
        self.assertEqual(result['amount'], '30')
        self.assertEqual(result['unit'], 'dkg')
    
    def test_parse_ingredient_with_fel(self):
        """Тест парсинга ингредиента с 'fél'"""
        extractor = TutireceptekExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_line("fél kávéskanál só")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'só')
        self.assertEqual(result['amount'], '0.5')
        self.assertEqual(result['unit'], 'kávéskanál')
    
    def test_parse_ingredient_without_amount(self):
        """Тест парсинга ингредиента без количества"""
        extractor = TutireceptekExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_line("friss majoranna")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'majoranna')
        self.assertIsNone(result['amount'])
        self.assertEqual(result['unit'], 'friss')
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        html_file = self.html_files[0]
        extractor = TutireceptekExtractor(str(html_file))
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
    
    def test_extract_instructions_not_empty(self):
        """Тест что instructions извлекаются и не пустые"""
        html_file = self.html_files[0]
        extractor = TutireceptekExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        self.assertIsNotNone(instructions)
        self.assertIsInstance(instructions, str)
        self.assertGreater(len(instructions), 0)
    
    def test_all_files_process_without_errors(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = TutireceptekExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
                self.assertIn('instructions', result)
                self.assertIn('category', result)


class TestTutireceptekExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "tutireceptek_hu"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = TutireceptekExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        extractor = TutireceptekExtractor(str(self.html_files[0]))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")
    
    def test_parse_ingredient_removes_parentheses(self):
        """Тест что parse_ingredient удаляет скобки"""
        extractor = TutireceptekExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_line("10 dkg bambuszrügy (elhagyható)")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'bambuszrügy')
        self.assertNotIn('elhagyható', result['name'])
        self.assertNotIn('(', result['name'])


if __name__ == '__main__':
    unittest.main()
