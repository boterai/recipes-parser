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
        # Извлекаем из title tag
        title_tag = self.soup.find('title')
        if title_tag:
            title = self.clean_text(title_tag.get_text())
            # Format: "Recept za X | Stil" or "Originalni... recept za X | Stil"
            if '|' in title:
                title = title.split('|')[0].strip()
            
            # Extract dish name from "recept za X" or "Recept za X"
            match = re.search(r'recept\s+za\s+(.+)', title, re.IGNORECASE)
            if match:
                dish_name = match.group(1).strip()
                # Capitalize first letter if it's a simple single-word dish
                words = dish_name.split()
                if len(words) == 1:
                    dish_name = dish_name.capitalize()
                return dish_name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            if len(desc) > 20 and desc != 'Stil 2024':
                return desc
        
        # Альтернатива - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if len(desc) > 20 and desc != 'Stil 2024':
                return desc
        
        return None
    
    def parse_ingredient_line(self, text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "200 g (1 ½ šolje) „00" mekog pšeničnog brašna"
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."}
        """
        if not text:
            return None
        
        text = self.clean_text(text)
        original_text = text
        
        # Удаляем запятые в конце
        text = re.sub(r',\s*$', '', text).strip()
        
        # Паттерн 1: число + единица + название
        # Примеры: "200 g (1 ½ šolje) „00" mekog pšeničnog brašna"
        pattern1 = r'^(\d+(?:[.,]\d+)?)\s+(g|gr|kg|ml|l|kašik[ea]?|čen[a]?|kom[a]?|glavica?|pcs?|pieces?|cloves?|tablespoons?)\s+(.+)'
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = amount_str.replace(',', '.')
            try:
                amount = float(amount)
                if amount == int(amount):
                    amount = int(amount)
            except:
                pass
            
            # Удаляем скобки из названия
            name = re.sub(r'\([^)]*\)', '', name).strip()
            
            # Очистка названия:
            # Для "„00" mekog pšeničnog brašna" → должно быть "brašno '00'"
            # Для "brašna od durum pšenice" → должно быть "brašno od durum pšenice"
            # Для "mlevenog mesa (govedina i svinjetina)" → должно быть "mleveno meso (govedina i svinjetina)"
            # Для "srednja glavica crnog luka, sitno seckana" → должно быть "crni luk"
            # Для "svežih ili suvih kora za lazanje" → должно быть "kore za lazanje"
            
            # Если название начинается с кавычек, перемещаем их в конец перед основным словом
            quote_match = re.match(r'^[„"]+(.+?)[""]+\s+(.+)', name)
            if quote_match:
                quote_text = quote_match.group(1)
                rest = quote_match.group(2)
                # "00" mekog pšeničnog brašna → brašno '00'
                # Берем последнее слово из rest как основное слово
                words = rest.split()
                if words:
                    main_word = words[-1]  # brašna
                    # Преобразуем в именительный падеж (упрощенно)
                    if main_word.endswith('a'):
                        main_word = main_word[:-1] + 'o'  # brašna → brašno
                    name = f"{main_word} '{quote_text}'"
            else:
                # Удаляем описательные прилагательные в начале
                name = re.sub(r'^(srednja|sitno\s+seckana|seckana|usitnjene|pečene|rendani|rendanog|sve[žz]i[h]?|suvo[g]?|crveno[g]?|belo[g]?|crno[g]?|mekog|pšeničnog|isečene|svežih|ili|suvih)\s+', '', name, flags=re.IGNORECASE)
                
                # Удаляем текст после запятой (обычно описание способа приготовления)
                name = re.sub(r',.*$', '', name)
                
                # Преобразуем из родительного падежа в именительный (упрощенно)
                # mesa → meso, luka → luk, pirea → pire, vina → vino, ulja → ulje
                # parmezana → parmezan, mocarele → mocarela, putera → puter, mleka → mleko
                name_words = name.split()
                if name_words:
                    last_word = name_words[-1]
                    # Простая эвристика для сербского языка
                    if last_word.endswith('a') and len(last_word) > 3:
                        # Проверяем, не артикль ли это (za, od, etc.)
                        if last_word not in ['za', 'od', 'na', 'sa', 'pa']:
                            # Преобразуем: mesa → meso, luka → luk, etc.
                            if last_word.endswith('oga'):
                                last_word = last_word[:-3] + 'i'  # crnog → crni
                            elif last_word.endswith('ega'):
                                last_word = last_word[:-3] + 'o'
                            elif last_word.endswith('ana'):
                                last_word = last_word[:-2]  # parmezana → parmezan
                            elif last_word.endswith('ela') or last_word.endswith('ela'):
                                pass  # mocarela остается
                            elif last_word.endswith('era'):
                                last_word = last_word[:-1]  # putera → puter
                            elif last_word.endswith('eka'):
                                last_word = last_word[:-1]  # mleka → mleko
                            elif last_word.endswith('sa'):
                                last_word = last_word[:-1]  # mesa → meso
                            elif last_word.endswith('ka') and len(last_word) > 4:
                                last_word = last_word[:-1]  # luka → luk
                            elif last_word.endswith('nja'):
                                last_word = last_word[:-1]  # brašnja → brašno (rare)
                            elif last_word.endswith('na'):
                                last_word = last_word[:-1] + 'o'  # pšeničnog → pšenično (rare)
                            elif last_word.endswith('ea'):
                                last_word = last_word[:-1]  # pirea → pire
                            elif last_word.endswith('ca'):
                                last_word = last_word[:-1]  # oraščića → oraščić
                            name_words[-1] = last_word
                            name = ' '.join(name_words)
                
                name = name.strip()
            
            # Нормализация единиц
            unit_map = {
                'gr': 'g',
                'kom': 'pieces',
                'koma': 'pieces',
                'pcs': 'pieces',
                'pc': 'pieces',
                'čen': 'cloves',
                'čena': 'cloves',
                'clove': 'cloves',
                'glavica': 'pieces',
                'kašika': 'tablespoons',
                'kašike': 'tablespoons',
                'tablespoon': 'tablespoons',
                'piece': 'pieces'
            }
            
            units = unit_map.get(unit.lower(), unit.lower())
            
            return {
                "name": name,
                "amount": amount,
                "units": units
            }
        
        # Паттерн 2: просто число + название (для "4 jaja od najmanje 70 g")
        pattern2 = r'^(\d+)\s+([a-zšđčćžа-я]+)'
        match2 = re.match(pattern2, text, re.IGNORECASE)
        if match2:
            amount_str, name = match2.groups()
            amount = int(amount_str)
            
            # Удаляем все после названия
            name = re.sub(r'\s+(od|za|sa|i|po|na).*$', '', name, flags=re.IGNORECASE)
            
            return {
                "name": name,
                "amount": amount,
                "units": "pieces"
            }
        
        # Паттерн 3: только название без количества (So i biber po ukusu)
        # Убираем фразы типа "po ukusu", "za dekoraciju"
        name = re.sub(r'\s+(po\s+ukusu|za\s+dekoraciju)$', '', text, flags=re.IGNORECASE)
        name = re.sub(r'\s+(i)\s+', ' ', name)  # "So i biber" → "So biber"
        name = name.strip()
        
        if name and len(name) > 1:
            # Разбиваем на отдельные ингредиенты если есть "i"
            if ' i ' in name.lower():
                # Возвращаем только первый
                name = name.split(' i ')[0].strip()
            
            return {
                "name": name,
                "amount": None,
                "units": None
            }
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Ищем все списки <ul> в документе
        for ul in self.soup.find_all('ul'):
            # Проверяем, содержит ли список ингредиенты
            ul_text = ul.get_text().lower()
            if any(word in ul_text for word in ['g ', 'ml ', 'brašn', 'mes', 'jaj', 'luk', 'putera', 'mleka', 'kašik']):
                for li in ul.find_all('li'):
                    ingredient_text = li.get_text()
                    if ingredient_text and len(ingredient_text.strip()) > 2:
                        # Проверяем, есть ли "i" в тексте (например, "So i biber")
                        if ' i ' in ingredient_text.lower() and 'po ukusu' in ingredient_text.lower():
                            # Разбиваем на отдельные ингредиенты
                            parts = re.split(r'\s+i\s+', ingredient_text.lower())
                            for part in parts:
                                part = re.sub(r'\s*(po\s+ukusu|za\s+dekoraciju).*$', '', part).strip()
                                part = re.sub(r',\s*$', '', part).strip()
                                if part and len(part) > 1:
                                    ingredients.append({
                                        "name": part,
                                        "amount": None,
                                        "units": None
                                    })
                        else:
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
        for p in self.soup.find_all('p'):
            text = self.clean_text(p.get_text())
            
            # Пропускаем пустые и короткие параграфы
            if not text or len(text) < 20:
                continue
            
            # Ищем параграфы с описанием приготовления (содержат глаголы действия)
            if any(word in text.lower() for word in ['zagrejati', 'dodati', 'peći', 'peci', 'mešati', 'kuvati', 'sipati', 'otopiti', 'naneti', 'umutiti', 'poređati', 'oblikovati']):
                # Удаляем префиксы типа "Priprema ragu sosa:" или "Priprema:"
                text = re.sub(r'^[^:]+:\s*', '', text)
                if text and len(text) > 20:
                    instructions.append(text)
        
        # Объединяем все инструкции
        if instructions:
            # Разбиваем на предложения и нумеруем
            all_text = ' '.join(instructions)
            # Разбиваем по точкам с заглавной буквой (начало нового предложения)
            sentences = re.split(r'\.\s+(?=[A-ZА-ЯŠĐČĆŽ])', all_text)
            numbered = []
            for idx, sentence in enumerate(sentences, 1):
                sentence = sentence.strip()
                if sentence:
                    if not sentence.endswith('.'):
                        sentence += '.'
                    numbered.append(f"{idx}. {sentence}")
            
            return ' '.join(numbered)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Определяем категорию по ключевым словам в заголовке
        title_tag = self.soup.find('title')
        h1 = self.soup.find('h1')
        
        text_to_check = ""
        if title_tag:
            text_to_check += " " + self.clean_text(title_tag.get_text()).lower()
        if h1:
            text_to_check += " " + self.clean_text(h1.get_text()).lower()
        
        # Ключевые слова для десертов
        dessert_keywords = ['kolač', 'torta', 'desert', 'sladol', 'čokolad', 'krem', 'puding', 'gurabije', 'keks', 'kolačić']
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
        times_found = []
        
        for p in self.soup.find_all('p'):
            text = self.clean_text(p.get_text())
            # Ищем паттерны времени, исключая температуру
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
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        tags = []
        
        # Ищем теги в ссылках с href="/tag/"
        for a in self.soup.find_all('a'):
            href = a.get('href', '')
            if '/tag/' in href:
                tag_text = self.clean_text(a.get_text())
                if tag_text and tag_text.lower() not in tags:
                    tags.append(tag_text.lower())
        
        if tags:
            return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в meta-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Проверяем, что это не логотип
            if not any(skip in url.lower() for skip in ['logo', 'icon']):
                urls.append(url)
        
        # Дополнительно ищем в <img> тегах статьи
        for img in self.soup.find_all('img'):
            src = img.get('src', '')
            if src and 'static-stil.kurir.rs' in src:
                # Пропускаем логотипы и иконки
                if any(skip in src.lower() for skip in ['logo', 'icon', 'povratak']):
                    continue
                if src not in urls:
                    urls.append(src)
                if len(urls) >= 3:
                    break
        
        if urls:
            # Убираем дубликаты, сохраняя порядок
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
