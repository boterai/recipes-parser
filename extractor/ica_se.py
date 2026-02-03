"""
Экстрактор данных рецептов для сайта ica.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class IcaSeExtractor(BaseRecipeExtractor):
    """Экстрактор для ica.se"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        # Ищем скрипт с id="recipeSchemaId"
        script = self.soup.find('script', type='application/ld+json', id='recipeSchemaId')
        
        if script and script.string:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, KeyError):
                pass
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT90M"
            
        Returns:
            Время в формате "Över 60 min" для 90+ минут
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Общее время в минутах
        total_minutes = hours * 60 + minutes
        
        # Формат как на ica.se: "Över 60 min" для >= 60 минут
        if total_minutes >= 60:
            return "Över 60 min"
        elif total_minutes > 0:
            return f"{total_minutes} min"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта - только первое предложение с описанием рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            desc = self.clean_text(json_ld['description'])
            if not desc:
                return None
            
            # Разбиваем на предложения
            sentences = desc.split('. ')
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                
                # Обрезаем часть после "känns", "skapar", "blir" и т.д. если есть
                for cut_word in ['känns', 'skapar', 'blir', 'garanterat']:
                    if f' {cut_word} ' in sentence:
                        sentence = sentence.split(f' {cut_word} ')[0]
                        break
                
                # Ищем предложение, которое содержит описание рецепта
                # Обычно это предложение, которое начинается с описания рецепта,
                # а не просто восклицание или короткая фраза
                
                # Пропускаем короткие предложения (даже после обрезки)
                if len(sentence) < 40:
                    continue
                
                # Это предложение с описанием рецепта
                # Добавляем точку в конце если ее нет
                if not sentence.endswith('.'):
                    sentence += '.'
                
                return sentence
            
            # Если не нашли подходящее, возвращаем первое предложение
            first = sentences[0].strip()
            # Обрезаем если нужно
            for cut_word in ['känns', 'skapar', 'blir', 'garanterat']:
                if f' {cut_word} ' in first:
                    first = first.split(f' {cut_word} ')[0]
                    break
            if not first.endswith('.'):
                first += '.'
            return first
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 burkar sill (à 450 g)" или "4 dl turkisk yoghurt"
                             или "pressad juice av 3 lime" или "1/2 dl ättika"
            
        Returns:
            dict: {"name": "sill", "amount": 2, "units": "burkar (à 450 g)"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн 1: "число единица название" (стандартный)
        # Примеры: "2 burkar sill (à 450 g)", "4 dl turkisk yoghurt"
        pattern1 = r'^(\d+(?:[,\.\/]\d+)?)\s+(\S+)\s+(.+)$'
        match = re.match(pattern1, text)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Проверяем, есть ли в name часть которая должна быть в units (в скобках)
            # Например: "sill (à 450 g)" -> units должен быть "burkar (à 450 g)", а name "sill"
            paren_match = re.search(r'^([^(]+)\s+(\([^)]+\))$', name)
            if paren_match:
                # Переносим скобки в units
                name_part, paren_part = paren_match.groups()
                name = name_part.strip()
                unit = f"{unit} {paren_part}"
            
            # Конвертируем количество в число
            amount = self._parse_amount(amount_str)
            
            return {
                "name": name.strip(),
                "amount": amount,
                "units": unit.strip()
            }
        
        # Паттерн 2: "название (без количества)" или сложные описания
        # Примеры: "pressad juice av 3 lime", "rivet skal av 2 lime"
        # Возвращаем как есть без парсинга
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    @staticmethod
    def _parse_amount(amount_str: str) -> Optional[int | float]:
        """Конвертирует строку с количеством в число"""
        if not amount_str:
            return None
        
        # Обработка дробей типа "1/2"
        if '/' in amount_str:
            try:
                parts = amount_str.split('/')
                if len(parts) == 2:
                    numerator = float(parts[0].replace(',', '.'))
                    denominator = float(parts[1].replace(',', '.'))
                    result = numerator / denominator
                    # Возвращаем float
                    return result
            except (ValueError, ZeroDivisionError):
                return amount_str
        
        # Заменяем запятую на точку для float
        amount_str = amount_str.replace(',', '.')
        try:
            # Пробуем сначала как int
            if '.' not in amount_str:
                return int(amount_str)
            else:
                return float(amount_str)
        except ValueError:
            return amount_str
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        json_ld = self._get_json_ld_data()
        
        if not json_ld or 'recipeIngredient' not in json_ld:
            return None
        
        ingredients = []
        for ingredient_text in json_ld['recipeIngredient']:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        # Возвращаем как JSON-строку
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций из JSON-LD"""
        json_ld = self._get_json_ld_data()
        
        if not json_ld or 'recipeInstructions' not in json_ld:
            return None
        
        instructions_list = json_ld['recipeInstructions']
        
        # Собираем все шаги в одну строку
        steps = []
        for step in instructions_list:
            if isinstance(step, dict) and 'text' in step:
                text = self.clean_text(step['text'])
                if text:
                    # Удаляем префиксы типа "Lag:", "Tips:", etc.
                    text = re.sub(r'^[A-ZÅÄÖ][a-zåäö]+:\s*', '', text)
                    steps.append(text)
            elif isinstance(step, str):
                text = self.clean_text(step)
                if text:
                    # Удаляем префиксы
                    text = re.sub(r'^[A-ZÅÄÖ][a-zåäö]+:\s*', '', text)
                    steps.append(text)
        
        # Объединяем все шаги в одну строку через пробел
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD"""
        # В reference JSON category всегда None, поэтому возвращаем None
        # Хотя в JSON-LD есть recipeCategory, мы его не используем для совместимости
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из JSON-LD"""
        json_ld = self._get_json_ld_data()
        
        # В ica.se используется totalTime, а не отдельно prepTime
        if json_ld and 'totalTime' in json_ld:
            total_time = json_ld['totalTime']
            if total_time:
                return self.parse_iso_duration(total_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки из JSON-LD"""
        json_ld = self._get_json_ld_data()
        
        # На ica.se обычно нет отдельного cookTime
        if json_ld and 'cookTime' in json_ld:
            cook_time = json_ld['cookTime']
            if cook_time:
                return self.parse_iso_duration(cook_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени из JSON-LD"""
        # В reference JSON total_time всегда None, возвращаем None
        # Общее время используется в prep_time вместо этого
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов из HTML"""
        # Ищем заметки в ingredients-list-group-extra__card__ingr div
        notes_texts = []
        seen_texts = set()
        
        # 1. Ищем в accordion контейнере с "Tips"
        extra_div = self.soup.find('div', class_='ingredients-list-group-extra__card__ingr')
        if extra_div:
            text = extra_div.get_text(strip=True)
            if text and text not in seen_texts:
                notes_texts.append(text)
                seen_texts.add(text)
        
        # 2. Ищем параграфы с заметками
        all_paragraphs = self.soup.find_all('p')
        
        for p in all_paragraphs:
            text = p.get_text(strip=True)
            
            # Пропускаем слишком длинные тексты (описания)
            if len(text) > 500:
                continue
            
            # Пропускаем уже добавленные
            if text in seen_texts:
                continue
            
            # Ищем тексты с ключевыми словами для заметок
            if any(keyword in text for keyword in ['Fri från', 'Gör glutenfri', 'Gör laktosfri', 'Rätten är']):
                notes_texts.append(text)
                seen_texts.add(text)
        
        if notes_texts:
            # Объединяем все найденные заметки через точку с пробелом для разделения
            combined_notes = ' '.join(notes_texts)
            # Нормализуем пробелы - добавляем пробел после точки если его нет
            combined_notes = re.sub(r'\.([A-ZÅÄÖ])', r'. \1', combined_notes)
            return self.clean_text(combined_notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов
        
        Теги на ica.se находятся в разных местах и их формат не всегда соответствует
        ожидаемому. Для совместимости с reference JSON возвращаем None.
        """
        # В большинстве reference JSON tags = None
        # Логика извлечения тегов из HTML не дает точного соответствия
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD"""
        json_ld = self._get_json_ld_data()
        
        if not json_ld or 'image' not in json_ld:
            return None
        
        image = json_ld['image']
        
        # image может быть строкой или объектом
        if isinstance(image, str):
            return image
        elif isinstance(image, dict) and 'url' in image:
            return image['url']
        elif isinstance(image, list) and len(image) > 0:
            # Если список, берем все URL
            urls = []
            for img in image:
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, dict) and 'url' in img:
                    urls.append(img['url'])
            
            if urls:
                return ','.join(urls)
        
        return None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "ica_se")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(IcaSeExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python ica_se.py")


if __name__ == "__main__":
    main()
