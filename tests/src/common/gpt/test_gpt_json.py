import unittest
from src.common.gpt.gpt_json import GPTJsonExtractor


class TestGPTJsonCleaner(unittest.TestCase):
    """Тесты для GPTJsonCleaner - извлечение данных из невалидных JSON от GPT"""
    
    def setUp(self):
        """Подготовка схемы для тестов"""
        self.schema = {
            "type": "object",
            "properties": {
                "dish_name": {"type": "string"},
                "description": {"type": "string"},
                "ingredients": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "instructions": {"type": "string"},
                "cook_time": {"type": "string"},
                "prep_time": {"type": "string"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        }
        self.cleaner = GPTJsonExtractor(self.schema)
    
    def test_extract_value_with_double_quotes(self):
        """Тест извлечения значения с двойными кавычками"""
        json_str = '{"dish_name": "Chicken ""Noodle"" Soup"}'
        key_positions = self.cleaner.make_key_positions(json_str)
        
        value = self.cleaner.extract_value_by_key(json_str, "dish_name", key_positions)
        
        self.assertIsNotNone(value)
        self.assertIn("Chicken", value)
    
    def test_extract_value_with_escaped_quotes(self):
        """Тест извлечения значения с экранированными кавычками"""
        json_str = '{"description": "This soup pairs well with \\"pickles\\"."}'
        key_positions = self.cleaner.make_key_positions(json_str)
        
        value = self.cleaner.extract_value_by_key(json_str, "description", key_positions)
        
        self.assertIsNotNone(value)
        self.assertIn("pickles", value)
    
    def test_extract_array_with_invalid_quotes(self):
        """Тест извлечения массива с невалидными кавычками"""
        json_str = '{"ingredients": ["500 g chicken ""thighs""", "1 \\"medium\\" carrot"]}'
        key_positions = self.cleaner.make_key_positions(json_str)
        
        value = self.cleaner.extract_value_by_key(json_str, "ingredients", key_positions)
        
        self.assertIsNotNone(value)
        self.assertIsInstance(value, list)
        self.assertGreater(len(value), 0)
    
    def test_extract_missing_key(self):
        """Тест извлечения несуществующего ключа"""
        json_str = '{"dish_name": "Soup"}'
        key_positions = self.cleaner.make_key_positions(json_str)
        
        value = self.cleaner.extract_value_by_key(json_str, "missing_key", key_positions)
        
        self.assertIsNone(value)
    
    def test_extract_all_values_invalid_json(self):
        """Тест извлечения всех значений из невалидного JSON"""
        json_str = '''{"dish_name": "Chicken ""Soup""", "description": "Delicious \\"soup\\"", "ingredients": ["chicken", "carrots",], "cook_time": "150 minutes"}'''
        
        result = self.cleaner.extract_all_values(json_str)
        
        self.assertIsInstance(result, dict)
        self.assertIn("dish_name", result)
        self.assertIn("description", result)
        self.assertIn("ingredients", result)
        self.assertIn("cook_time", result)
    
    def test_extract_value_with_newlines(self):
        """Тест извлечения значения с переносами строк"""
        json_str = '{"instructions": "step 1: Cook\\nstep 2: Serve"}'
        key_positions = self.cleaner.make_key_positions(json_str)
        
        value = self.cleaner.extract_value_by_key(json_str, "instructions", key_positions)
        
        self.assertIsNotNone(value)
        self.assertIn("step 1", value)
    
    def test_extract_empty_array(self):
        """Тест извлечения пустого массива"""
        json_str = '{"ingredients": []}'
        key_positions = self.cleaner.make_key_positions(json_str)
        
        value = self.cleaner.extract_value_by_key(json_str, "ingredients", key_positions)
        
        self.assertIsNotNone(value)
        self.assertIsInstance(value, list)
        self.assertEqual(len(value), 0)
    
    def test_extract_complex_invalid_structure(self):
        """Тест извлечения из сложной невалидной структуры"""
        json_str = '''
        {
            "dish_name": "Traditional Homemade Pasta",
            "description": "This recipe has been in my family for generations.",
            "ingredients": [
                "500 g 00 flour",
                "4 large eggs",
                "pinch of salt"
            ],
            "instructions": "Mix flour with eggs. Knead for 10 minutes.",
            "tags": ["pasta", "italian cuisine"]
        }
        '''
        
        result = self.cleaner.extract_all_values(json_str)
        
        self.assertIsInstance(result, dict)
        self.assertIn("dish_name", result)
        self.assertIn("ingredients", result)
        self.assertIsInstance(result["ingredients"], list)
        self.assertGreater(len(result["ingredients"]), 0)


class TestGPTJsonExtractorEdgeCases(unittest.TestCase):
    """Тесты для граничных случаев"""
    
    def setUp(self):
        self.schema = {
            "properties": {
                "name": {"type": "string"},
                "items": {"type": "array", "items": {"type": "string"}}
            }
        }
        self.cleaner = GPTJsonExtractor(self.schema)
    
    def test_unicode_characters(self):
        """Тест обработки unicode символов"""
        json_str = '{"name": "Борщ со сметаной"}'
        key_positions = self.cleaner.make_key_positions(json_str)
        
        value = self.cleaner.extract_value_by_key(json_str, "name", key_positions)
        
        self.assertIsNotNone(value)
        self.assertIn("Борщ", value)
    
    def test_mixed_quotes_types(self):
        """Тест смешанных типов кавычек"""
        json_str = '''{"name": "Recipe with ""quotes"" and double"s"}'''
        
        result = self.cleaner.extract_all_values(json_str)
        
        self.assertIn("name", result)
    
    def test_nested_quotes_in_array(self):
        """Тест вложенных кавычек в массиве"""
        json_str = '{"items": ["item with nested quotes", "item with double quotes"]}'
        key_positions = self.cleaner.make_key_positions(json_str)
        
        value = self.cleaner.extract_value_by_key(json_str, "items", key_positions)
        
        self.assertIsInstance(value, list)
        self.assertEqual(len(value), 2)


if __name__ == '__main__':
    unittest.main()

