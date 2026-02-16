"""
Экстрактор данных рецептов для сайта juliekarla.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class JulieKarlaExtractor(BaseRecipeExtractor):
    """Экстрактор для juliekarla.dk"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT8H" или "PT90M"
            
        Returns:
            Время в читаемом формате, например "20 minutes" или "1 hour 30 minutes"
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
        
        # Если минут больше 60, конвертируем в часы + минуты
        if minutes >= 60:
            hours += minutes // 60
            minutes = minutes % 60
        
        # Форматируем в читаемый вид
        parts = []
        if hours > 0:
            parts.append(f"{hours} {'hour' if hours == 1 else 'hours'}")
        if minutes > 0:
            parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
        
        return " ".join(parts) if parts else None
    
    def get_recipe_json_ld(self) -> Optional[Dict]:
        """Извлечение данных рецепта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            if desc:
                desc = self.clean_text(desc)
                # Добавляем точку в конце, если её нет
                if desc and not desc.endswith('.'):
                    desc += '.'
                return desc
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "250 gr broccoli buketter" или "1 stk æg"
            
        Returns:
            dict: {"name": "broccoli buketter", "amount": 250, "units": "gr"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст от HTML entities и заметок в скобках
        text = self.clean_text(ingredient_text)
        # Удаляем заметки в скобках (например, "(brug et helt stykke og riv)")
        text = re.sub(r'\([^)]*\)', '', text).strip()
        # Удаляем лишние закрывающие скобки
        text = re.sub(r'\s*\)\s*', ' ', text).strip()
        
        # Паттерн: [количество] [единица] [название]
        # Примеры: "250 gr broccoli buketter", "1 stk æg", "1/2 tsk salt"
        pattern = r'^([\d\s/.,]+)?\s*(stk|gr|g|kg|dl|ml|l|tsk|spsk|fed|stilke|flaske|håndfuld|knivspids|kviste|stort)?\.?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part.replace(',', '.'))
                amount = total
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                    # Если это целое число, конвертируем в int
                    if amount == int(amount):
                        amount = int(amount)
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        name = name.strip()
        # Удаляем фразы типа "til stegning"
        name = re.sub(r'\b(til stegning)\b', '', name, flags=re.IGNORECASE).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_recipe_json_ld()
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = []
        
        for ing_text in recipe_data['recipeIngredient']:
            parsed = self.parse_ingredient(ing_text)
            if parsed:
                ingredients_list.append(parsed)
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        recipe_data = self.get_recipe_json_ld()
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            for step in instructions:
                if isinstance(step, dict) and 'text' in step:
                    step_text = self.clean_text(step['text'])
                    if step_text:
                        # Удаляем дополнительные подсказки и заметки
                        # Убираем предложения, начинающиеся с "Man kan også", "Smag evt.", "NB", "Tip"
                        sentences = step_text.split('. ')
                        main_sentences = []
                        for sent in sentences:
                            sent = sent.strip()
                            # Пропускаем предложения с подсказками
                            if not re.match(r'^(Man kan også|Smag evt\.|NB|Tip|Husk)', sent, re.IGNORECASE):
                                main_sentences.append(sent)
                        
                        if main_sentences:
                            step_text = '. '.join(main_sentences)
                            # Убедимся, что в конце есть точка
                            if not step_text.endswith('.'):
                                step_text += '.'
                            steps.append(step_text)
                elif isinstance(step, str):
                    step_text = self.clean_text(step)
                    if step_text:
                        steps.append(step_text)
        elif isinstance(instructions, str):
            steps.append(self.clean_text(instructions))
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_json_ld()
        if not recipe_data:
            return None
        
        # Проверяем recipeCategory
        if 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                # Возвращаем первую категорию
                return self.clean_text(category[0]) if category else None
            elif isinstance(category, str):
                return self.clean_text(category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        return None
    
    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок к рецепту
        Ищем в параграфах характерные фразы-заметки
        """
        entry_content = self.soup.find(class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем в параграфах фразы, начинающиеся с ключевых слов для заметок
        paragraphs = entry_content.find_all('p')
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Разбиваем на предложения
            sentences = re.split(r'[.!]', text)
            
            for sent in sentences:
                sent = sent.strip()
                # Проверяем, начинается ли с ключевых фраз
                if re.match(r'^(Har du ikke|Har du|Nemme|Tip|Note)', sent, re.IGNORECASE):
                    # Это заметка - возвращаем первое предложение
                    # Очищаем от лишнего текста в скобках
                    sent = re.sub(r'\([^)]*\)', '', sent).strip()
                    if sent:
                        # Добавляем точку в конце
                        if not sent.endswith('.'):
                            sent += '.'
                        return self.clean_text(sent)
        
        # Если не нашли в параграфах, ищем в h2 с многоточием
        h2_elements = entry_content.find_all('h2')
        for h2 in h2_elements:
            h2_text = h2.get_text(strip=True)
            # Проверяем, содержит ли заголовок ключевые слова и многоточие
            if re.search(r'(Nemme|perfekte|Tips?)', h2_text, re.IGNORECASE) and h2_text.endswith('…'):
                # Пытаемся собрать полную заметку из h2 и следующего параграфа
                # Это сложный случай - пока просто возвращаем h2 без многоточия
                return self.clean_text(h2_text.rstrip('…').strip() + '.')
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов
        На juliekarla.dk теги извлекаются из названия рецепта, описания и recipeCuisine
        """
        recipe_data = self.get_recipe_json_ld()
        if not recipe_data:
            return None
        
        tags = []
        
        # Добавляем ключевые слова из названия рецепта
        if 'name' in recipe_data:
            name = recipe_data['name']
            # Извлекаем ключевые слова из названия (слова длиннее 2 символов, кроме служебных)
            stopwords = {'med', 'og', 'til', 'af', 'den', 'det', 'som', 'fra', 'på', 'i', 'en', 'et', 'er'}
            words = [w.lower() for w in name.split() if len(w) > 2 and w.lower() not in stopwords]
            tags.extend(words[:4])  # Берем первые 4 ключевых слова
        
        # Добавляем ключевые слова из описания (например, "sundt", "lækkert")
        if 'description' in recipe_data:
            desc = recipe_data['description']
            if desc:
                # Ищем прилагательные, характеризующие блюдо
                desc_words = desc.split()
                for word in desc_words:
                    word_clean = word.lower().strip('.,!?')
                    # Добавляем только характерные прилагательные
                    if word_clean in ['sundt', 'lækkert', 'nem', 'hurtig', 'sund']:
                        if word_clean not in tags:
                            tags.append(word_clean)
        
        # Добавляем теги из recipeCuisine (если это тег типа "vegetar" и т.д.)
        if 'recipeCuisine' in recipe_data:
            cuisine = recipe_data['recipeCuisine']
            if isinstance(cuisine, list):
                for c in cuisine:
                    c = self.clean_text(c).lower()
                    # Добавляем только если это не "dansk" и не "Italiensk" и т.п. (общие кухни)
                    if c and c not in ['dansk', 'italiensk', 'fransk', 'amerikansk']:
                        if c not in tags:
                            tags.append(c)
            elif isinstance(cuisine, str):
                c = self.clean_text(cuisine).lower()
                if c and c not in ['dansk', 'italiensk', 'fransk', 'amerikansk']:
                    if c not in tags:
                        tags.append(c)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower and tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag_lower)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        recipe_data = self.get_recipe_json_ld()
        if not recipe_data or 'image' not in recipe_data:
            return None
        
        images = recipe_data['image']
        urls = []
        
        if isinstance(images, list):
            urls = [img for img in images if isinstance(img, str)]
        elif isinstance(images, str):
            urls = [images]
        
        # Берем только первое изображение (основное)
        if urls:
            return urls[0]
        
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
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """
    Обработка всех HTML файлов из директории preprocessed/juliekarla_dk
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "juliekarla_dk")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из {preprocessed_dir}")
        process_directory(JulieKarlaExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python juliekarla_dk.py")


if __name__ == "__main__":
    main()
