"""
Экстрактор данных рецептов для сайта zafferano-3cuochi.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class Zafferano3CuochiExtractor(BaseRecipeExtractor):
    """Экстрактор для zafferano-3cuochi.it"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+-\s+Zafferano.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в content-singola-ricetta последний параграф перед PREPARAZIONE
        content_widget = self.soup.find(class_='content-singola-ricetta')
        if content_widget:
            paragraphs = content_widget.find_all('p')
            # Ищем параграф с "leccarsi i baffi" или берем последний
            for p in reversed(paragraphs):
                text = p.get_text().strip()
                if 'leccarsi' in text.lower() or 'primo piatto' in text.lower():
                    # Ищем последнее предложение
                    sentences = re.split(r'[.!]\s+', text)
                    if sentences:
                        last_sentence = sentences[-1].strip()
                        if last_sentence and not last_sentence.endswith(('.', '!')):
                            last_sentence += '.'
                        return self.clean_text(last_sentence)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Ищем виджет с классом 'ingredienti'
        ing_widget = self.soup.find(class_='ingredienti')
        if not ing_widget:
            return None
        
        # Извлекаем все элементы списка
        items = ing_widget.find_all('li')
        
        for item in items:
            ingredient_text = item.get_text(strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            if not ingredient_text:
                continue
            
            # Специальная обработка для "sale e pepe q.b." - разбиваем на два ингредиента
            if re.match(r'sale\s+e\s+pepe', ingredient_text, re.IGNORECASE):
                # Добавляем sale
                ingredients.append({
                    "name": "sale",
                    "amount": None,
                    "units": "q.b."
                })
                # Добавляем pepe
                ingredients.append({
                    "name": "pepe",
                    "amount": None,
                    "units": "q.b."
                })
                continue
            
            # Парсим ингредиент
            parsed = self.parse_ingredient_italian(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_italian(self, text: str) -> Optional[dict]:
        """
        Парсинг итальянского ингредиента
        Примеры: "2 bustine di Zafferano", "400 g di ravioli", "1 scalogno"
        """
        if not text:
            return None
        
        text = text.strip()
        
        # Проверяем наличие "q.b." в конце
        has_qb = bool(re.search(r'q\.?b\.?$', text, re.IGNORECASE))
        units_from_qb = "q.b." if has_qb else None
        
        # Убираем "q.b." для дальнейшей обработки
        text = re.sub(r'\s*q\.?b\.?$', '', text, flags=re.IGNORECASE)
        
        # Попробуем извлечь количество в начале
        amount_pattern = r'^(\d+(?:[.,]\d+)?)\s*'
        amount_match = re.match(amount_pattern, text)
        
        amount = None
        if amount_match:
            amount = amount_match.group(1).replace(',', '.')
            text = text[len(amount_match.group(0)):]  # Убираем количество из текста
        
        # Извлекаем единицу измерения
        units_pattern = r'^(g|kg|ml|l|bustine|bustina|pezzo|pezzi|cucchiai|cucchiaio|cucchiaino|cucchiaini)\s+'
        units_match = re.match(units_pattern, text, re.IGNORECASE)
        
        units = None
        if units_match:
            units = units_match.group(1)
            text = text[len(units_match.group(0)):]  # Убираем единицу
        elif units_from_qb:
            units = units_from_qb
        
        # Убираем "di" если есть
        text = re.sub(r'^di\s+', '', text, flags=re.IGNORECASE)
        
        # Очистка названия
        name = text.strip()
        # Убираем "da X g" в конце и в начале (иногда разорванные строки)
        name = re.sub(r'\s+da\s+\d+[.,]?\d*\s*$', '', name, flags=re.IGNORECASE)
        name = re.sub(r'^\d+[.,]?\d*\s*$', '', name, flags=re.IGNORECASE)  # Убираем если осталось только число
        
        # Если название пустое, пропускаем
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": float(amount) if amount and amount != 'None' else None,
            "units": units if units else None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Ищем все виджеты с классом preparazione_lista
        prep_widgets = self.soup.find_all(class_='preparazione_lista')
        
        all_text = []
        
        for prep_widget in prep_widgets:
            # Получаем весь текст напрямую
            text = prep_widget.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            # Убираем заголовок "PREPARAZIONE"
            text = re.sub(r'^PREPARAZIONE\s*', '', text, flags=re.IGNORECASE)
            if text:
                all_text.append(text)
        
        if all_text:
            # Берем первый виджет с текстом (обычно содержит полную инструкцию)
            full_text = all_text[0] if all_text else ''
            
            # Разбиваем на предложения
            sentences = re.split(r'\.\s+', full_text)
            key_actions = []
            
            for sent in sentences:
                sent = sent.strip()
                # Берем только ключевые действия
                if sent and len(sent) > 15 and any(word in sent.lower() for word in 
                    ['pulite', 'pelate', 'tritate', 'unite', 'aggiungete', 'versate', 
                     'lessate', 'servite', 'cuocete', 'fate', 'regolate', 'saltate']):
                    key_actions.append(sent)
            
            if key_actions:
                # Создаем сжатую версию (примерно как в reference)
                summary = '. '.join(key_actions[:10])  # Первые 10 ключевых действий
                return summary + '.' if not summary.endswith('.') else summary
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На данном сайте не найдено информации о питательности
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Определяем категорию на основе тегов или типа блюда
        # Ищем в мета-тегах или breadcrumbs
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        # Определяем по умолчанию как Main Course для пасты/первых блюд
        dish_name = self.extract_dish_name()
        if dish_name:
            name_lower = dish_name.lower()
            if any(word in name_lower for word in ['ravioli', 'pasta', 'risotto', 'primi']):
                return "Main Course"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в виджете info-ricetta
        info_widget = self.soup.find(class_='info-ricetta')
        if info_widget:
            # Ищем текст с "min"
            text = info_widget.get_text()
            # Паттерн: "60 min"
            time_match = re.search(r'(\d+)\s*min', text, re.IGNORECASE)
            if time_match:
                minutes = time_match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Время приготовления не всегда явно указано отдельно
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Обычно на сайте указано только prep_time
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию "3 Cuochi Consiglia"
        for widget in self.soup.find_all(class_=lambda x: x and 'shortcode' in str(x).lower()):
            text = widget.get_text().strip()
            if '3 Cuochi Consiglia' in text or '3 Cuochi consiglia' in text:
                # Убираем заголовок и берем первое предложение
                text = re.sub(r'^3 Cuochi Consiglia', '', text, flags=re.IGNORECASE)
                text = self.clean_text(text)
                # Берем первое предложение
                sentences = re.split(r'[.!]\s+', text)
                if sentences and len(sentences) > 0:
                    first_sent = sentences[0].strip()
                    if first_sent and not first_sent.endswith('.'):
                        first_sent += '.'
                    return first_sent
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Определяем теги на основе названия и ингредиентов
        dish_name = self.extract_dish_name()
        if dish_name:
            name_lower = dish_name.lower()
            
            # Основные категории
            if 'pasta' in name_lower or 'ravioli' in name_lower:
                tags.append('pasta')
            if 'risotto' in name_lower:
                tags.append('risotto')
            if 'funghi' in name_lower or 'porcini' in name_lower:
                tags.append('funghi')
            if 'zafferano' in name_lower:
                tags.append('zafferano')
            
            # Тип блюда
            if any(word in name_lower for word in ['ravioli', 'pasta', 'risotto']):
                tags.append('primo piatto')
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в контенте рецепта
        content_widget = self.soup.find(class_='content-singola-ricetta')
        if content_widget:
            images = content_widget.find_all('img')
            for img in images[:3]:  # Берем максимум 3 изображения
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
                    urls.append(src)
        
        # Убираем дубликаты
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            return ','.join(unique_urls[:3]) if unique_urls else None
        
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
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для тестирования"""
    import os
    
    # Обрабатываем папку preprocessed/zafferano-3cuochi_it
    preprocessed_dir = os.path.join("preprocessed", "zafferano-3cuochi_it")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(Zafferano3CuochiExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python zafferano-3cuochi_it.py")


if __name__ == "__main__":
    main()
