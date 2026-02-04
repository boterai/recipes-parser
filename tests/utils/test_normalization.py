import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.normalization import normalize_ingredient, normalize_ingredients_list


class TestNormalizeIngredient(unittest.TestCase):
    """Тесты для нормализации ингредиентов"""

    def test_simple_amount_and_unit_in_name(self):
        """Тест: простое число и единица в начале name"""
        ingredient = {"name": "100g flour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "flour")
        self.assertEqual(result["amount"], 100.0)
        self.assertEqual(result["unit"], "g")

    def test_amount_with_space_and_unit(self):
        """Тест: число с пробелом перед единицей"""
        ingredient = {"name": "2 cups sugar", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "sugar")
        self.assertEqual(result["amount"], 2.0)
        self.assertEqual(result["unit"], "cups")

    def test_decimal_amount(self):
        """Тест: десятичное число"""
        ingredient = {"name": "1.5 kg potatoes", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "potatoes")
        self.assertEqual(result["amount"], 1.5)
        self.assertEqual(result["unit"], "kg")

    def test_simple_fraction(self):
        """Тест: простая дробь 1/2"""
        ingredient = {"name": "1/2 cup milk", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "milk")
        self.assertEqual(result["amount"], 0.5)
        self.assertEqual(result["unit"], "cup")

    def test_mixed_fraction(self):
        """Тест: смешанная дробь 1 1/2"""
        ingredient = {"name": "1 1/2 cups butter", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "butter")
        self.assertEqual(result["amount"], 1.5)
        self.assertEqual(result["unit"], "cups")

    def test_range_with_hyphen(self):
        """Тест: диапазон с дефисом (берётся среднее)"""
        ingredient = {"name": "100-200g cheese", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "cheese")
        self.assertEqual(result["amount"], 150.0)
        self.assertEqual(result["unit"], "g")

    def test_range_with_dash(self):
        """Тест: диапазон с длинным тире"""
        ingredient = {"name": "50–100 ml water", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "water")
        self.assertEqual(result["amount"], 75.0)
        self.assertEqual(result["unit"], "ml")

    def test_amount_in_brackets(self):
        """Тест: число и единица в скобках"""
        ingredient = {"name": "flour (500g)", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "flour")
        self.assertEqual(result["amount"], 500.0)
        self.assertEqual(result["unit"], "g")

    def test_amount_in_brackets_with_space(self):
        """Тест: число и единица в скобках с пробелами"""
        ingredient = {"name": "butter ( 200 g )", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "butter")
        self.assertEqual(result["amount"], 200.0)
        self.assertEqual(result["unit"], "g")

    def test_amount_field_with_complex_string(self):
        """Тест: поле amount содержит сложную строку"""
        ingredient = {"name": "flour", "amount": "100-150 g", "unit": ""}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "flour")
        self.assertEqual(result["amount"], 125.0)
        self.assertEqual(result["unit"], "g")

    def test_no_extraction_needed(self):
        """Тест: ингредиент уже нормализован"""
        ingredient = {"name": "flour", "amount": 500, "unit": "g"}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "flour")
        self.assertEqual(result["amount"], 500.0)
        self.assertEqual(result["unit"], "g")

    def test_only_name_no_amount(self):
        """Тест: только название без количества"""
        ingredient = {"name": "salt to taste", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "salt to taste")
        self.assertIsNone(result["amount"])
        self.assertEqual(result["unit"], "")

    def test_complex_unit_patterns(self):
        """Тест: различные варианты единиц"""
        test_cases = [
            {"input": {"name": "3 tablespoons oil", "amount": None, "unit": None},
             "expected": {"name": "oil", "amount": 3.0, "unit": "tablespoons"}},
            
            {"input": {"name": "2 teaspoons vanilla", "amount": None, "unit": None},
             "expected": {"name": "vanilla", "amount": 2.0, "unit": "teaspoons"}},
            
            {"input": {"name": "5 pieces chicken", "amount": None, "unit": None},
             "expected": {"name": "chicken", "amount": 5.0, "unit": "pieces"}},
            
            {"input": {"name": "1 pinch salt", "amount": None, "unit": None},
             "expected": {"name": "salt", "amount": 1.0, "unit": "pinch"}},
        ]
        
        for case in test_cases:
            with self.subTest(input=case["input"]):
                result = normalize_ingredient(case["input"])
                self.assertEqual(result["name"], case["expected"]["name"])
                self.assertEqual(result["amount"], case["expected"]["amount"])
                self.assertEqual(result["unit"], case["expected"]["unit"])

    def test_unit_with_period(self):
        """Тест: единица с точкой на конце"""
        ingredient = {"name": "2 tbsp. butter", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "butter")
        self.assertEqual(result["amount"], 2.0)
        self.assertEqual(result["unit"], "tbsp")

    def test_trailing_punctuation_in_name(self):
        """Тест: знаки препинания в конце name после извлечения"""
        ingredient = {"name": "100g ,flour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "flour")
        self.assertEqual(result["amount"], 100.0)
        self.assertEqual(result["unit"], "g")

    def test_empty_ingredient(self):
        """Тест: пустой ингредиент"""
        ingredient = {"name": "", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "")
        self.assertIsNone(result["amount"])
        self.assertEqual(result["unit"], "")

    def test_none_ingredient(self):
        """Тест: None вместо словаря"""
        result = normalize_ingredient(None)
        self.assertIsNone(result)

    def test_invalid_ingredient(self):
        """Тест: невалидный тип (не словарь)"""
        result = normalize_ingredient("not a dict")
        self.assertEqual(result, "not a dict")

    def test_preserve_existing_amount_if_valid(self):
        """Тест: сохранение существующего amount если он валиден, но очистка name"""
        ingredient = {"name": "100g flour", "amount": 200, "unit": "kg"}
        result = normalize_ingredient(ingredient)
        
        # Должно сохранить существующий amount и unit, но очистить name от "100g"
        self.assertEqual(result["name"], "flour")
        self.assertEqual(result["amount"], 200.0)
        self.assertEqual(result["unit"], "kg")

    def test_zero_amount_triggers_extraction(self):
        """Тест: amount=0 триггерит извлечение из name"""
        ingredient = {"name": "50g sugar", "amount": 0, "unit": ""}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "sugar")
        self.assertEqual(result["amount"], 50.0)
        self.assertEqual(result["unit"], "g")

    def test_multiple_words_after_unit(self):
        """Тест: несколько слов после единицы"""
        ingredient = {"name": "2 cups all-purpose flour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "all-purpose flour")
        self.assertEqual(result["amount"], 2.0)
        self.assertEqual(result["unit"], "cups")


class TestNormalizeIngredientsList(unittest.TestCase):
    """Тесты для нормализации списка ингредиентов"""

    def test_normalize_multiple_ingredients(self):
        """Тест: нормализация списка из нескольких ингредиентов"""
        ingredients = [
            {"name": "100g flour", "amount": None, "unit": None},
            {"name": "2 cups sugar", "amount": None, "unit": None},
            {"name": "1/2 tsp salt", "amount": None, "unit": None},
        ]
        
        result = normalize_ingredients_list(ingredients)
        
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["name"], "flour")
        self.assertEqual(result[0]["amount"], 100.0)
        self.assertEqual(result[1]["name"], "sugar")
        self.assertEqual(result[1]["amount"], 2.0)
        self.assertEqual(result[2]["name"], "salt")
        self.assertEqual(result[2]["amount"], 0.5)

    def test_normalize_empty_list(self):
        """Тест: пустой список"""
        result = normalize_ingredients_list([])
        self.assertEqual(result, [])

    def test_normalize_none_list(self):
        """Тест: None вместо списка"""
        result = normalize_ingredients_list(None)
        self.assertIsNone(result)

    def test_normalize_mixed_valid_invalid(self):
        """Тест: список с валидными и невалидными элементами"""
        ingredients = [
            {"name": "100g flour", "amount": None, "unit": None},
            None,
            {"name": "sugar", "amount": 50, "unit": "g"},
        ]
        
        result = normalize_ingredients_list(ingredients)
        
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["name"], "flour")
        self.assertIsNone(result[1])
        self.assertEqual(result[2]["name"], "sugar")


