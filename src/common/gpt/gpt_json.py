"""модуль для очистки строки json по схеме GPT"""
import json
import re
from typing import Optional, Any


class GPTJsonExtractor:
    def __init__(self, schema: dict):
        self.properties = schema.get("properties", {})
    
    def _find_key_position(self, json_str: str, key: str) -> Optional[int]:
        """Найти позицию ключа в строке"""
        pattern = rf'"{re.escape(key)}"\s*:'
        match = re.search(pattern, json_str)
        return match.end() if match else None
    
    def _extract_string_value(self, json_str: str, start_pos: int, end_pos: Optional[int] = None) -> str:
        """Извлечь строковое значение начиная с позиции"""
        # Пропускаем пробелы и первую кавычку
        i = start_pos
        while i < len(json_str) and json_str[i] in ' \t\n':
            i += 1
        
        if i >= len(json_str) or json_str[i] != '"':
            return ""
        
        i += 1  # Пропускаем открывающую кавычку
        value = []
        escaped = False
        
        while i < len(json_str):
            char = json_str[i]
            
            if escaped:
                # Обрабатываем экранированные символы
                if char == '"':
                    value.append('"')
                elif char == '\\':
                    value.append('\\')
                elif char == 'n':
                    value.append('\n')
                else:
                    value.append(char)
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"' and i >= (end_pos or 0) - 3:
                # Конец строки
                break
            else:
                value.append(char)
            
            i += 1
        
        return ''.join(value)
    
    def _extract_array_value(self, json_str: str, start_pos: int) -> list:
        """Извлечь массив начиная с позиции"""
        i = start_pos
        while i < len(json_str) and json_str[i] in ' \t\n':
            i += 1
        
        if i >= len(json_str) or json_str[i] != '[':
            return []
        
        array_str = self._extract_balanced_brackets(json_str, i, '[', ']')
        
        items = []
        item_pattern = r'"([^"\\]*(?:\\.[^"\\]*)*)"'
        for match in re.finditer(item_pattern, array_str):
            item = match.group(1).replace('\\"', '"').replace('\\\\', '\\')
            items.append(item)
        
        return items
    
    def _extract_balanced_brackets(self, text: str, start: int, 
                                   open_br: str, close_br: str) -> str:
        """Извлечь сбалансированную структуру со скобками"""
        depth = 0
        i = start
        result = []
        
        while i < len(text):
            char = text[i]
            result.append(char)
            
            if char == open_br:
                depth += 1
            elif char == close_br:
                depth -= 1
                if depth == 0:
                    break
            
            i += 1
        
        return ''.join(result)
    
    def extract_value_by_key(self, json_str: str, key: str, key_positions: dict) -> Any:
        """Извлечь значение по ключу (строка или массив)"""
        pos = None
        end_pos = len(json_str)

        for k, (start, end) in key_positions.items():
            if pos is not None:
                end_pos = start
                break
            if k == key:
                pos = end
        if pos is None:
            return None
        # Определяем тип значения
        i = pos
        while i < len(json_str) and json_str[i] in ' \t\n':
            i += 1
        
        if i >= len(json_str):
            return None
        
        if json_str[i] == '"':
            return self._extract_string_value(json_str, pos, end_pos)
        elif json_str[i] == '[':
            return self._extract_array_value(json_str, pos)
        
        return None
    
    def make_key_positions(self, json_str: str) -> dict:
        key_positions = {}
        for key in self.properties.keys():
            pos = self._find_key_position(json_str, key)
            if pos is not None:
                key_positions[key] = (pos - len(key) - 3, pos)  # start and end of key match
        
        key_positions = dict(sorted(key_positions.items(), key=lambda item: item[1][0]))
        return key_positions
    
    def extract_all_values(self, json_str: str) -> dict:
        """Извлечь все значения по схеме"""        
        key_positions = self.make_key_positions(json_str)

        result = {}
        
        for key in self.properties.keys():
            value = self.extract_value_by_key(json_str, key, key_positions)
            if value is not None:
                result[key] = value
        
        return result

if __name__ == "__main__":
    str_data = '{"dish_name": "Chicken Noodle Soup with Omelette", "description": "This soup pairs well with lightly salted pickles and pickled garlic.", "ingredients": ["500 g chicken thighs on the bone", "1 medium carrot", "1 medium onion", "4 cloves of garlic", "1 small bunch of parsley or dill", "150 g egg noodles", "2 eggs", "1 tbsp butter or vegetable oil", "0.5 tsp whole black peppercorns", "0.5 tsp whole allspice berries", "salt, freshly ground black pepper"], "tags": ["soup", "chicken soup", "noodle soup", "chicken thighs"], "category": "soup", "instructions": "step 1: Rub the chicken thighs with salt, place in a pot, cover with 2 liters of cold water. Bring to a boil over high heat. Reduce the heat to a simmer. Skim off any foam. step 2: Thoroughly scrub the onion and carrot without peeling. Cut in half lengthwise. Dry roast in a pan without oil until charred. Crush the garlic cloves with the flat side of a knife. Trim the stems from the herbs, wash them well (set aside the leaves). step 3: Add all prepared vegetables and herb stems to the broth. Add the black and allspice berries and a little salt. Simmer, uncovered, for 2 hours. step 4: Finely chop the herb leaves. Whisk the eggs with a pinch of salt. Add 2 tsp of herbs. Heat a skillet over medium heat, melt the butter. Pour in the eggs and cook the omelette. The eggs should be fully cooked. Transfer the omelette to a cutting board, let it cool, then slice into thin strips. step 5: Remove the chicken thighs from the broth with a slotted spoon, cut the meat off the bones. Strain the broth into a clean pot. Add the chicken meat. Bring the broth to a boil again, add the noodles, cook according to the package instructions. Divide the omelette "noodles" among bowls, pour the soup with egg noodles and chicken meat. Sprinkle with the remaining herbs and serve.", "cook_time": "150 minutes", "prep_time": "", "total_time": "150 minutes"}'
    with open("src/models/schemas/translated_recipe.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    cleaner = GPTJsonExtractor(schema=schema)
    
    # Извлекаем все поля по схеме без json.loads
    extracted = cleaner.extract_all_values(str_data)
    
    print(json.dumps(extracted, ensure_ascii=False, indent=2))