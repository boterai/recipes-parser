"""
Тесты для экстрактора elenabucataria.com
"""

import unittest
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extractor.elenabucataria_com import ElenaExtractor


class TestElenaExtractor(unittest.TestCase):
    """Тесты для ElenaExtractor"""
    
    @classmethod
    def setUpClass(cls):
        """Подготовка - находим тестовые HTML файлы"""
        cls.test_dir = Path(__file__).parent.parent.parent / "preprocessed" / "elenabucataria_com"
        cls.html_files = list(cls.test_dir.glob("*.html"))
        
        if not cls.html_files:
            raise unittest.SkipTest("No HTML test files found in preprocessed/elenabucataria_com")
    
    def test_extractor_initialization(self):
        """Тест инициализации экстрактора"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ElenaExtractor(str(html_file))
        
        self.assertIsNotNone(extractor.soup)
        self.assertIsNotNone(extractor.html_path)
    
    def test_extract_all_returns_dict(self):
        """Тест что extract_all возвращает словарь"""
        if not self.html_files:
            self.skipTest("No HTML files available")
        
        html_file = self.html_files[0]
        extractor = ElenaExtractor(str(html_file))
        result = extractor.extract_all()
        
        self.assertIsInstance(result, dict)
    
    def test_extract_all_has_required_fields(self):
        """Тест наличия всех обязательных полей"""
        required_fields = [
            'dish_name', 'description', 'ingredients', 'instructions',
            'category', 'prep_time', 'cook_time', 'total_time',
            'notes', 'tags', 'image_urls'
        ]
        
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                extractor = ElenaExtractor(str(html_file))
                result = extractor.extract_all()
                
                for field in required_fields:
                    self.assertIn(field, result, f"Field '{field}' missing in result")
    
    def test_dish_name_extracted(self):
        """Тест извлечения названия блюда"""
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                extractor = ElenaExtractor(str(html_file))
                result = extractor.extract_all()
                
                # dish_name должно быть строкой (не None для наших тестовых файлов)
                self.assertIsNotNone(result['dish_name'])
                self.assertIsInstance(result['dish_name'], str)
                self.assertGreater(len(result['dish_name']), 0)
    
    def test_description_extracted(self):
        """Тест извлечения описания"""
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                extractor = ElenaExtractor(str(html_file))
                result = extractor.extract_all()
                
                # description должно присутствовать
                if result['description'] is not None:
                    self.assertIsInstance(result['description'], str)
                    self.assertGreater(len(result['description']), 0)
    
    def test_ingredients_format(self):
        """Тест формата ингредиентов"""
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                extractor = ElenaExtractor(str(html_file))
                result = extractor.extract_all()
                
                if result['ingredients'] is not None:
                    # Должно быть JSON строкой
                    self.assertIsInstance(result['ingredients'], str)
                    
                    # Парсим JSON
                    ingredients = json.loads(result['ingredients'])
                    self.assertIsInstance(ingredients, list)
                    
                    # Проверяем структуру каждого ингредиента
                    for ing in ingredients:
                        self.assertIsInstance(ing, dict)
                        self.assertIn('name', ing)
                        self.assertIn('amount', ing)
                        self.assertIn('units', ing)
                        
                        # name должно быть строкой
                        self.assertIsInstance(ing['name'], str)
                        # amount может быть None, int или float
                        if ing['amount'] is not None:
                            self.assertIsInstance(ing['amount'], (int, float))
                        # units может быть None или строкой
                        if ing['units'] is not None:
                            self.assertIsInstance(ing['units'], str)
    
    def test_instructions_extracted(self):
        """Тест извлечения инструкций"""
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                extractor = ElenaExtractor(str(html_file))
                result = extractor.extract_all()
                
                if result['instructions'] is not None:
                    self.assertIsInstance(result['instructions'], str)
                    self.assertGreater(len(result['instructions']), 0)
    
    def test_time_fields_format(self):
        """Тест формата полей времени"""
        time_fields = ['prep_time', 'cook_time', 'total_time']
        
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                extractor = ElenaExtractor(str(html_file))
                result = extractor.extract_all()
                
                for field in time_fields:
                    if result[field] is not None:
                        self.assertIsInstance(result[field], str)
                        self.assertGreater(len(result[field]), 0)
    
    def test_image_urls_format(self):
        """Тест формата image_urls"""
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                extractor = ElenaExtractor(str(html_file))
                result = extractor.extract_all()
                
                if result['image_urls'] is not None:
                    self.assertIsInstance(result['image_urls'], str)
                    # Должно начинаться с http
                    self.assertTrue(result['image_urls'].startswith('http'))
    
    def test_notes_format(self):
        """Тест формата заметок"""
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                extractor = ElenaExtractor(str(html_file))
                result = extractor.extract_all()
                
                if result['notes'] is not None:
                    self.assertIsInstance(result['notes'], str)
                    self.assertGreater(len(result['notes']), 0)
    
    def test_extract_all_no_exceptions(self):
        """Тест что extract_all не выбрасывает исключений"""
        for html_file in self.html_files:
            with self.subTest(html_file=html_file.name):
                try:
                    extractor = ElenaExtractor(str(html_file))
                    result = extractor.extract_all()
                    self.assertIsNotNone(result)
                except Exception as e:
                    self.fail(f"extract_all raised {type(e).__name__}: {e}")


if __name__ == '__main__':
    unittest.main()
