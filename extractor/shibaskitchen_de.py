"""
Экстрактор данных рецептов для сайта shibaskitchen.de
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ShibasKitchenExtractor(BaseRecipeExtractor):
    """Экстрактор для shibaskitchen.de"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
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
        
        # Форматируем время
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        
        return ' '.join(parts) if parts else None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Обработка @graph структуры
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Обработка простой структуры
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
                # Обработка списка
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Приоритет: JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффиксы типа "Rezept"
            name = re.sub(r'\s+(Rezept|Recipe).*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Fallback: h1
        h1 = self.soup.find('h1')
        if h1:
            name = h1.get_text(strip=True)
            name = re.sub(r'\s+[-–—]\s+.*$', '', name)  # Убираем подзаголовок после тире
            return self.clean_text(name)
        
        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            name = og_title['content']
            name = re.sub(r'\s+(Rezept|Recipe).*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s+-\s+.*$', '', name)  # Убираем суффикс после тире
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет: JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Fallback: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Fallback: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD в структурированном формате"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients = []
        raw_ingredients = recipe_data['recipeIngredient']
        
        if not isinstance(raw_ingredients, list):
            return None
        
        for ingredient_text in raw_ingredients:
            if not ingredient_text:
                continue
            
            # Парсим каждый ингредиент (может вернуть несколько)
            parsed_list = self.parse_ingredient(ingredient_text)
            if parsed_list:
                ingredients.extend(parsed_list)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> list:
        """
        Парсинг строки ингредиента в структурированный формат
        Может возвращать несколько ингредиентов если в строке "Salz & Pfeffer"
        
        Args:
            ingredient_text: Строка вида "500 g Blattspinat" или "1 Zwiebel" или "Salz & Pfeffer"
            
        Returns:
            list: Список словарей [{"name": "Blattspinat", "amount": "500", "units": "g"}]
        """
        if not ingredient_text:
            return []
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Специальная обработка для множественных ингредиентов
        # Паттерны: "Salz & Pfeffer", "Salz, Pfeffer und Paprikapulver", "Sesam und Schwarzkümmel"
        # Проверяем: нет чисел в начале или есть разделители между словами
        if re.search(r'(\s+(&|und|,)\s+)|([,&])', text, re.IGNORECASE):
            # Проверяем, есть ли в начале количество
            has_amount = re.match(r'^\d+', text.strip())
            
            # Если нет количества в начале, или есть фраза "nach Geschmack"/"zum Bestreuen"
            # это скорее всего список ингредиентов
            if not has_amount or 'nach geschmack' in text.lower() or 'zum bestreuen' in text.lower():
                # Убираем фразы вроде "nach Geschmack", "zum Bestreuen"
                text = re.sub(r'\(?\s*(nach geschmack|zum bestreuen|nach bedarf|nach belieben|optional)\s*\)?', '', text, flags=re.IGNORECASE).strip()
                
                # Разделяем по , & und
                # Сначала заменяем "und" на запятую для единого разделителя
                text = re.sub(r'\s+und\s+', ',', text, flags=re.IGNORECASE)
                text = re.sub(r'\s*&\s*', ',', text)
                
                parts = [p.strip() for p in text.split(',') if p.strip()]
                
                # Если получили несколько частей и это простые слова (не содержат единицы измерения)
                if len(parts) > 1:
                    result = []
                    for part in parts:
                        # Проверяем, есть ли в части единицы измерения
                        if re.match(r'^\d+\s+(g|kg|ml|l|tl|el|pck)', part, re.IGNORECASE):
                            # Это полноценный ингредиент, парсим рекурсивно
                            sub_ingredients = self._parse_single_ingredient(part)
                            if sub_ingredients:
                                result.extend(sub_ingredients)
                        else:
                            # Простое название без количества
                            result.append({
                                "name": part,
                                "amount": None,
                                "units": None
                            })
                    if result:
                        return result
        
        # Обычный случай - один ингредиент
        return self._parse_single_ingredient(text)
    
    def _parse_single_ingredient(self, text: str) -> list:
        """Парсинг одного ингредиента"""
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для немецких ингредиентов: "500 g Blattspinat" или "1 Zwiebel"
        # Формат: [количество] [единица] название
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|l|tl|el|prise|pck\.|pck|packung|dose|glas|stück|stck|scheiben?|zehen?|bund|zweige?|ganze?|halbe?|viertel)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return [{
                "name": text,
                "amount": None,
                "units": None
            }]
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            else:
                # Обработка чисел с запятой (немецкий формат)
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "nach Geschmack", "optional", "zum Bestreichen"
        name = re.sub(r'\b(nach geschmack|optional|zum bestreichen|nach bedarf|nach belieben)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return []
        
        return [{
            "name": name,
            "amount": amount,
            "units": unit
        }]
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and 'text' in step:
                    step_text = self.clean_text(step['text'])
                    if step_text:
                        steps.append(f"{idx}. {step_text}")
                elif isinstance(step, str):
                    step_text = self.clean_text(step)
                    if step_text:
                        steps.append(f"{idx}. {step_text}")
        elif isinstance(instructions, str):
            # Если это просто строка, разбиваем по предложениям или абзацам
            step_text = self.clean_text(instructions)
            if step_text:
                steps.append(f"1. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_json_ld()
        
        # Пытаемся найти категорию в JSON-LD
        if recipe_data:
            # Проверяем различные поля для категории
            for key in ['recipeCategory', 'category', 'keywords']:
                if key in recipe_data:
                    category = recipe_data[key]
                    if isinstance(category, str):
                        return self.clean_text(category)
                    elif isinstance(category, list):
                        return ', '.join([self.clean_text(c) for c in category if c])
        
        # Fallback: ищем в meta тегах
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes_list = []
        
        # 1. Ищем в JSON-LD (если есть)
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeNotes' in recipe_data:
            notes_text = self.clean_text(recipe_data['recipeNotes'])
            if notes_text:
                notes_list.append(notes_text)
        
        # 2. Ищем секцию с примечаниями в HTML
        notes_patterns = [
            'wprm-recipe-notes',
            'recipe-notes',
            r'^notes$',
            'tipps',
            'hinweise'
        ]
        
        for pattern in notes_patterns:
            notes_section = self.soup.find(class_=re.compile(pattern, re.I))
            if notes_section:
                # Извлекаем текст, убирая заголовок
                text = notes_section.get_text(separator=' ', strip=True)
                # Убираем заголовки
                text = re.sub(r'^(Notes?|Notizen|Hinweise?|Tipps?|Shibas\s+Notizen|Tipps?\s*&\s*Anmerkungen)[\s:]*', '', text, flags=re.IGNORECASE)
                text = self.clean_text(text)
                if text and text not in notes_list and len(text) > 30:
                    notes_list.append(text)
        
        # 3. Ищем в секциях FAQ / заголовках h2, содержащих "einfrieren" и подобные слова
        if not notes_list:
            h2_elements = self.soup.find_all('h2')
            for h2 in h2_elements:
                h2_text = h2.get_text(strip=True).lower()
                if any(keyword in h2_text for keyword in ['einfrieren', 'aufbewahren', 'lagern']):
                    # Берем следующий параграф после заголовка
                    next_p = h2.find_next('p')
                    if next_p:
                        text = self.clean_text(next_p.get_text(strip=True))
                        if text and len(text) > 30 and text not in notes_list:
                            # Берем только первые 1-2 предложения
                            sentences = re.split(r'[.!?]\s+', text)
                            short_note = '. '.join(sentences[:2])
                            if short_note and not short_note.endswith('.'):
                                short_note += '.'
                            notes_list.append(short_note)
                            break  # Берем только первую найденную заметку из FAQ
        
        # 4. Ищем важные советы в описаниях ингредиентов
        if not notes_list:
            ingredient_lis = self.soup.find_all('li')
            for li in ingredient_lis:
                li_text = li.get_text(separator=' ', strip=True)
                # Ищем предложения с "achte darauf" / "wichtig"
                if any(keyword in li_text.lower() for keyword in ['achte darauf', 'wichtig ist']):
                    sentences = re.split(r'[.!?]\s+', li_text)
                    for sentence in sentences:
                        if any(keyword in sentence.lower() for keyword in ['achte darauf', 'wichtig ist', 'damit sie nicht']):
                            text = self.clean_text(sentence)
                            if text and len(text) > 30 and text not in notes_list:
                                notes_list.append(text)
                                break
                    if notes_list:
                        break
        
        # Фильтруем заметки: убираем короткие фрагменты и нежелательные префиксы
        filtered_notes = []
        for note in notes_list:
            # Пропускаем очень короткие заметки или те, что содержат только количества
            if len(note) > 50 and not re.match(r'^(ca\.|etwa)?\s*\d+', note, re.IGNORECASE):
                # Убираем префиксы вроде "Shibas Notizen", "Tipps & Anmerkungen" в начале
                note = re.sub(r'^(Shibas?\s+Notizen?|Tipps?\s*&\s*Anmerkungen?|Hinweise?)[\s:]*', '', note, flags=re.IGNORECASE)
                note = note.strip()
                if note and len(note) > 50:
                    filtered_notes.append(note)
        
        # Объединяем все найденные заметки
        if filtered_notes:
            return ' '.join(filtered_notes[:2])  # Берем максимум 2 заметки
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_set = set()
        
        # 1. Пытаемся найти в JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Обычно keywords - это строка с разделителями
                tags_from_json = [k.strip() for k in re.split(r'[,;]', keywords) if k.strip()]
                tags_set.update(tags_from_json)
            elif isinstance(keywords, list):
                tags_set.update([self.clean_text(k) for k in keywords if k])
        
        # 2. Извлекаем из recipeCuisine (турецкая кухня, etc.)
        if recipe_data and 'recipeCuisine' in recipe_data:
            cuisine = recipe_data['recipeCuisine']
            if isinstance(cuisine, str):
                tags_set.add(self.clean_text(cuisine))
            elif isinstance(cuisine, list):
                tags_set.update([self.clean_text(c) for c in cuisine if c])
        
        # 3. Fallback: meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords_text = meta_keywords['content']
            tags_from_meta = [k.strip() for k in re.split(r'[,;]', keywords_text) if k.strip()]
            tags_set.update(tags_from_meta)
        
        # 4. Fallback: article:tag meta tags
        article_tags = self.soup.find_all('meta', property='article:tag')
        for tag in article_tags:
            if tag.get('content'):
                tags_set.add(self.clean_text(tag['content']))
        
        # Фильтрация и форматирование
        filtered_tags = []
        for tag in tags_set:
            # Пропускаем пустые и очень короткие теги
            if tag and len(tag) >= 3:
                filtered_tags.append(tag)
        
        if filtered_tags:
            return ', '.join(sorted(filtered_tags))
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Извлекаем из JSON-LD (приоритет)
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # 2. Fallback: og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # 3. Fallback: twitter:image
        if not urls:
            twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                urls.append(twitter_image['content'])
        
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
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка примеров из preprocessed/shibaskitchen_de"""
    import os
    
    # Путь относительно корня репозитория
    preprocessed_dir = os.path.join("preprocessed", "shibaskitchen_de")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ShibasKitchenExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Убедитесь, что вы запускаете скрипт из корня репозитория")


if __name__ == "__main__":
    main()
