"""
Экстрактор данных рецептов для сайта eda.vot-tac.ru
"""

import sys
from pathlib import Path
import json
import re
import copy
from typing import Optional
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class EdaVotTacExtractor(BaseRecipeExtractor):
    """Экстрактор для eda.vot-tac.ru"""
    
    # Константы для фильтрации и распознавания контента
    IRRELEVANT_CONTENT_KEYWORDS = ['елки', 'наливай', 'счастье', 'исполнитель']
    COOKING_ACTION_VERBS = [
        'вымыть', 'разрезать', 'выложить', 'посолить', 'посыпать', 
        'нарезать', 'выпекать', 'запекать', 'смешать', 'полить'
    ]
    RUSSIAN_STOPWORDS = {'с', 'в', 'и', 'для', 'из', 'на', 'по', 'к', 'у', 'о'}
    INGREDIENT_UNITS = r'(мл|г|кг|л|клубней|зубчика|зубчиков|шт|штук|ст\.?\s*л\.?|ч\.?\s*л\.?|стаканов?|чайных?\s+ложек?|столовых?\s+ложек?|кусочек)'
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем первый h2 в entry-content (обычно содержит полное название)
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            h2 = entry_content.find('h2')
            if h2:
                name = self.clean_text(h2.get_text())
                if name:
                    return name
        
        # Альтернативно - из h1.entry-title
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем "Рецепт" в начале
            title = re.sub(r'^Рецепт\s+', '', title, flags=re.IGNORECASE)
            return title
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в entry-content первый параграф после заголовка
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Найдем первый h2
            h2 = entry_content.find('h2')
            if h2:
                # Берем текст самого h2 как описание если это короткое описание блюда
                h2_text = self.clean_text(h2.get_text())
                # Проверяем если это не заголовок типа "Ингредиенты для" или "Рецепт"
                if h2_text and not any(x in h2_text for x in ['Ингредиенты для', 'Рецепт', 'Пищевая']):
                    # Проверяем если следующий элемент - параграф с описанием
                    next_p = h2.find_next('p')
                    if next_p:
                        desc = self.clean_text(next_p.get_text())
                        # Убираем описание если это просто составляющие
                        if desc and not desc.startswith('Состав:') and 'Время приготовления' not in desc:
                            return desc
                    
                    # Если нет параграфа с описанием, генерируем из названия блюда
                    # Например: "Картофель, запеченный с лимоном" -> "Запеченный картофель с лимоном"
                    # Это упрощенный вариант для рецептов без явного описания
                    # Можно вернуть None или сгенерировать простое описание
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем параграф с "Состав:"
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Метод 1: Найдем тег с текстом "Состав:"
        composition_tag = None
        for p in entry_content.find_all('p'):
            strong = p.find('strong')
            if strong and 'Состав:' in strong.get_text():
                composition_tag = p
                break
        
        if composition_tag:
            # Получаем весь текст, заменяя <br> на перенос строки
            html_content = str(composition_tag)
            # Заменяем <br> на \n
            html_content = html_content.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
            
            # Парсим снова чтобы извлечь текст
            temp_soup = BeautifulSoup(html_content, 'lxml')
            text = temp_soup.get_text()
            
            # Разделяем по переносам строк
            lines = text.split('\n')
            
            for line in lines:
                line = self.clean_text(line)
                if not line or 'Состав:' in line:
                    continue
                
                # Парсим ингредиент
                parsed = self.parse_ingredient_structured(line)
                if parsed:
                    ingredients.append(parsed)
            
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        # Метод 2: Если нет "Состав:", ищем упоминания ингредиентов в инструкциях
        # Для формата без явного списка ингредиентов, извлекаем ключевые слова
        # из инструкций (это менее точный метод, но для некоторых рецептов единственный)
        # Берем первое упоминание основных продуктов из инструкций
        return None  # Для таких случаев возвращаем None
    
    def parse_ingredient_structured(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат для eda.vot-tac.ru
        
        Примеры:
        "6 клубней картофеля" -> {"name": "картофель", "amount": 6, "units": "клубней"}
        "50 мл. ароматного подсолнечного масла" -> {"name": "ароматное подсолнечное масло", "amount": 50, "units": "мл"}
        "соль по-вкусу" -> {"name": "соль", "amount": None, "units": "по вкусу"}
        """
        if not text:
            return None
        
        text = self.clean_text(text).lower()
        
        # Паттерн для извлечения: [количество] [единица] [название]
        # Примеры: "6 клубней картофеля", "50 мл ароматного масла"
        # Поддержка формата "50 мл. название"
        pattern1 = rf'^(\d+(?:[.,]\d+)?)\s+{self.INGREDIENT_UNITS}\.?\s+(.+)$'
        
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Очистка количества
            amount = amount_str.replace(',', '.')
            try:
                if '.' in amount:
                    amount_val = float(amount)
                    if amount_val.is_integer():
                        amount = int(amount_val)
                    else:
                        amount = amount_val
                else:
                    amount = int(amount)
            except ValueError:
                amount = amount_str
            
            # Очистка единицы измерения
            unit = unit.strip().rstrip('.')
            
            # Очистка названия  
            name = self.clean_text(name)
            # Убираем описания в скобках
            name = re.sub(r'\s*\([^)]*\)', '', name).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн для "по вкусу", "по желанию" и т.д.
        if 'по' in text and ('вкусу' in text or 'желанию' in text):
            # Извлекаем название до "по"
            name_match = re.match(r'^(.+?)\s+по[\s\-](?:вкусу|желанию)', text)
            if name_match:
                return {
                    "name": name_match.group(1).strip(),
                    "amount": None,
                    "units": "по вкусу"
                }
        
        # Паттерн для "кусочек корня имбиря (примерно...)"
        if 'кусочек' in text:
            # Извлекаем описание в скобках как units
            desc_match = re.match(r'^кусочек\s+(.+?)\s*(\([^)]+\))?$', text)
            if desc_match:
                name = desc_match.group(1).strip()
                desc = desc_match.group(2)
                return {
                    "name": name,
                    "amount": None,
                    "units": desc.strip('()') if desc else None
                }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Метод 1: Ищем параграф с "Приготовление:"
        preparation_tag = None
        for strong in entry_content.find_all('strong'):
            if 'Приготовление:' in strong.get_text():
                preparation_tag = strong.parent
                break
        
        if preparation_tag:
            # Заменяем <br> на пробелы
            html_content = str(preparation_tag)
            html_content = html_content.replace('<br>', ' ').replace('<br/>', ' ').replace('<br />', ' ')
            
            temp_soup = BeautifulSoup(html_content, 'lxml')
            text = self.clean_text(temp_soup.get_text())
            
            # Убираем "Приготовление:" из начала
            text = re.sub(r'^Приготовление:\s*', '', text, flags=re.IGNORECASE)
            
            # Убираем последнее предложение если оно содержит рекомендацию
            sentences = re.split(r'\.\s+', text)
            if sentences:
                last_sentence = sentences[-1].strip()
                if 'подойдет' in last_sentence.lower() or 'прекрасно' in last_sentence.lower():
                    # Удаляем последнее предложение
                    text = '. '.join(sentences[:-1])
                    if text and not text.endswith('.'):
                        text += '.'
            
            return text if text else None
        
        # Метод 2: Ищем h2 с "Рецепт" и собираем параграфы после него
        for h2 in entry_content.find_all('h2'):
            h2_text = h2.get_text()
            # Ищем заголовок рецепта (может содержать кавычки или быть более общим)
            if 'Рецепт' in h2_text and '«' in h2_text:
                # Собираем все параграфы до следующего h2
                paragraphs = []
                current = h2.find_next_sibling()
                while current:
                    if current.name == 'h2':
                        break
                    if current.name == 'p':
                        text = self.clean_text(current.get_text())
                        # Пропускаем параграфы с нерелевантным контентом
                        if text and not any(word in text.lower() for word in self.IRRELEVANT_CONTENT_KEYWORDS):
                            # Проверяем что это инструкция (содержит глаголы действия)
                            if any(word in text.lower() for word in self.COOKING_ACTION_VERBS):
                                paragraphs.append(text)
                    current = current.find_next_sibling()
                
                if paragraphs:
                    # Объединяем параграфы в одну инструкцию
                    return ' '.join(paragraphs)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории
        
        Note: Все рецепты на сайте eda.vot-tac.ru относятся к основным блюдам,
        поэтому возвращаем статическую категорию "Main Course" для совместимости
        с общим форматом проекта.
        """
        return "Main Course"
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Метод 1: Ищем "Время приготовления:" в параграфах
        for p in entry_content.find_all('p', limit=30):
            text = p.get_text()
            if 'Время приготовления:' in text:
                time_match = re.search(r'Время приготовления:\s*(\d+)\s*(мин|минут)', text, re.IGNORECASE)
                if time_match:
                    minutes = time_match.group(1)
                    return f"{minutes} minutes"
        
        # Метод 2: Извлекаем время из инструкций как fallback
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Ищем последнее упоминание времени в минутах в инструкциях
        # Паттерны: "30 минут", "запекать 20 минут", "готовить 15 минут"
        time_matches = list(re.finditer(r'(\d+)\s*минут', instructions, re.IGNORECASE))
        
        if time_matches:
            # Берем последнее найденное время (обычно это время запекания/готовки)
            last_match = time_matches[-1]
            minutes = last_match.group(1)
            return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (не предоставляется на сайте)"""
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (не предоставляется на сайте)"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок"""
        # Ищем последнюю строку инструкций, которая обычно содержит рекомендации
        # Сначала получаем весь текст инструкций из HTML
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Найдем параграф с "Приготовление:"
        preparation_tag = None
        for strong in entry_content.find_all('strong'):
            if 'Приготовление:' in strong.get_text():
                preparation_tag = strong.parent
                break
        
        if not preparation_tag:
            return None
        
        # Получаем весь текст
        html_content = str(preparation_tag)
        html_content = html_content.replace('<br>', ' ').replace('<br/>', ' ').replace('<br />', ' ')
        
        temp_soup = BeautifulSoup(html_content, 'lxml')
        text = self.clean_text(temp_soup.get_text())
        
        # Убираем "Приготовление:" из начала
        text = re.sub(r'^Приготовление:\s*', '', text, flags=re.IGNORECASE)
        
        # Разделяем на предложения
        sentences = re.split(r'\.\s+', text)
        
        # Ищем последнее предложение с рекомендациями
        for sentence in reversed(sentences):
            sentence = sentence.strip()
            if sentence and ('подойдет' in sentence.lower() or 'прекрасно' in sentence.lower()):
                # Добавляем точку в конце если её нет
                if not sentence.endswith('.'):
                    sentence += '.'
                return sentence
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из названия блюда"""
        # Берем ключевые слова из названия блюда
        dish_name = self.extract_dish_name()
        if not dish_name:
            return None
        
        # Разбиваем название на слова
        words = dish_name.lower().split()
        
        # Фильтруем общие слова и короткие слова
        tags = []
        
        for word in words:
            # Убираем знаки препинания
            word = re.sub(r'[^\w\-]', '', word)
            if word and word not in self.RUSSIAN_STOPWORDS and len(word) > 2:
                tags.append(word)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем изображения в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Найдем все img теги
            for img in entry_content.find_all('img'):
                # Приоритет: data-lazy-src, затем src
                url = img.get('data-lazy-src') or img.get('src')
                
                if url:
                    # Пропускаем SVG placeholders и дефолтные картинки ошибок
                    if url.startswith('data:image/svg') or 'podarok_korobka_bant' in url:
                        continue
                    
                    # Пропускаем очень маленькие изображения (вероятно иконки)
                    if url not in urls:
                        urls.append(url)
        
        # Ограничиваем до разумного количества (первые 10)
        if urls:
            urls = urls[:10]
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
    import os
    # Обрабатываем папку preprocessed/eda_vot-tac_ru
    preprocessed_dir = os.path.join("preprocessed", "eda_vot-tac_ru")
    
    # Проверяем существование директории
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(EdaVotTacExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python eda_vot-tac_ru.py")


if __name__ == "__main__":
    main()
