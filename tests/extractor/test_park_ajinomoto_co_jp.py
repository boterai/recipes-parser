"""
Тесты для экстрактора park.ajinomoto.co.jp
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.park_ajinomoto_co_jp import ParkAjinomotoCoJpExtractor


class TestParkAjinomotoCoJpExtractor(unittest.TestCase):
    """Тесты для ParkAjinomotoCoJpExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "park_ajinomoto_co_jp"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/park_ajinomoto_co_jp")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
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
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_description_not_empty(self):
        """Тест что description извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        description = extractor.extract_description()
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)
    
    def test_extract_category(self):
        """Тест что category извлекается"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Находим файл с категорией (не print версию)
        non_print_files = [f for f in self.html_files if 'print' not in f.name]
        if not non_print_files:
            self.skipTest("No non-print files available")
        
        html_file = non_print_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        category = extractor.extract_category()
        
        # Может быть None для print версий
        if category:
            self.assertIsInstance(category, str)
            self.assertGreater(len(category), 0)
    
    def test_extract_tags(self):
        """Тест что tags извлекаются"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Находим файл с тегами (не print версию)
        non_print_files = [f for f in self.html_files if 'print' not in f.name]
        if not non_print_files:
            self.skipTest("No non-print files available")
        
        html_file = non_print_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        tags = extractor.extract_tags()
        
        # Может быть None для print версий
        if tags:
            self.assertIsInstance(tags, str)
            self.assertGreater(len(tags), 0)
            # Проверяем что теги разделены запятой
            self.assertIn(',', tags)
    
    def test_parse_ingredient_text(self):
        """Тест парсинга текста ингредиента"""
        extractor = ParkAjinomotoCoJpExtractor(str(self.html_files[0]))
        
        # Тест на японском с количеством и единицей
        result = extractor.parse_ingredient_text("ごぼう 1本（150g）")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'ごぼう')
        self.assertEqual(result['amount'], '1')
        self.assertEqual(result['unit'], '本（150g）')
    
    def test_parse_ingredient_text_with_tablespoon(self):
        """Тест парсинга ингредиента с большой ложкой"""
        extractor = ParkAjinomotoCoJpExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_text("片栗粉 大さじ1")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], '片栗粉')
        self.assertEqual(result['amount'], '1')
        self.assertEqual(result['unit'], '大さじ')
    
    def test_parse_ingredient_text_with_text_amount(self):
        """Тест парсинга ингредиента с текстовым количеством"""
        extractor = ParkAjinomotoCoJpExtractor(str(self.html_files[0]))
        
        result = extractor.parse_ingredient_text("塩 少々")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], '塩')
        self.assertEqual(result['amount'], '少々')
        self.assertIsNone(result['unit'])
    
    def test_ingredients_format_is_json_string(self):
        """Тест что ingredients возвращаются в виде JSON строки"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = ParkAjinomotoCoJpExtractor(str(html_file))
                ingredients = extractor.extract_ingredients()
                
                # Должны быть ингредиенты во всех файлах
                self.assertIsNotNone(ingredients)
                
                if ingredients:
                    # Проверяем что это валидный JSON
                    parsed = json.loads(ingredients)
                    self.assertIsInstance(parsed, list)
                    
                    # Проверяем структуру первого ингредиента
                    if parsed:
                        first_ing = parsed[0]
                        self.assertIn('name', first_ing)
                        self.assertIn('amount', first_ing)
                        self.assertIn('unit', first_ing)
    
    def test_parse_iso_duration(self):
        """Тест парсинга ISO 8601 duration"""
        # PT15M -> 15 minutes
        result = ParkAjinomotoCoJpExtractor.parse_iso_duration("PT15M")
        self.assertEqual(result, "15 minutes")
        
        # PT1H30M -> 90 minutes
        result = ParkAjinomotoCoJpExtractor.parse_iso_duration("PT1H30M")
        self.assertEqual(result, "90 minutes")
        
        # PT30M -> 30 minutes
        result = ParkAjinomotoCoJpExtractor.parse_iso_duration("PT30M")
        self.assertEqual(result, "30 minutes")
        
        # PT45M -> 45 minutes
        result = ParkAjinomotoCoJpExtractor.parse_iso_duration("PT45M")
        self.assertEqual(result, "45 minutes")
    
    def test_extract_time_fields(self):
        """Тест извлечения временных полей"""
        html_file = self.html_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        
        prep_time = extractor.extract_prep_time()
        cook_time = extractor.extract_cook_time()
        total_time = extractor.extract_total_time()
        
        # Хотя бы одно поле должно быть заполнено
        self.assertTrue(
            prep_time is not None or cook_time is not None or total_time is not None,
            "At least one time field should be extracted"
        )
    
    def test_extract_instructions(self):
        """Тест извлечения инструкций"""
        html_file = self.html_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        instructions = extractor.extract_instructions()
        
        self.assertIsNotNone(instructions)
        self.assertIsInstance(instructions, str)
        self.assertGreater(len(instructions), 0)
        # Проверяем что есть нумерация шагов
        self.assertIn('1.', instructions)
    
    def test_extract_image_urls(self):
        """Тест извлечения URL изображений"""
        # Находим файл не print версию
        non_print_files = [f for f in self.html_files if 'print' not in f.name]
        if not non_print_files:
            self.skipTest("No non-print files available")
        
        html_file = non_print_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        image_urls = extractor.extract_image_urls()
        
        # Должно быть изображение в обычных версиях
        self.assertIsNotNone(image_urls)
        if image_urls:
            self.assertIsInstance(image_urls, str)
            # Проверяем что это валидный URL
            self.assertTrue(
                image_urls.startswith('http://') or image_urls.startswith('https://'),
                "Image URL should start with http:// or https://"
            )
    
    def test_all_files_process_without_errors(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = ParkAjinomotoCoJpExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
    
    def test_print_version_support(self):
        """Тест что print версия поддерживается"""
        # Находим print версию
        print_files = [f for f in self.html_files if 'print' in f.name]
        if not print_files:
            self.skipTest("No print files available")
        
        html_file = print_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        result = extractor.extract_all()
        
        # Проверяем что основные поля извлечены
        self.assertIsNotNone(result['dish_name'])
        self.assertIsNotNone(result['description'])
        self.assertIsNotNone(result['ingredients'])
        self.assertIsNotNone(result['instructions'])
        self.assertIsNotNone(result['total_time'])


class TestParkAjinomotoCoJpExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "park_ajinomoto_co_jp"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = ParkAjinomotoCoJpExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        extractor = ParkAjinomotoCoJpExtractor(str(self.html_files[0]))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")
    
    def test_json_ld_data_extraction(self):
        """Тест извлечения JSON-LD данных"""
        # Находим не print версию
        non_print_files = [f for f in self.html_files if 'print' not in f.name]
        if not non_print_files:
            self.skipTest("No non-print files available")
        
        html_file = non_print_files[0]
        extractor = ParkAjinomotoCoJpExtractor(str(html_file))
        json_ld = extractor.get_json_ld_data()
        
        # JSON-LD должен присутствовать в обычных версиях
        self.assertIsNotNone(json_ld)
        self.assertIsInstance(json_ld, dict)
        self.assertIn('@type', json_ld)


if __name__ == '__main__':
    unittest.main()
