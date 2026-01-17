"""
Экстрактор данных рецептов для сайта stil.kurir.rs
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class StilKurirExtractor(BaseRecipeExtractor):
    """Экстрактор для stil.kurir.rs"""
    
    def __init__(self, html_path: str):
        """
        Инициализация экстрактора для stil.kurir.rs
        
        Args:
            html_path: Путь к HTML файлу
        """
        super().__init__(html_path)
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из canonical URL или title tag
        title_tag = self.soup.find('title')
        if title_tag:
            title = self.clean_text(title_tag.get_text())
            # Формат: "Originalni italijanski recept za lazanje | Stil"
            # Берем часть до первого разделителя
            if '|' in title:
                title = title.split('|')[0].strip()
            # Извлекаем ключевое слово (обычно последнее существительное)
            # Ищем паттерн "recept za X" или просто "X"
            if 'recept za' in title.lower():
                # Берем всё после "recept za"
                parts = re.split(r'recept\s+za\s+', title, flags=re.IGNORECASE)
                if len(parts) > 1:
                    return parts[-1].strip()
            # Если есть двоеточие, берем первое существительное после него
            if ':' in title:
                after_colon = title.split(':')[-1].strip()
                # Извлекаем первое значимое слово
                words = after_colon.split()
                if words:
                    return words[0].capitalize()
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            text = self.clean_text(h1.get_text())
            # Ищем "recept za X"
            if 'recept za' in text.lower():
                parts = re.split(r'recept\s+za\s+', text, flags=re.IGNORECASE)
                if len(parts) > 1:
                    return parts[-1].strip()
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем найти в <meta name="title">
        meta_title = self.soup.find('meta', {'name': 'title'})
        if meta_title and meta_title.get('content'):
            desc = self.clean_text(meta_title['content'])
            if len(desc) > 20:
                return desc
        
        # Ищем в og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            # Проверяем, что это не просто "Stil 2024"
            if len(desc) > 20 and desc != 'Stil 2024':
                return desc
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            if len(desc) > 20 and desc != 'Stil 2024':
                return desc
        
        return None
    
    def parse_ingredient_line(self, text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "200 g brašna" или "2 čena belog luka"
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."}
        """
        if not text:
            return None
        
        text = self.clean_text(text)
        
        # Паттерн: число + единица + название
        # Примеры: "200 g brašna", "500 ml mleka", "2 kašike maslinovog ulja"
        pattern = r'^(\d+(?:[.,]\d+)?)\s*(g|gr|kg|ml|l|kašik[ea]?|čen[a]?|kom[a]?|pieces?|pcs|tablespoons?|teaspoons?|tbsps?|tsps?|šolj[ea]?|cups?)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = amount_str.replace(',', '.')
            try:
                # Пробуем преобразовать в число
                amount = float(amount)
                if amount == int(amount):
                    amount = int(amount)
            except:
                pass
            
            # Очистка названия
            # Удаляем скобки и содержимое
            name = re.sub(r'\([^)]*\)', '', name)
            # Удаляем запятые в конце
            name = re.sub(r',\s*$', '', name)
            name = name.strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit if unit else None
            }
        else:
            # Если паттерн не совпал, возвращаем только название
            # Убираем запятые в конце
            name = re.sub(r',\s*$', '', text)
            return {
                "name": name.strip(),
                "amount": None,
                "units": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Ищем все списки <ul> в документе
        for ul in self.soup.find_all('ul'):
            # Проверяем, содержит ли список ингредиенты (по ключевым словам)
            ul_text = ul.get_text().lower()
            if any(word in ul_text for word in ['g ', 'ml ', 'brašn', 'mes', 'jaj', 'luk', 'putera', 'mleka']):
                for li in ul.find_all('li'):
                    ingredient_text = self.clean_text(li.get_text())
                    if ingredient_text and len(ingredient_text) > 2:
                        parsed = self.parse_ingredient_line(ingredient_text)
                        if parsed and parsed.get('name'):
                            ingredients.append(parsed)
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем параграфы с инструкциями
        # Обычно начинаются с "Priprema:" или содержат нумерацию
        for p in self.soup.find_all('p'):
            text = self.clean_text(p.get_text())
            
            # Пропускаем пустые и короткие параграфы
            if not text or len(text) < 10:
                continue
            
            # Если это заголовок раздела (например, "Priprema:"), пропускаем
            if text.endswith(':') and len(text) < 50:
                continue
            
            # Ищем параграфы с описанием приготовления
            if any(word in text.lower() for word in ['zagrejati', 'dodati', 'peći', 'mešati', 'kuvati', 'sipati', 'otopiti', 'naneti']):
                # Удаляем префиксы типа "Priprema ragu sosa:"
                text = re.sub(r'^[^:]+:\s*', '', text)
                if text and len(text) > 20:
                    instructions.append(text)
        
        # Объединяем все инструкции
        if instructions:
            # Разбиваем на предложения и нумеруем
            all_text = ' '.join(instructions)
            # Разбиваем по точкам с заглавной буквой
            sentences = re.split(r'\.\s+(?=[A-ZА-Я])', all_text)
            numbered = []
            for idx, sentence in enumerate(sentences, 1):
                sentence = sentence.strip()
                if sentence and not sentence.endswith('.'):
                    sentence += '.'
                if sentence:
                    numbered.append(f"{idx}. {sentence}")
            
            return ' '.join(numbered)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Пытаемся определить категорию по ключевым словам в заголовке/описании
        title_tag = self.soup.find('title')
        h1 = self.soup.find('h1')
        
        text_to_check = ""
        if title_tag:
            text_to_check += " " + self.clean_text(title_tag.get_text()).lower()
        if h1:
            text_to_check += " " + self.clean_text(h1.get_text()).lower()
        
        # Ключевые слова для десертов
        dessert_keywords = ['kolač', 'torta', 'desert', 'sladol', 'čokolad', 'krem', 'puding', 'gurabije', 'keks']
        if any(keyword in text_to_check for keyword in dessert_keywords):
            return "Dessert"
        
        # Ключевые слова для закусок/салатов
        appetizer_keywords = ['salat', 'predjelo', 'zalogaj']
        if any(keyword in text_to_check for keyword in appetizer_keywords):
            return "Appetizer"
        
        # По умолчанию главное блюдо
        return "Main Course"
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем упоминания времени в тексте
        # Приоритет: более длинные периоды (30-40 минут важнее 10 минут)
        times_found = []
        
        for p in self.soup.find_all('p'):
            text = self.clean_text(p.get_text())
            # Ищем паттерны типа "30-40 minuta", "20 min", "180°C" (температура не время)
            # Ищем все упоминания времени
            time_matches = re.finditer(r'(\d+(?:-\d+)?)\s*(min(?:ut[ea]?)?|h)(?!\s*°)', text, re.IGNORECASE)
            for time_match in time_matches:
                time_val = time_match.group(1)
                unit = time_match.group(2)
                if 'min' in unit.lower():
                    times_found.append((time_val, "minutes"))
                elif unit.lower() == 'h':
                    times_found.append((time_val, "hours"))
        
        # Выбираем самое длинное время (обычно это общее время готовки)
        if times_found:
            # Сортируем по длительности (если есть диапазон, берем максимум)
            def get_max_time(time_str):
                if '-' in time_str:
                    return int(time_str.split('-')[1])
                return int(time_str)
            
            times_found.sort(key=lambda x: get_max_time(x[0]), reverse=True)
            time_val, unit = times_found[0]
            return f"{time_val} {unit}"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Обычно не указано явно
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Обычно не указано явно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы с советами или примечаниями
        for p in self.soup.find_all('p'):
            text = self.clean_text(p.get_text())
            # Ищем советы (обычно короткие фразы)
            if text and 10 < len(text) < 100:
                # Проверяем, не является ли это инструкцией
                if not any(word in text.lower() for word in ['zagrejati', 'dodati', 'peći', 'mešati']):
                    # Проверяем на характерные фразы заметок
                    if any(word in text.lower() for word in ['savršen', 'ukusn', 'mogu', 'trebalo']):
                        return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        tags = []
        
        # Ищем теги в ссылках
        for a in self.soup.find_all('a'):
            href = a.get('href', '')
            if '/tag/' in href:
                tag_text = self.clean_text(a.get_text())
                if tag_text and tag_text not in tags:
                    tags.append(tag_text.lower())
        
        if tags:
            return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в meta-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # Ищем изображения в <picture> и <img> тегах
        for img in self.soup.find_all('img'):
            src = img.get('src')
            if src and 'static-stil.kurir.rs' in src:
                if src not in urls:
                    urls.append(src)
                if len(urls) >= 3:
                    break
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # По умолчанию обрабатываем папку preprocessed/stil_kurir_rs
    recipes_dir = os.path.join("preprocessed", "stil_kurir_rs")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(StilKurirExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python stil_kurir_rs.py")


if __name__ == "__main__":
    main()