class TestEdgeCases(unittest.TestCase):
    """Тесты для граничных случаев"""

    def test_very_long_number(self):
        """Тест: очень большое число"""
        ingredient = {"name": "1000000g flour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["amount"], 1000000.0)

    def test_very_small_fraction(self):
        """Тест: очень маленькая дробь"""
        ingredient = {"name": "1/8 tsp pepper", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["amount"], 0.125)

    def test_multiple_spaces(self):
        """Тест: множественные пробелы"""
        ingredient = {"name": "100g    flour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "flour")
        self.assertNotIn("    ", result["name"])

    def test_tabs_and_newlines(self):
        """Тест: табы и переносы строк"""
        ingredient = {"name": "100g\t\nflour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"].strip(), "flour")
        self.assertEqual(result["amount"], 100.0)

    def test_amount_with_plus(self):
        """Тест: количество с плюсом (не поддерживается, должно остаться как есть)"""
        ingredient = {"name": "100+50g flour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        # Паттерн не распознает +, поэтому извлечёт только 100
        self.assertEqual(result["amount"], 100.0)

    def test_decimal_with_multiple_dots(self):
        """Тест: неправильное число с несколькими точками"""
        ingredient = {"name": "1.2.3g flour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        # Должно распарсить только 1.2
        self.assertEqual(result["amount"], 1.2)


class TestComplexCases(unittest.TestCase):
    """Тесты для сложных случаев - проверка что ничего лишнего не удаляется и не добавляется"""
    
    def test_ingredient_with_description(self):
        """Тест: ингредиент с описанием после количества"""
        ingredient = {"name": "100g fresh tomatoes", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "fresh tomatoes")
        self.assertEqual(result["amount"], 100.0)
        self.assertEqual(result["unit"], "g")
    
    def test_ingredient_with_multiple_descriptors(self):
        """Тест: ингредиент с несколькими описаниями"""
        ingredient = {"name": "2 cups fresh organic flour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "fresh organic flour")
        self.assertEqual(result["amount"], 2.0)
        self.assertEqual(result["unit"], "cups")
    
    def test_ingredient_without_amount_multiple_words(self):
        """Тест: ингредиент без количества с несколькими словами"""
        ingredient = {"name": "fresh basil leaves", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "fresh basil leaves")
        self.assertIsNone(result["amount"])
        self.assertEqual(result["unit"], "")
    
    def test_ingredient_name_containing_number_in_middle(self):
        """Тест: название содержит число в середине (не количество)"""
        ingredient = {"name": "type 00 flour", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        # Число в середине не должно извлекаться
        self.assertEqual(result["name"], "type 00 flour")
        self.assertIsNone(result["amount"])
        self.assertEqual(result["unit"], "")
    
    def test_ingredient_with_number_at_end(self):
        """Тест: число в конце названия (не количество)"""
        ingredient = {"name": "olive oil extra virgin 1L bottle", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        # Число в конце не извлекается
        self.assertEqual(result["name"], "olive oil extra virgin 1L bottle")
        self.assertIsNone(result["amount"])
    
    def test_word_similar_to_unit_but_not_unit(self):
        """Тест: слово похоже на единицу, но не является ей"""
        ingredient = {"name": "cupboard staples", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        # "cup" есть в "cupboard", но это не единица
        self.assertEqual(result["name"], "cupboard staples")
        self.assertIsNone(result["amount"])
        self.assertEqual(result["unit"], "")
    
    def test_ingredient_already_clean(self):
        """Тест: ингредиент уже чистый, ничего удалять не нужно"""
        ingredient = {"name": "chicken breast", "amount": 500, "unit": "g"}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "chicken breast")
        self.assertEqual(result["amount"], 500.0)
        self.assertEqual(result["unit"], "g")
    
    def test_ingredient_with_brand_name(self):
        """Тест: ингредиент с названием бренда"""
        ingredient = {"name": "100g Philadelphia cream cheese", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "Philadelphia cream cheese")
        self.assertEqual(result["amount"], 100.0)
        self.assertEqual(result["unit"], "g")
    
    def test_ingredient_with_parentheses_description(self):
        """Тест: ингредиент с описанием в скобках (не количество)"""
        ingredient = {"name": "flour (all-purpose)", "amount": 500, "unit": "g"}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "flour (all-purpose)")
        self.assertEqual(result["amount"], 500.0)
        self.assertEqual(result["unit"], "g")
    
    def test_amount_and_unit_in_name_already_in_fields(self):
        """Тест: количество и единица есть и в name и в полях - должны удалиться из name"""
        ingredient = {"name": "200g butter", "amount": 200, "unit": "g"}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "butter")
        self.assertEqual(result["amount"], 200.0)
        self.assertEqual(result["unit"], "g")
    
    def test_different_amount_in_name_and_field(self):
        """Тест: разное количество в name и в поле amount"""
        ingredient = {"name": "100g sugar", "amount": 150, "unit": "g"}
        result = normalize_ingredient(ingredient)
        
        # Сохраняется значение из поля amount, но name очищается
        self.assertEqual(result["name"], "sugar")
        self.assertEqual(result["amount"], 150.0)
        self.assertEqual(result["unit"], "g")
    
    def test_compound_ingredient_name(self):
        """Тест: сложное составное название"""
        ingredient = {"name": "2 tbsp extra-virgin olive oil", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "extra-virgin olive oil")
        self.assertEqual(result["amount"], 2.0)
        self.assertEqual(result["unit"], "tbsp")
    
    def test_ingredient_with_comma_separated_description(self):
        """Тест: ингредиент с описанием через запятую"""
        ingredient = {"name": "100g flour, sifted", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "flour, sifted")
        self.assertEqual(result["amount"], 100.0)
        self.assertEqual(result["unit"], "g")
    
    def test_measurement_in_brackets_with_description(self):
        """Тест: количество в скобках + описание"""
        ingredient = {"name": "fresh tomatoes (500g), diced", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "fresh tomatoes, diced")
        self.assertEqual(result["amount"], 500.0)
        self.assertEqual(result["unit"], "g")
    
    def test_no_false_unit_extraction(self):
        """Тест: не должно извлекаться ложное количество из похожих слов"""
        # can, jar, bottle - это валидные единицы измерения, поэтому они будут извлечены
        test_cases = [
            {"name": "1 can of beans", "expected_name": "of beans", "expected_amount": 1.0, "expected_unit": "can"},
            {"name": "2 jars of honey", "expected_name": "of honey", "expected_amount": 2.0, "expected_unit": "jars"},
            {"name": "1 bottle of water", "expected_name": "of water", "expected_amount": 1.0, "expected_unit": "bottle"},
        ]
        
        for case in test_cases:
            with self.subTest(name=case["name"]):
                ingredient = {"name": case["name"], "amount": None, "unit": None}
                result = normalize_ingredient(ingredient)
                self.assertEqual(result["name"], case["expected_name"])
                self.assertEqual(result["amount"], case["expected_amount"])
                self.assertEqual(result["unit"], case["expected_unit"])
    
    def test_preserve_special_characters(self):
        """Тест: сохранение специальных символов в названии"""
        ingredient = {"name": "100g jalapeño peppers", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "jalapeño peppers")
        self.assertEqual(result["amount"], 100.0)
        self.assertEqual(result["unit"], "g")
    
    def test_hyphenated_amounts(self):
        """Тест: количество через дефис (диапазон)"""
        ingredient = {"name": "50-75g parmesan cheese", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["name"], "parmesan cheese")
        self.assertEqual(result["amount"], 62.5)  # Среднее от 50 и 75
        self.assertEqual(result["unit"], "g")
    
    def test_amount_with_approximately(self):
        """Тест: количество с приблизительным значением"""
        ingredient = {"name": "~100g chocolate chips", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        # Тильда не распознается паттерном, должна остаться часть имени
        self.assertIn("chocolate chips", result["name"])
    
    def test_multiple_amounts_only_first_extracted(self):
        """Тест: несколько количеств - извлекается только первое"""
        ingredient = {"name": "2 cups flour plus 1 cup sugar", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        self.assertEqual(result["amount"], 2.0)
        self.assertEqual(result["unit"], "cups")
        # "plus 1 cup sugar" должно остаться в имени
        self.assertIn("flour plus 1", result["name"])
    
    def test_no_extraction_from_middle_of_word(self):
        """Тест: не извлекать из середины слова"""
        ingredient = {"name": "sugar100free sweetener", "amount": None, "unit": None}
        result = normalize_ingredient(ingredient)
        
        # Число в середине слова не должно извлекаться
        self.assertEqual(result["name"], "sugar100free sweetener")
        self.assertIsNone(result["amount"])


if __name__ == "__main__":
    unittest.main()
