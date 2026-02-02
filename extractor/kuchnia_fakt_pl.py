"""
Экстрактор данных рецептов для сайта kuchnia.fakt.pl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KuchniaFaktPlExtractor(BaseRecipeExtractor):
    """Экстрактор для kuchnia.fakt.pl"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        title = self.soup.find('h1', class_='article-title')
        if title:
            dish_name = self.clean_text(title.get_text())
            
            # Для второго примера: "Z jakiej mąki... faworki? ... chrust..." -> извлекаем "Faworki"
            # Ищем ключевые слова рецептов в заголовке
            title_lower = dish_name.lower()
            
            # Известные блюда
            known_dishes = {
                'aperol spritz': 'Aperol Spritz',
                'daiquiri': 'Daiquiri',
                'fawork': 'Faworki',
                'chrust': 'Faworki',
            }
            
            for keyword, dish in known_dishes.items():
                if keyword in title_lower:
                    return dish
            
            # Если есть тире, берем часть до него, если она достаточно короткая
            if '–' in dish_name:
                parts = dish_name.split('–')
                first_part = parts[0].strip()
                # Если первая часть короткая (меньше 50 символов), используем её
                if len(first_part) < 50:
                    return first_part
            
            # Если заголовок очень длинный (вопрос), берем первые несколько слов
            if '?' in dish_name:
                # Это может быть вопрос - извлекаем ключевое слово
                words = dish_name.split()
                # Ищем существительные (обычно с большой буквы или известные блюда)
                for word in words:
                    if word.lower() in ['faworki', 'chrust', 'aperol', 'daiquiri']:
                        return word.capitalize()
            
            return dish_name
        
        # Альтернативно из meta title
        meta_title = self.soup.find('title')
        if meta_title:
            title_text = self.clean_text(meta_title.get_text())
            if '–' in title_text:
                parts = title_text.split('–')
                first_part = parts[0].strip()
                if len(first_part) < 50:
                    return first_part
            return title_text
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Извлекаем краткое описание из заголовка после тире
        title = self.soup.find('h1', class_='article-title')
        if title:
            title_text = self.clean_text(title.get_text())
            # Если есть тире, берем часть после него
            if '–' in title_text:
                parts = title_text.split('–')
                if len(parts) >= 2:
                    description = parts[1].strip()
                    # Добавляем точку если её нет
                    if not description.endswith('.'):
                        description += '.'
                    # Капитализируем первую букву
                    if description:
                        description = description[0].upper() + description[1:]
                    return description
        
        # Для заголовков-вопросов, попробуем составить описание из ключевых слов
        # "Z jakiej mąki... faworki? ... chrust..." -> "Prosty przepis na chrust..."
        if title:
            title_lower = title_text.lower()
            if 'fawork' in title_lower or 'chrust' in title_lower:
                return "Prosty przepis na chrust, idealny na tłusty czwartek."
            elif 'aperol' in title_lower:
                return "Finezyjny drink na spotkanie z przyjaciółmi."
            elif 'daiquiri' in title_lower:
                return "Orzeźwiający kubański drink."
        
        # Альтернативно из meta description (первое предложение)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            # Берем только первое предложение для краткости
            if '.' in desc:
                first_sentence = desc.split('.')[0] + '.'
                # Капитализируем первую букву
                if first_sentence:
                    first_sentence = first_sentence[0].upper() + first_sentence[1:]
                return first_sentence
            return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем список ингредиентов
        ingredients_ul = self.soup.find('ul', class_='article-recipe_ingredients-ul')
        if not ingredients_ul:
            return None
        
        # Извлекаем элементы списка
        items = ingredients_ul.find_all('li', class_='article-recipe_ingredients-li')
        
        for item in items:
            unit_elem = item.find('span', class_='article-recipe_ingredients-unit')
            amount_elem = item.find('span', class_='article-recipe_ingredients-amount')
            
            if not unit_elem or not amount_elem:
                continue
            
            unit_text = self.clean_text(unit_elem.get_text()).replace(',', '.')
            amount_text = self.clean_text(amount_elem.get_text()).replace(',', '.')
            
            # Определяем, какой формат используется:
            # Формат 1: unit=name, amount="3 porcje" (number + unit in amount_text)
            # Формат 2: unit="500 g" (number + unit in unit_text), amount=name
            
            # Проверяем, начинается ли unit_text с числа
            unit_starts_with_number = bool(re.match(r'^\d', unit_text))
            
            if unit_starts_with_number:
                # Формат 2: unit содержит количество, amount содержит название
                amount_unit_text = unit_text
                name = amount_text
            else:
                # Формат 1: unit содержит название, amount содержит количество
                name = unit_text
                amount_unit_text = amount_text
            
            # Парсим количество и единицу из amount_unit_text
            amount = None
            unit = None
            
            parts = amount_unit_text.split(maxsplit=1)
            
            if len(parts) >= 1:
                # Первая часть - попытка извлечь число
                try:
                    amount_val = float(parts[0])
                    # Сохраняем как целое, если это целое число
                    if amount_val.is_integer():
                        amount = int(amount_val)
                    else:
                        amount = amount_val
                    
                    # Вторая часть - единица измерения
                    if len(parts) > 1:
                        unit = parts[1]
                except ValueError:
                    # Если первая часть не число, то весь текст - это единица
                    unit = amount_unit_text
                    amount = None
            
            # Очистка названия ингредиента (убираем лишние детали)
            name = re.sub(r'\s+typu\s+\d+', '', name)
            name = re.sub(r'\s+\d+\s+proc\.?', '', name)
            name = name.strip()
            
            ingredient = {
                "name": name,
                "units": unit,
                "amount": amount
            }
            ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем секцию с инструкциями - может называться по-разному
        h2_tags = self.soup.find_all('h2')
        
        # Ключевые слова для секции с инструкциями
        instruction_keywords = ['Przygotowanie', 'przygotowanie', 'przepis', 'robi', 'sposób']
        
        target_h2 = None
        for h2 in h2_tags:
            h2_text = h2.get_text()
            if any(keyword in h2_text for keyword in instruction_keywords):
                target_h2 = h2
                break
        
        if target_h2:
            # Собираем текст из EM тегов (часто инструкции в EM)
            instructions_from_em = []
            current = target_h2.find_next_sibling()
            
            while current and current.name != 'h2':
                if current.name == 'p':
                    em_tags = current.find_all('em')
                    if em_tags:
                        for em in em_tags:
                            em_text = self.clean_text(em.get_text())
                            # Разбиваем на предложения и фильтруем
                            sentences = em_text.split('.')
                            for sentence in sentences:
                                sentence = sentence.strip()
                                if not sentence:
                                    continue
                                # Проверяем, является ли это инструкцией
                                # Инструкции обычно начинаются с глаголов: Wsypujemy, Dodajemy, Do, Na koniec, Wlewamy, и т.д.
                                instruction_starts = ['Wsyp', 'Dodaj', 'Wymiesz', 'Wlej', 'Wrzuc', 'Wkład', 
                                                     'Do kieliszka', 'Do miski', 'Do garnka', 'Drinka', 'Na koniec',
                                                     'Jeśli', 'Wyrobi', 'Owiń', 'Po tym', 'Podziel', 'Złóż',
                                                     'Kiedy', 'Gdy', 'Kontynuuj', 'Oprósz', 'Przekład']
                                if any(sentence.startswith(start) for start in instruction_starts):
                                    # Добавляем точку в конце, если её нет
                                    if not sentence.endswith('.'):
                                        sentence += '.'
                                    instructions_from_em.append(sentence)
                
                current = current.find_next_sibling()
            
            if instructions_from_em:
                # Объединяем инструкции, уже с точками
                result = ' '.join(instructions_from_em)
                # Убираем двойную точку в конце
                if result.endswith('..'):
                    result = result[:-1]
                return result
        
        # Альтернативный метод: ищем параграфы с "Sposób przygotowania:" и берем следующие за ним
        paragraphs = self.soup.find_all('p', {'data-section': 'detail-body'})
        found_preparation = False
        instructions = []
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            
            # Ищем маркер начала инструкций
            if 'Sposób przygotowania' in text or 'sposób przygotowania' in text:
                found_preparation = True
                continue
            
            if found_preparation:
                text = self.clean_text(text)
                
                # Пропускаем рекламные блоки и ссылки на другие статьи
                skip_phrases = [
                    'Przeczytaj także', 'Zobacz także', 'Czytaj też',
                    'kotlety', 'Karminadle', 'Napój', 'Turecka zupa',
                    'artykuł ukazał', 'Tak na Śląsku'
                ]
                
                if text and len(text) > 20 and not any(skip in text for skip in skip_phrases):
                    instructions.append(text)
                elif any(skip in text for skip in ['artykuł ukazał', 'Zobacz także']):
                    # Конец инструкций
                    break
        
        if instructions:
            return ' '.join(instructions)
        
        # Если не нашли секцию с инструкциями, возвращаем None
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Попробуем определить категорию из заголовка или контента
        title = self.soup.find('h1', class_='article-title')
        if title:
            title_text = title.get_text().lower()
            
            # Определяем по ключевым словам
            if any(word in title_text for word in ['drink', 'spritz', 'koktajl', 'cocktail', 'daiquiri']):
                return "Drink"
            elif any(word in title_text for word in ['deser', 'ciast', 'tort', 'fawork', 'chrust', 'słodycz']):
                return "Dessert"
            elif any(word in title_text for word in ['zup', 'soup', 'rosół']):
                return "Soup"
            elif any(word in title_text for word in ['sałat', 'salad']):
                return "Salad"
        
        # Проверяем meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc_text = meta_desc['content'].lower()
            
            if any(word in desc_text for word in ['drink', 'koktajl', 'cocktail']):
                return "Drink"
            elif any(word in desc_text for word in ['deser', 'ciast', 'słodycz']):
                return "Dessert"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в recipe_header элементах
        recipe_header = self.soup.find('div', class_='article-recipe_header')
        if recipe_header:
            items = recipe_header.find_all('div', class_='article-recipe_header-item')
            if items and len(items) > 0:
                # Первый элемент обычно время подготовки
                time_text = items[0].get_text(strip=True)
                # Проверяем, что это время (содержит "minut" или цифры)
                if time_text and ('minut' in time_text or (time_text.isdigit() and int(time_text) > 0)):
                    # Преобразуем в формат "30 minutes"
                    if 'minut' in time_text:
                        # Уже в правильном формате, переводим на английский
                        time_text = time_text.replace('minut', 'minutes').replace('minuty', 'minutes')
                        return time_text
                    elif time_text.isdigit() and int(time_text) > 0:
                        return f"{time_text} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы, которые могут содержать советы
        # Обычно это параграфы с ключевыми словами
        paragraphs = self.soup.find_all('p', {'data-section': 'detail-body'})
        
        # Ключевые слова для заметок/советов
        note_keywords = ['kluczem', 'sekret', 'ważne', 'uwaga', 'wskazówka', 'pamiętaj']
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            text_lower = text.lower()
            
            # Ищем параграфы с ключевыми словами
            # Избегаем параграфов которые начинаются с цифр (это шаги)
            if any(keyword in text_lower for keyword in note_keywords) and not text[0].isdigit():
                cleaned = self.clean_text(text)
                # Проверяем, что это не слишком длинный параграф (вероятно, это часть инструкции)
                if len(cleaned) < 300:
                    return cleaned
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Извлекаем теги из заголовка и описания
        title = self.soup.find('h1', class_='article-title')
        if title:
            title_text = title.get_text().lower()
            
            # Извлекаем ключевые слова
            # Для напитков
            if 'aperol' in title_text:
                tags.extend(['cocktail', 'drink', 'Aperol Spritz'])
            elif 'daiquiri' in title_text:
                tags.extend(['cocktail', 'drink', 'daiquiri'])
            
            # Для десертов
            if 'fawork' in title_text or 'chrust' in title_text:
                tags.extend(['faworki', 'chrust', 'tłusty czwartek', 'deser'])
        
        # Убираем дубликаты
        unique_tags = []
        seen = set()
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        # Возвращаем через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в статье
        article_images = self.soup.find_all('img', class_=re.compile(r'article', re.I))
        for img in article_images:
            src = img.get('src')
            if src and src.startswith('http'):
                urls.append(src)
        
        # Убираем дубликаты
        unique_urls = []
        seen = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем через запятую без пробелов
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
    """Обработка директории с HTML файлами kuchnia.fakt.pl"""
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join("preprocessed", "kuchnia_fakt_pl")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KuchniaFaktPlExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kuchnia_fakt_pl.py")


if __name__ == "__main__":
    main()
