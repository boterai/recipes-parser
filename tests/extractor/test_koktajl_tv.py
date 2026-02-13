"""
Тесты для экстрактора koktajl.tv
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.koktajl_tv import KoktajlTvExtractor


class TestKoktajlTvExtractor(unittest.TestCase):
    """Тесты для KoktajlTvExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "koktajl_tv"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/koktajl_tv")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = KoktajlTvExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = KoktajlTvExtractor(str(html_file))
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
        extractor = KoktajlTvExtractor(str(html_file))
        result = extractor.extract_all()
        
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")
    
    def test_extract_dish_name_not_empty(self):
        """Тест что dish_name извлекается и не пустой"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = KoktajlTvExtractor(str(html_file))
        dish_name = extractor.extract_dish_name()
        
        self.assertIsNotNone(dish_name)
        self.assertIsInstance(dish_name, str)
        self.assertGreater(len(dish_name), 0)
    
    def test_extract_description_for_some_files(self):
        """Тест что description извлекается для некоторых файлов"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Проверяем что хотя бы в одном файле есть описание
        found_description = False
        for html_file in self.html_files:
            extractor = KoktajlTvExtractor(str(html_file))
            description = extractor.extract_description()
            
            if description:
                found_description = True
                self.assertIsInstance(description, str)
                self.assertGreater(len(description), 0)
                break
        
        self.assertTrue(found_description, "No descriptions found in any test file")
    
    def test_extract_ingredients_from_h3_structure(self):
        """Тест извлечения ингредиентов из H3 структуры"""
        # Файл aperol-spritz использует H3 структуру
        aperol_file = self.test_dir / "aperol-spritz_1.html"
        if not aperol_file.exists():
            self.skipTest("aperol-spritz test file not found")
        
        extractor = KoktajlTvExtractor(str(aperol_file))
        ingredients = extractor.extract_ingredients()
        
        self.assertIsNotNone(ingredients)
        # Проверяем что это валидный JSON
        parsed = json.loads(ingredients)
        self.assertIsInstance(parsed, list)
        self.assertGreater(len(parsed), 0)
        
        # Проверяем структуру
        first_ing = parsed[0]
        self.assertIn('name', first_ing)
        self.assertIn('amount', first_ing)
        self.assertIn('units', first_ing)
    
    def test_extract_ingredients_from_table_structure(self):
        """Тест извлечения ингредиентов из TABLE структуры"""
        # Файл white-russian использует TABLE структуру
        white_russian_file = self.test_dir / "white-russian-deserowy-koktajl-z-wodka-i-likierem-kawowym_1.html"
        if not white_russian_file.exists():
            self.skipTest("white-russian test file not found")
        
        extractor = KoktajlTvExtractor(str(white_russian_file))
        ingredients = extractor.extract_ingredients()
        
        self.assertIsNotNone(ingredients)
        # Проверяем что это валидный JSON
        parsed = json.loads(ingredients)
        self.assertIsInstance(parsed, list)
        self.assertGreater(len(parsed), 0)
        
        # Проверяем структуру
        first_ing = parsed[0]
        self.assertIn('name', first_ing)
        self.assertIn('amount', first_ing)
        self.assertIn('units', first_ing)
    
    def test_extract_instructions_not_empty(self):
        """Тест что instructions извлекаются и не пустые"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        # Проверяем что хотя бы в одном файле есть инструкции
        found_instructions = False
        for html_file in self.html_files:
            extractor = KoktajlTvExtractor(str(html_file))
            instructions = extractor.extract_instructions()
            
            if instructions:
                found_instructions = True
                self.assertIsInstance(instructions, str)
                self.assertGreater(len(instructions), 0)
                break
        
        self.assertTrue(found_instructions, "No instructions found in any test file")
    
    def test_extract_tags_when_available(self):
        """Тест что tags извлекаются когда доступны"""
        # white-russian файл имеет теги
        white_russian_file = self.test_dir / "white-russian-deserowy-koktajl-z-wodka-i-likierem-kawowym_1.html"
        if not white_russian_file.exists():
            self.skipTest("white-russian test file not found")
        
        extractor = KoktajlTvExtractor(str(white_russian_file))
        tags = extractor.extract_tags()
        
        self.assertIsNotNone(tags)
        self.assertIsInstance(tags, str)
        self.assertGreater(len(tags), 0)
        # Проверяем что теги разделены запятой
        self.assertIn(',', tags)
    
    def test_all_files_process_without_errors(self):
        """Тест что все HTML файлы обрабатываются без ошибок"""
        for html_file in self.html_files:
            with self.subTest(file=html_file.name):
                extractor = KoktajlTvExtractor(str(html_file))
                result = extractor.extract_all()
                
                # Проверяем что результат содержит все поля
                self.assertIsInstance(result, dict)
                self.assertIn('dish_name', result)
                self.assertIn('description', result)
                self.assertIn('ingredients', result)
                self.assertIn('instructions', result)
                self.assertIn('category', result)
                self.assertIn('tags', result)


class TestKoktajlTvExtractorEdgeCases(unittest.TestCase):
    """Тесты граничных случаев"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "koktajl_tv"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found")
    
    def test_clean_text_removes_html_entities(self):
        """Тест что clean_text удаляет HTML entities"""
        extractor = KoktajlTvExtractor(str(self.html_files[0]))
        
        # Тестируем на примере с HTML entity
        cleaned = extractor.clean_text("Test &quot;quoted&quot; text")
        self.assertNotIn('&quot;', cleaned)
        self.assertIn('"', cleaned)
    
    def test_extract_all_fields_type_consistency(self):
        """Тест что типы полей консистентны"""
        extractor = KoktajlTvExtractor(str(self.html_files[0]))
        result = extractor.extract_all()
        
        # Проверяем что строковые поля либо None, либо str
        string_fields = ['dish_name', 'description', 'category', 'prep_time', 
                        'cook_time', 'total_time', 'notes', 'tags', 'image_urls',
                        'ingredients', 'instructions']
        
        for field in string_fields:
            value = result.get(field)
            self.assertTrue(value is None or isinstance(value, str),
                          f"Field {field} should be None or str, got {type(value)}")
    
    def test_dish_name_cleanup(self):
        """Тест что dish_name правильно очищается от префиксов"""
        # Файл с "Przepis na" в названии
        chocolate_file = self.test_dir / "przepis-na-goraca-czekolade-z-whisky-i-popcornem-karmelowym_1.html"
        if not chocolate_file.exists():
            self.skipTest("chocolate test file not found")
        
        extractor = KoktajlTvExtractor(str(chocolate_file))
        dish_name = extractor.extract_dish_name()
        
        # Проверяем что "Przepis na" удален
        self.assertIsNotNone(dish_name)
        self.assertNotIn('Przepis na', dish_name)
        self.assertNotIn('przepis na', dish_name.lower())


if __name__ == '__main__':
    unittest.main()
