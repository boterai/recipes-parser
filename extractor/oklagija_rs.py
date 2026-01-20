"""
Экстрактор данных рецептов для сайта oklagija.rs
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class OklagijaExtractor(BaseRecipeExtractor):
    """Экстрактор для oklagija.rs"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем найти в заголовке h2.itemTitle
        title_elem = self.soup.find('h2', class_='itemTitle')
        if title_elem:
            return self.clean_text(title_elem.get_text())
        
        # Альтернативно - из meta тега title
        meta_title = self.soup.find('meta', attrs={'name': 'title'})
        if meta_title and meta_title.get('content'):
            return self.clean_text(meta_title['content'])
        
        # Или из og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в div.itemIntroText
        intro_div = self.soup.find('div', class_='itemIntroText')
        if intro_div:
            # Берем текст из параграфа внутри
            p = intro_div.find('p')
            if p:
                return self.clean_text(p.get_text())
            return self.clean_text(intro_div.get_text())
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Или из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_line(self, text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "100 g ovsenih pahuljica" или "1 kašičica praška"
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."} или None
        """
        if not text:
            return None
        
        # Чистим текст
        text = self.clean_text(text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "100 g ovsenih pahuljica", "1 kašičica praška", "2-3 pomorandže"
        # С учетом модификаторов: "1 dobro puna kašičica", "2 velike kašike"
        # Единицы измерения на сербском: g, ml, kg, kašičica, kašika, kesica, glavica и т.д.
        pattern = r'^([\d\s/.,\-]+)?\s*(?:dobro\s+puna|dobro\s+pune|mala|male|velika|velike|srednja|srednje)?\s*(g|ml|kg|l|kašičica|kašike|kašika|kesica|kesice|glavica|glavice|čaša|čaše|kocka|kocke|cm|mm|po\s+ukusu)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "units": None,
                "amount": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Убираем пробелы и оставляем диапазоны через дефис
            amount_str = re.sub(r'\s+', '', amount_str)
            
            # Если есть диапазон (2-3), берем первое значение
            if '-' in amount_str:
                amount_parts = amount_str.split('-')
                try:
                    val = float(amount_parts[0].replace(',', '.'))
                    # Конвертируем в int если это целое число
                    amount = int(val) if val.is_integer() else val
                except:
                    amount = amount_str
            else:
                try:
                    # Пробуем преобразовать в число
                    val = float(amount_str.replace(',', '.'))
                    # Конвертируем в int если это целое число
                    amount = int(val) if val.is_integer() else val
                except:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "po ukusu", "po želji" и т.д.
        name = re.sub(r'\b(po\s+ukusu|po\s+želji|optional|ako\s+želite)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Удаляем HTML теги если есть (например, <a>)
        name = re.sub(r'<[^>]+>', '', name)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем div.itemIngredients
        ingredients_div = self.soup.find('div', class_='itemIngredients')
        if not ingredients_div:
            return None
        
        # Извлекаем все параграфы
        paragraphs = ingredients_div.find_all('p')
        
        for p in paragraphs:
            # Пропускаем параграфы с классом "break" (это заголовки секций)
            if p.get('class') and 'break' in p.get('class'):
                continue
            
            # Получаем текст ингредиента
            text = p.get_text(separator=' ', strip=True)
            
            # Парсим ингредиент
            parsed = self.parse_ingredient_line(text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем div.itemSteps
        steps_div = self.soup.find('div', class_='itemSteps')
        if not steps_div:
            return None
        
        # Извлекаем все параграфы
        paragraphs = steps_div.find_all('p')
        
        steps = []
        for p in paragraphs:
            # Получаем текст шага
            text = p.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            if text:
                steps.append(text)
        
        # Объединяем все шаги в одну строку
        result = ' '.join(steps) if steps else None
        
        # Нормализуем пробелы после точек перед заглавными буквами
        if result:
            result = re.sub(r'\.([A-ZŠĐČĆŽ])', r'. \1', result)
        
        return result
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в div.itemCategory
        category_div = self.soup.find('div', class_='itemCategory')
        if category_div:
            # Берем ссылку внутри
            link = category_div.find('a')
            if link:
                return self.clean_text(link.get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Проверяем itemSteps на наличие упоминания времени подготовки
        steps_div = self.soup.find('div', class_='itemSteps')
        if steps_div:
            text = steps_div.get_text()
            
            # Специальный паттерн для "pola sata" (полчаса)
            if re.search(r'\bpola\s+sata\b', text, re.IGNORECASE):
                return "30 minutes"
            
            # Паттерны для времени подготовки (отстаивание, маринование и т.д.)
            prep_patterns = [
                r'odstoji\s+(\d+)[-\s]*(\d*)\s*(sat|sata|sati|minut|minuta|h|min)',
                r'ostavite\s+da\s+odstoji\s+(\d+)[-\s]*(\d*)\s*(sat|sata|sati|minut|minuta|h|min)',
                r'marinira\s+.*?(\d+)[-\s]*(\d*)\s*(sat|sata|sati|minut|minuta|h|min)',
                r'priprema[:\s]+(\d+)[-\s]*(\d*)\s*(sat|sata|sati|minut|minuta|h|min)',
            ]
            
            for pattern in prep_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    time_value1 = match.group(1).strip()
                    time_value2 = match.group(2).strip() if match.group(2) else None
                    time_unit = match.group(3).strip()
                    
                    # Если есть диапазон (1-2), берем максимальное значение
                    if time_value2:
                        time_value = time_value2
                    else:
                        time_value = time_value1
                    
                    # Нормализуем единицы и конвертируем в минуты
                    if time_unit in ['sat', 'sati', 'sata', 'h']:
                        # Конвертируем часы в минуты
                        total_minutes = int(time_value) * 60
                        return f"{total_minutes} minutes"
                    else:
                        return f"{time_value} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем упоминания времени в тексте рецепта
        steps_div = self.soup.find('div', class_='itemSteps')
        if steps_div:
            text = steps_div.get_text()
            
            # Паттерны для времени готовки
            cook_patterns = [
                r'pec[iì]te?[:\s]+.*?(\d+)\s*(minut|minuta|min)',
                r'na\s+\d+\s*stepeni.*?oko\s+(\d+)\s*(?:do\s+(\d+))?\s*(minut|minuta|min)',
                r'oko\s+(\d+)\s*do\s+(\d+)\s*(minut|minuta|min)',
                r'oko\s+(\d+)\s*(minut|minuta|min)',
            ]
            
            total_minutes = 0
            found_times = []
            
            for pattern in cook_patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    groups = match.groups()
                    time_val = None
                    
                    # Если есть диапазон (15 do 20), берем минимум (первое значение)
                    if len(groups) >= 2 and groups[1] and groups[1].isdigit():
                        # Это диапазон, берем первое значение
                        time_val = int(groups[0])
                    else:
                        # Берем последнюю группу с числом
                        for i in range(len(groups)-1, -1, -1):
                            if groups[i] and groups[i].isdigit():
                                time_val = int(groups[i])
                                break
                    
                    if time_val and time_val not in found_times:
                        found_times.append(time_val)
                        total_minutes += time_val
            
            if total_minutes > 0:
                return f"{total_minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Если есть prep_time и cook_time, суммируем
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа
            prep_match = re.search(r'(\d+)', prep)
            cook_match = re.search(r'(\d+)', cook)
            
            if prep_match and cook_match:
                prep_val = int(prep_match.group(1))
                cook_val = int(cook_match.group(1))
                
                total = prep_val + cook_val
                return f"{total} minutes"
        elif prep:
            return prep
        elif cook:
            return cook
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # На oklagija.rs нет явного раздела с заметками
        # Проверяем, может быть есть какие-то примечания в конце текста
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Первый приоритет - meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Теги разделены запятыми, добавляем пробел после запятой если его нет
            # Нормализуем: убираем пробелы вокруг запятых и добавляем один пробел после
            keywords = re.sub(r'\s*,\s*', ', ', keywords)
            return keywords
        
        # Второй вариант - из div.itemTagsBlock
        tags_block = self.soup.find('div', class_='itemTagsBlock')
        if tags_block:
            tag_links = tags_block.find_all('a')
            for link in tag_links:
                tag_text = self.clean_text(link.get_text())
                if tag_text:
                    tags.append(tag_text)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Ищем в meta image
        meta_image = self.soup.find('meta', attrs={'name': 'image'})
        if meta_image and meta_image.get('content'):
            url = meta_image['content']
            if url not in urls:
                urls.append(url)
        
        # Ищем изображение в div.itemImage
        image_div = self.soup.find('div', class_='itemImage')
        if image_div:
            img = image_div.find('img')
            if img and img.get('src'):
                src = img['src']
                # Преобразуем относительный URL в абсолютный
                if src.startswith('/'):
                    src = 'https://www.oklagija.rs' + src
                if src not in urls:
                    urls.append(src)
        
        # Возвращаем URLs через запятую без пробелов
        return ','.join(urls) if urls else None
    
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
    # Обрабатываем папку preprocessed/oklagija_rs
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "oklagija_rs"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(OklagijaExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python oklagija_rs.py")


if __name__ == "__main__":
    main()
