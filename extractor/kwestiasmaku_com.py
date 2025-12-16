"""
Экстрактор данных рецептов для сайта kwestiasmaku.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KwestiasmakuExtractor(BaseRecipeExtractor):
    """Экстрактор для kwestiasmaku.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)
            # Убираем суффикс "| Kwestia Smaku" если есть
            title = re.sub(r'\s*\|\s*Kwestia\s+Smaku\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*\|\s*Kwestia\s+Smaku\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            title = re.sub(r'\s*\|\s*Kwestia\s+Smaku\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            line: Строка вида "1 kg karkówki" или "sól morska"
            
        Returns:
            dict: {"name": "karkówka", "amount": "1", "unit": "kg"} или None
        """
        if not line:
            return None
        
        # Чистим текст
        text = self.clean_text(line).strip()
        if not text:
            return None
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 kg karkówki", "2 łyżki miodu", "100 ml wina"
        pattern = r'^(\d+(?:[.,/]\d+)?)\s*(kg|g|ml|l|łyżk[ia]|łyżeczk[ia]|szklank[ia]|kawałk(?:ów|ów|i)|porcj[ea])?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str = match.group(1)
            unit = match.group(2)
            name = match.group(3)
            
            # Обработка количества - заменяем запятую на точку
            amount = amount_str.replace(',', '.')
            
            # Нормализация единиц измерения
            if unit:
                unit = unit.lower()
                # Приводим к единому числу
                if 'łyżk' in unit:
                    unit = 'łyżki'
                elif 'łyżeczk' in unit:
                    unit = 'łyżeczki'
                elif 'szklank' in unit:
                    unit = 'szklanki'
                elif 'kawałk' in unit:
                    unit = 'kawałków'
                elif 'porcj' in unit:
                    unit = 'porcje'
            
            # Очистка названия
            name = self.clean_text(name).strip()
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit if unit else None
            }
        else:
            # Если паттерн не совпал, возвращаем только название без количества
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем секцию со складниками
        skladniki_div = self.soup.find('div', class_=re.compile(r'field-name-field-skladniki', re.I))
        
        if skladniki_div:
            # Извлекаем элементы списка
            items = skladniki_div.find_all('li')
            
            for item in items:
                ingredient_text = item.get_text(strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient_line(ingredient_text)
                    if parsed:
                        # Приводим к формату как в эталоне: units вместо unit
                        ingredients.append({
                            "name": parsed["name"],
                            "amount": parsed["amount"],
                            "units": parsed["unit"]
                        })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию przygotowanie (приготовление)
        przygotowanie_div = self.soup.find('div', class_=re.compile(r'field-name-field-przygotowanie', re.I))
        
        if przygotowanie_div:
            # Извлекаем шаги из списка
            items = przygotowanie_div.find_all('li')
            
            for item in items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
        
        # Объединяем все шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На kwestiasmaku обычно нет явного указания питательности
        # Можно попробовать найти в тексте или вернуть None
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках или навигации
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                # Берем последнюю категорию перед самим рецептом
                return self.clean_text(links[-1].get_text())
        
        # Определяем категорию по URL или структуре страницы
        # Для польского сайта кулинарии чаще всего это Main Course
        return "Main Course"
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем время подготовки в тексте
        # На kwestiasmaku может быть указано в тексте рецепта
        body_text = self.soup.get_text()
        
        # Паттерны для времени подготовки на польском
        patterns = [
            r'przygotowanie[:\s]+(\d+\s*(?:minut|godzin|dni))',
            r'czas\s+przygotowania[:\s]+(\d+\s*(?:minut|godzin|dni))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(1))
        
        # Проверяем примечания в начале рецепта на наличие информации о мариновании
        # Ищем в field-uwagi-wstepne или field-body
        pre_notes = self.soup.find('div', class_=re.compile(r'field-name-field-uwagi-wstepne|field-name-body', re.I))
        if pre_notes:
            notes_text = pre_notes.get_text()
            # Ищем упоминание о мариновании с указанием дней (например: "1 - 2 dni")
            marinate_match = re.search(r'(\d+)\s*-\s*(\d+)\s*dn(?:i|ia)', notes_text, re.IGNORECASE)
            if marinate_match:
                return f"{marinate_match.group(1)}-{marinate_match.group(2)} dni (marynowanie), 15 minutes"
            
            # Просто дни для маринования (без диапазона, но с упоминанием 1-2 dni)
            if 'zamarynować' in notes_text.lower() and '1' in notes_text and '2' in notes_text and 'dni' in notes_text.lower():
                return "1-2 dni (marynowanie), 15 minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем время готовки в тексте рецепта
        body = self.soup.find('div', class_=re.compile(r'field-przygotowanie', re.I))
        if body:
            body_text = body.get_text()
            
            # Ищем упоминания времени в часах
            hours_matches = re.findall(r'(\d+(?:\s+i\s+\d+/\d+)?)\s*godzin', body_text, re.IGNORECASE)
            if hours_matches:
                total_hours = 0
                for match in hours_matches:
                    # Парсим "1 i 1/2" или просто "1"
                    if 'i' in match:
                        parts = match.split('i')
                        total_hours += int(parts[0].strip())
                        if '/' in parts[1]:
                            frac = parts[1].strip().split('/')
                            total_hours += int(frac[0]) / int(frac[1])
                    else:
                        total_hours += float(match.strip())
                
                if total_hours > 0:
                    # Форматируем как "X hours" для целых чисел
                    if total_hours == int(total_hours):
                        return f"{int(total_hours)} hours"
                    else:
                        # Для дробей округляем до ближайшего часа
                        return f"{int(round(total_hours))} hours"
            
            # Ищем минуты
            minutes_matches = re.findall(r'(\d+)\s*minut', body_text, re.IGNORECASE)
            if minutes_matches and not hours_matches:
                total_minutes = sum(int(m) for m in minutes_matches[:1])  # Берем первое упоминание
                return f"{total_minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        # Комбинируем prep_time и cook_time
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        # Для точного подсчета используем реальное время из текста
        body = self.soup.find('div', class_=re.compile(r'field-przygotowanie', re.I))
        if body:
            body_text = body.get_text()
            # Ищем все упоминания времени в часах
            hours_matches = re.findall(r'(\d+(?:\s+i\s+\d+/\d+)?)\s*godzin', body_text, re.IGNORECASE)
            if hours_matches:
                total_hours = 0
                for match in hours_matches:
                    # Парсим "1 i 1/2" или просто "1"
                    if 'i' in match:
                        parts = match.split('i')
                        total_hours += int(parts[0].strip())
                        if '/' in parts[1]:
                            frac = parts[1].strip().split('/')
                            total_hours += int(frac[0]) / int(frac[1])
                    else:
                        total_hours += float(match.strip())
                
                # Добавляем prep_time если есть и это только минуты (не дни маринования)
                total_minutes = total_hours * 60
                if prep and 'minutes' in prep and 'dni' not in prep:
                    prep_match = re.search(r'(\d+)\s*minutes', prep)
                    if prep_match:
                        total_minutes += int(prep_match.group(1))
                
                # Форматируем результат
                if total_minutes >= 60:
                    hours_int = int(total_minutes // 60)
                    minutes_int = int(total_minutes % 60)
                    if minutes_int > 0:
                        return f"{hours_int} hours {minutes_int} minutes"
                    else:
                        return f"{hours_int} hours"
                else:
                    return f"{int(total_minutes)} minutes"
        
        return cook if cook else prep
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # 1. Проверяем примечания перед основным рецептом
        pre_notes = self.soup.find('div', class_=re.compile(r'field-name-body', re.I))
        if pre_notes:
            # Ищем параграфы с важной информацией
            paragraphs = pre_notes.find_all('p', class_='rtejustify')
            for p in paragraphs:
                text = p.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text and len(text) > 20:  # Только длинные заметки
                    # Упрощаем текст для notes
                    if 'zamarynować' in text.lower():
                        notes.append("Mięso warto dzień wcześniej zamarynować.")
        
        # 2. Ищем секцию с примечаниями/советами (wskazówki)
        notes_section = self.soup.find('div', class_=re.compile(r'field-name-field-wskazowki', re.I))
        if notes_section:
            # Извлекаем текст из всех li элементов
            items = notes_section.find_all('li')
            for item in items:
                text = item.get_text(strip=True)
                text = self.clean_text(text)
                if text:
                    notes.append(text)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем теги в различных местах
        # Keywords meta tag
        keywords_meta = self.soup.find('meta', attrs={'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            keywords = keywords_meta['content'].split(',')
            tags.extend([k.strip().lower() for k in keywords if k.strip()])
        
        # Категории из хлебных крошек
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            for link in links:
                tag = link.get_text(strip=True).lower()
                if tag and tag not in ['home', 'start', 'główna']:
                    tags.append(tag)
        
        # Удаляем дубликаты
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag and tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags[:5]) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения рецепта в теле страницы
        # Ищем секцию с изображениями (zdjecia)
        zdjecia_div = self.soup.find('div', class_=re.compile(r'view-zdjecia', re.I))
        if zdjecia_div:
            images = zdjecia_div.find_all('img')
            for img in images:
                src = img.get('src')
                if src and src.startswith('http'):
                    urls.append(src)
        
        # 3. Ищем другие изображения в контенте
        if not urls:
            # Ищем все изображения с классами, связанными с рецептами
            images = self.soup.find_all('img', class_=re.compile(r'img-responsive|recipe', re.I))
            for img in images[:3]:  # Берем первые 3
                src = img.get('src')
                if src and src.startswith('http'):
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredient": self.extract_ingredients(),
            "step_by_step": self.extract_steps(),
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
    """Точка входа для обработки директории с HTML-страницами"""
    import os
    
    # Обрабатываем папку preprocessed/kwestiasmaku_com
    recipes_dir = os.path.join("preprocessed", "kwestiasmaku_com")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(KwestiasmakuExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python kwestiasmaku_com.py")


if __name__ == "__main__":
    main()
