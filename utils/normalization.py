import re
from typing import Optional

# Единицы измерения (только английский язык)
UNIT_PATTERNS = {
    'g', 'kg', 'mg', 'ml', 'l', 'cl', 'dl', 'oz', 'lb', 'lbs', 'cup', 'cups',
    'tbsp', 'tsp', 'tablespoon', 'tablespoons', 'teaspoon', 'teaspoons',
    'piece', 'pieces', 'pcs', 'pc', 'slice', 'slices', 'clove', 'cloves',
    'bunch', 'bunches', 'pinch', 'handful', 'dash', 'sprig', 'sprigs',
    'can', 'cans', 'jar', 'jars', 'bottle', 'bottles', 'package', 'packages',
    'head', 'heads', 'stalk', 'stalks', 'leaf', 'leaves', 'strip', 'strips',
}

# Паттерн для извлечения числа (целое, дробное, диапазон)
NUMBER_PATTERN = re.compile(
    r'^\s*'
    r'('
    r'\d+\s+\d+\s*/\s*\d+|'  # 1 1/2 (смешанная дробь - должна быть первой!)
    r'\d+\s*/\s*\d+|'  # 1/2 (простая дробь)
    r'\d+(?:[.,]\d+)?(?:\s*[-–—]\s*\d+(?:[.,]\d+)?)?'  # 100, 100.5, 100-200
    r')'
    r'\s*',
    re.IGNORECASE
)

def amount_to_float(amount) -> Optional[float]:
    """Преобразует количество в float, если возможно"""
    try:
        return float(amount)
    except (ValueError, TypeError):
        return None

