"""
Экстрактор данных рецептов для сайта glossy.espreso.co.rs
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GlossyEspresoCoRsExtractor(BaseRecipeExtractor):
    """Экстрактор для glossy.espreso.co.rs"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Попробуем из тегов (обычно название блюда среди первых тегов)
        tags = self.extract_tags()
        if tags:
            # Разбираем теги
            tag_list = [t.strip() for t in tags.split(',')]
            # Ищем тег "Lazanje" или похожий (название блюда обычно среди первых)
            # Пропускаем общие теги типа "Recept"
            for tag in tag_list:
                tag_lower = tag.lower()
                if tag_lower not in ['recept', 'recepti', 'ideja za ručak', 'ideje za ručak']:
                    # Проверяем, что это похоже на название блюда (не слишком длинное)
                    if len(tag.split()) <= 3:
                        return tag
        
        # Если не получилось, ищем в заголовке h1 с itemprop="headline"
        h1 = self.soup.find('h1', itemprop='headline')
        if h1:
            text = self.clean_text(h1.get_text())
            # Извлекаем название блюда из заголовка
            # Обычно формат: "Описание: Recept za НАЗВАНИЕ которое..."
            # Попробуем извлечь упоминание рецепта
            match = re.search(r'(?:recept za |za )?([А-ЯЁа-яё\w\s-]+?)(?:\s+(?:koje|recept|который|которые|sa|od)|\s*$)', text, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(1))
            
            return text
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из title тега
        title_tag = self.soup.find('title')
        if title_tag and title_tag.string:
            return self.clean_text(title_tag.string)
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'Description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Из JSON-LD NewsArticle
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'NewsArticle':
                    if 'description' in data:
                        return self.clean_text(data['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def parse_ingredient_line(self, text: str) -> list:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "500 grama mesa" или "1 pakovanje lazanja"
            
        Returns:
            list: Список словарей [{"name": "mesa", "units": "grama", "amount": 500}] или None
        """
        if not text:
            return None
        
        # Чистим текст
        text = self.clean_text(text)
        
        # Проверяем, есть ли несколько ингредиентов через запятую
        # Например: "biljni začin, so, biber po ukusu"
        if ',' in text and not re.match(r'^\d', text):
            # Если начинается не с числа и есть запятые, разделяем
            parts = [p.strip() for p in text.split(',')]
            results = []
            for part in parts:
                parsed = self._parse_single_ingredient(part)
                if parsed:
                    results.extend(parsed if isinstance(parsed, list) else [parsed])
            return results if results else None
        
        return self._parse_single_ingredient(text)
    
    def _parse_single_ingredient(self, text: str) -> list:
        """Парсинг одного ингредиента"""
        # Заменяем дроби
        text = text.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
        text = text.replace('⅓', '0.33').replace('⅔', '0.67')
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "500 grama mesa", "1 pakovanje lazanja", "malo ulja"
        # Единицы измерения на сербском: grama/g, ml, šolje, kašike, komad, pakovanje, tegla, l, kg
        
        # Пробуем сначала дробь в начале (например, "1/2 šolje")
        pattern_fraction = r'^(\d+/\d+)\s+(grama?|gr?|ml|šolj[ea]|kašik[ea]|komada?|pakovanja?|tegl[ae]|litr[ae]?|kg|l)\s+(.+)$'
        match = re.match(pattern_fraction, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            parts = amount_str.split('/')
            amount = int(parts[0]) / int(parts[1])
            
            # Нормализуем единицы
            unit = self._normalize_unit(unit)
            
            return [{
                "name": name,
                "units": unit,
                "amount": amount
            }]
        
        # Пробуем числовое количество с единицей
        pattern1 = r'^(\d+(?:[.,]\d+)?)\s+(grama?|gr?|ml|šolj[ea]|kašik[ea]|komada?|pakovanja?|tegl[ae]|litr[ae]?|kg|l)\s+(.+)$'
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            amount = float(amount_str.replace(',', '.'))
            
            # Нормализуем единицы
            unit = self._normalize_unit(unit)
            
            return [{
                "name": name,
                "units": unit,
                "amount": int(amount) if amount == int(amount) else amount
            }]
        
        # Пробуем без единицы, только число
        pattern2 = r'^(\d+(?:[.,/]\d+)?)\s+(.+)$'
        match = re.match(pattern2, text, re.IGNORECASE)
        
        if match:
            amount_str, name = match.groups()
            
            # Обработка дробей в amount
            if '/' in amount_str:
                parts = amount_str.split('/')
                amount = int(parts[0]) / int(parts[1])
            else:
                amount = float(amount_str.replace(',', '.'))
            
            return [{
                "name": name,
                "units": 'komad',
                "amount": int(amount) if amount == int(amount) else amount
            }]
        
        # Если количество словесное (malo, po ukusu и т.д.) или его нет
        # Удаляем эти фразы из названия
        name = re.sub(r'\b(malo|po ukusu|po želji)\b', '', text, flags=re.IGNORECASE).strip()
        return [{
            "name": name if name else text,
            "units": None,
            "amount": None
        }]
    
    def _normalize_unit(self, unit: str) -> str:
        """Нормализация единиц измерения"""
        unit = unit.lower()
        if unit.startswith('gram') or unit == 'gr' or unit == 'g':
            return 'grama'
        elif unit.startswith('šolj'):
            return 'šolje'
        elif unit.startswith('kašik'):
            return 'kašike'
        elif unit.startswith('kom'):
            return 'komad'
        elif unit.startswith('pak'):
            return 'pakovanje'
        elif unit.startswith('tegl'):
            return 'tegla'
        return unit
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем параграф с текстом "Sastojci:"
        sastojci_p = None
        for p in self.soup.find_all('p'):
            p_text = p.get_text().lower()
            if 'sastojci' in p_text and (p.find('strong') or p.find('em')):
                sastojci_p = p
                break
        
        if sastojci_p:
            # Ищем следующий <ul> после этого параграфа
            current = sastojci_p.find_next_sibling()
            
            while current:
                if current.name == 'ul':
                    # Извлекаем все <li> из этого списка
                    for li in current.find_all('li', recursive=False):
                        # Извлекаем текст, убирая вложенные теги
                        text = li.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        
                        if text:
                            parsed_list = self.parse_ingredient_line(text)
                            if parsed_list:
                                ingredients.extend(parsed_list)
                    
                    # Проверяем, есть ли еще списки (для секций типа "Za crveni sos", "Za bešamel")
                    current = current.find_next_sibling()
                    if current and current.name == 'p':
                        # Проверяем, не началась ли секция "Priprema"
                        if 'priprema' in current.get_text().lower():
                            break
                        # Пропускаем заголовки подсекций (например, "Za bolonjeze")
                        current = current.find_next_sibling()
                    elif current and current.name == 'div':
                        # Пропускаем div-ы (например, related articles)
                        current = current.find_next_sibling()
                    elif current and current.name != 'ul':
                        break
                elif current.name == 'p':
                    # Пропускаем пустые параграфы (например, &nbsp;)
                    text = current.get_text(strip=True)
                    if not text or text == '\xa0':
                        current = current.find_next_sibling()
                        continue
                    # Проверяем, не началась ли секция "Priprema"
                    if 'priprema' in text.lower():
                        break
                    # Если это заголовок подсекции (например, "Za bolonjeze"), продолжаем
                    current = current.find_next_sibling()
                elif current.name == 'div':
                    # Пропускаем div-ы (например, related articles)
                    current = current.find_next_sibling()
                else:
                    current = current.find_next_sibling()
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем параграф с текстом "Priprema:"
        priprema_p = None
        for p in self.soup.find_all('p'):
            if p.find('strong') and 'priprema' in p.get_text().lower():
                priprema_p = p
                break
        
        if priprema_p:
            # Собираем все следующие параграфы до конца секции
            current = priprema_p.find_next_sibling()
            
            while current:
                if current.name == 'p':
                    text = current.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    
                    # Останавливаемся на секциях типа "Приятного аппетита" или новых заголовках
                    if text and not any(word in text.lower() for word in ['приятно', 'пријатно', 'извор', 'izvor']):
                        instructions.append(text)
                    elif text and any(word in text.lower() for word in ['приятно', 'пријатно']):
                        # Остановка на "Приятного аппетита"
                        break
                    
                    current = current.find_next_sibling()
                elif current.name in ['div', 'h2', 'h3']:
                    # Остановка на новых секциях
                    break
                else:
                    current = current.find_next_sibling()
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # По умолчанию для рецептов основных блюд
        return "Main Course"
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из текста инструкций"""
        instructions_text = self.extract_instructions()
        
        if not instructions_text:
            return None
        
        # Ищем упоминания времени в тексте
        # Паттерны: "oko sat vremena", "35-40 minuta", "oko pola sata", "oko 25 minuta"
        time_patterns = [
            (r'oko\s+sat\s+vremena', '60 minutes'),
            (r'oko\s+(\d+)\s+sata?', lambda m: f"{int(m.group(1)) * 60} minutes"),
            (r'(\d+)-(\d+)\s+minut', lambda m: f"{m.group(2)} minutes"),
            (r'oko\s+(\d+)\s+minut', lambda m: f"{m.group(1)} minutes"),
            (r'pola?\s+sata', '30 minutes'),
        ]
        
        # Собираем все времена, берем максимальное
        times = []
        for pattern, result in time_patterns:
            for match in re.finditer(pattern, instructions_text, re.IGNORECASE):
                if callable(result):
                    time_str = result(match)
                else:
                    time_str = result
                # Извлекаем число минут
                minutes = int(re.search(r'(\d+)', time_str).group(1))
                times.append((minutes, time_str))
        
        if times:
            # Возвращаем максимальное время
            return max(times, key=lambda x: x[0])[1]
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta-тега Keywords"""
        # Ищем в meta Keywords
        meta_keywords = self.soup.find('meta', {'name': 'Keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Фильтруем "Zdravi i srećni" и "Recepti" если они в начале
            tags = [tag.strip() for tag in keywords.split(',')]
            # Убираем общие теги
            filtered_tags = [tag for tag in tags if tag not in ['Zdravi i srećni', 'Zdravi i srecni', 'Recepti']]
            return ', '.join(filtered_tags) if filtered_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в og:image (главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', {'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем в JSON-LD NewsArticle
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'NewsArticle':
                    if 'image' in data:
                        img = data['image']
                        if isinstance(img, dict) and 'url' in img:
                            urls.append(img['url'])
                        elif isinstance(img, str):
                            urls.append(img)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            return ','.join(unique_urls) if unique_urls else None
        
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
            "prep_time": None,  # Не указано на сайте
            "cook_time": self.extract_cook_time(),
            "total_time": None,  # Не указано на сайте
            "notes": None,  # Не указано на сайте
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка директории с HTML файлами glossy.espreso.co.rs"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "glossy_espreso_co_rs"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(GlossyEspresoCoRsExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python glossy_espreso_co_rs.py")


if __name__ == "__main__":
    main()
