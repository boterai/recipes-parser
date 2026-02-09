"""
Тесты для экстрактора domacica.com (domacica_com_hr)
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.domacica_com_hr import DomacicaComHrExtractor


class TestDomacicaComHrExtractor(unittest.TestCase):
    """Тесты для DomacicaComHrExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "domacica_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/domacica_com")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = DomacicaComHrExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = DomacicaComHrExtractor(str(html_file))
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
        extractor = DomacicaComHrExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = DomacicaComHrExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_description_not_empty(self):
        """Тест что description извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = DomacicaComHrExtractor(str(html_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_extract_category_not_empty(self):
        """Тест что category извлекается и не пустая"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = DomacicaComHrExtractor(str(html_file))
        category = extractor.extract_category()
        
        self.assertIsNotNone(category)
        self.assertIsInstance(category, str)
        self.assertGreater(len(category), 0)
    
    def test_extract_tags_not_empty(self):
        """Тест что tags извлекаются и не пустые"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = DomacicaComHrExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        self.assertIsNotNone(tags)
        self.assertIsInstance(tags, str)
        self.assertGreater(len(tags), 0)
        # Проверяем что теги разделены запятой
        self.assertIn(',', tags)
    
    def test_parse_ingredient_with_amount_and_unit(self):
        """Тест парсинга ингредиента с количеством и единицей"""
        extractor = DomacicaComHrExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_text("500 gr tikve")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'tikve')
        self.assertEqual(result['amount'], 500)
        self.assertEqual(result['units'], 'gr')
    
    def test_parse_ingredient_with_fraction(self):
        """Тест парсинга ингредиента с дробью"""
        extractor = DomacicaComHrExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_text("½ kašičice sušenog mažurana")
        
        self.assertIsNotNone(result)
        self.assertIsNotNone(result['amount'])
        self.assertEqual(result['units'], 'kašičice')
    
    def test_parse_ingredient_without_amount(self):
        """Тест парсинга ингредиента без количества"""
        extractor = DomacicaComHrExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_text("maslinovo ulje")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'maslinovo ulje')
        self.assertIsNone(result['amount'])
        self.assertIsNone(result['units'])
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        html_file = self.html_files[0]
        extractor = DomacicaComHrExtractor(str(html_file))
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
                extractor = DomacicaComHrExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
    
    def test_iso_duration_parsing(self):
        """Тест парсинга ISO 8601 duration"""
        # Только минуты
        result = DomacicaComHrExtractor.parse_iso_duration("PT10M")
        self.assertEqual(result, "10 min")
        
        # Только часы
        result = DomacicaComHrExtractor.parse_iso_duration("PT1H")
        self.assertEqual(result, "1 hour")
        
        # Часы и минуты
        result = DomacicaComHrExtractor.parse_iso_duration("PT1H30M")
        self.assertEqual(result, "1 h 30 min")
    
    def test_extract_image_urls(self):
        """Тест извлечения URL изображений"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = DomacicaComHrExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        if image_urls:
            # Проверяем что это строка с URL
            self.assertIsInstance(image_urls, str)
            # URL должны начинаться с http
            self.assertTrue(image_urls.startswith('http'))
            # Если несколько URL, они разделены запятой
            if ',' in image_urls:
                urls = image_urls.split(',')
                for url in urls:
                    self.assertTrue(url.strip().startswith('http'))


class TestDomacicaComHrExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "domacica_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = DomacicaComHrExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        extractor = DomacicaComHrExtractor(str(self.html_files[0]))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")
    
    def test_ingredient_splitting_on_comma(self):
        """Тест что ингредиенты разделяются по запятой когда нет цифр"""
        extractor = DomacicaComHrExtractor(str(self.html_files[0]))
        
        # Используем тестовый HTML с "so, biber"
        ingredients = extractor.extract_ingredients()
        if ingredients:
            parsed = json.loads(ingredients)
            # Ищем "so" и "biber" как отдельные ингредиенты
            ingredient_names = [ing['name'] for ing in parsed]
            has_salt = any('so' in name.lower() for name in ingredient_names)
            self.assertTrue(has_salt, "Should have 'so' or 'So' in ingredients")


if __name__ == '__main__':
    unittest.main()