def normalize_ingredient(ingredient: dict) -> dict:
    """
    Normalizes ingredient: extracts amount and unit from name if present.
    
    Examples:
        {"name": "100g flour", "amount": null, "unit": null} 
        -> {"name": "flour", "amount": 100, "unit": "g"}
        
        {"name": "2 cups sugar", "amount": null, "unit": null}
        -> {"name": "sugar", "amount": 2, "unit": "cups"}
        
        {"name": "1/2 tsp salt", "amount": null, "unit": null}
        -> {"name": "salt", "amount": 0.5, "unit": "tsp"}
    """
    if not ingredient or not isinstance(ingredient, dict):
        return ingredient
    
    result = ingredient.copy()
    name = str(result.get('name', '')).strip()
    amount_raw = result.get('amount')
    unit = result.get('unit')
    if not isinstance(unit, str):
        unit = None
    
    # Сначала проверяем, является ли amount строкой (до преобразования в float)
    if amount_raw and isinstance(amount_raw, str) and not str(amount_raw).replace('.', '').replace(',', '').replace('-', '').replace(' ', '').isdigit():
        amount_str = str(amount_raw).strip()
        # Пытаемся извлечь число и единицу из amount
        match = NUMBER_PATTERN.match(amount_str)
        if match:
            num_str = match.group(1).replace(',', '.')
            remaining = amount_str[match.end():].strip()
            
            # Парсим число
            amount = None
            try:
                if '/' in num_str:
                    # Дробь
                    parts = num_str.split()
                    if len(parts) == 2:  # "1 1/2"
                        whole = float(parts[0])
                        frac_parts = parts[1].split('/')
                        amount = whole + float(frac_parts[0]) / float(frac_parts[1])
                    else:  # "1/2"
                        frac_parts = num_str.split('/')
                        amount = float(frac_parts[0]) / float(frac_parts[1])
                elif '-' in num_str or '–' in num_str or '—' in num_str:
                    # Диапазон - берём среднее
                    parts = re.split(r'[-–—]', num_str)
                    amount = (float(parts[0]) + float(parts[1])) / 2
                else:
                    amount = float(num_str)
            except (ValueError, IndexError):
                pass
            
            # Если осталась единица измерения
            if remaining and remaining.lower().rstrip('.') in UNIT_PATTERNS:
                unit = remaining
            elif remaining and not unit:
                unit = remaining
        else:
            # Не удалось распарсить, пробуем преобразовать в float
            amount = amount_to_float(amount_raw)
    else:
        # amount не строка или простое число - преобразуем в float
        amount = amount_to_float(amount_raw)
    
    # Проверяем, есть ли amount/unit в поле name
    if name:
        # Паттерн: число в начале имени
        match = NUMBER_PATTERN.match(name)
        if match:
            num_str = match.group(1).replace(',', '.')
            remaining = name[match.end():].strip()
            
            # Парсим число только если amount еще не задан
            if amount is None or amount == '' or amount == 0:
                try:
                    if '/' in num_str:
                        parts = num_str.split()
                        if len(parts) == 2:
                            whole = float(parts[0])
                            frac_parts = parts[1].split('/')
                            extracted_amount = whole + float(frac_parts[0]) / float(frac_parts[1])
                        else:
                            frac_parts = num_str.split('/')
                            extracted_amount = float(frac_parts[0]) / float(frac_parts[1])
                    elif '-' in num_str or '–' in num_str or '—' in num_str:
                        parts = re.split(r'[-–—]', num_str)
                        extracted_amount = (float(parts[0]) + float(parts[1])) / 2
                    else:
                        extracted_amount = float(num_str)
                        
                    amount = extracted_amount
                except (ValueError, IndexError):
                    pass
            
            # Всегда очищаем name от числа
            name = remaining
        
        # Проверяем единицу измерения в начале оставшегося имени
        if name:
            words = name.split()
            if words:
                first_word = words[0].lower()
                first_word_no_punct = first_word.rstrip('.,;:')
                # Проверяем с точкой и без точки
                if first_word_no_punct in UNIT_PATTERNS or first_word.rstrip(';:') in UNIT_PATTERNS:
                    # Извлекаем unit только если еще не задан
                    if not unit or unit == '':
                        # Сохраняем оригинальную единицу (с точкой если она была)
                        unit = words[0].rstrip(',;:')  # Убираем только запятую, двоеточие и точку с запятой
                    # Всегда очищаем name от единицы
                    name = ' '.join(words[1:]).strip()
    
    # Очищаем name от возможных остатков в скобках типа "(100g)"
    bracket_pattern = re.compile(r'\s*\(\s*(\d+(?:[.,]\d+)?\s*(?:' + '|'.join(re.escape(u) for u in UNIT_PATTERNS) + r'))\s*\)\s*', re.IGNORECASE)
    bracket_match = bracket_pattern.search(name)
    if bracket_match:
        bracket_content = bracket_match.group(1)
        inner_match = NUMBER_PATTERN.match(bracket_content)
        if inner_match:
            # Парсим amount только если еще не задан
            if amount is None or amount == '' or amount == 0:
                try:
                    amount = float(inner_match.group(1).replace(',', '.'))
                    remaining_unit = bracket_content[inner_match.end():].strip()
                    if remaining_unit and (not unit or unit == ''):
                        unit = remaining_unit
                except ValueError:
                    pass
        # Всегда очищаем name от скобок с количеством
        name = name[:bracket_match.start()] + name[bracket_match.end():]
        name = ' '.join(name.split())  # Нормализуем пробелы
    
    # Убираем лишние пробелы и знаки препинания в начале/конце
    name = name.strip(' .,;:-–—')
    if name == '':
        return {}
    
    # Очистка единицы: убираем точку в конце, если это не часть единицы (например, ст.л.)
    if unit:
        unit_str = str(unit).strip()
        # Убираем конечную точку только если это английская единица (без точек внутри)
        if unit_str.endswith('.') and '.' not in unit_str[:-1]:
            unit_str = unit_str[:-1]
        unit = unit_str
    
    result['name'] = name
    result['amount'] = amount if amount not in (None, '', 0) else None
    result['unit'] = str(unit).strip() if unit else ''
    
    return result


def normalize_ingredients_list(ingredients: list[dict]) -> list[dict]:
    """
    Нормализует список ингредиентов.
    """
    if not ingredients:
        return ingredients
    return [norm for ing in ingredients if (norm := normalize_ingredient(ing)) and norm ]