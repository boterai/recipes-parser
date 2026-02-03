"""
Экстрактор данных рецептов для сайта avmarket.lt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class AvmarketLtExtractor(BaseRecipeExtractor):
    """Экстрактор для avmarket.lt"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = self.clean_text(og_title['content'])
            # Убираем суффиксы типа " - AV MARKET"
            title = re.sub(r'\s*-\s*AV\s+MARKET.*$', '', title, flags=re.IGNORECASE)
            # Убираем дополнительные описания после двоеточия
            title = re.sub(r':\s+.*$', '', title)
            return title
        
        # Ищем первый h1 в основном контенте
        h1_tags = self.soup.find_all('h1')
        for h1 in h1_tags:
            text = self.clean_text(h1.get_text())
            # Пропускаем технические заголовки (consent dialog, prekiniai zenklai, etc.)
            if text and len(text) > 10 and 'consent' not in text.lower() and 'prekiniai' not in text.lower():
                # Убираем дополнительные описания после двоеточия
                text = re.sub(r':\s+.*$', '', text)
                return text
        
        # Альтернативно - из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            title = self.clean_text(title_tag.get_text())
            # Убираем суффиксы типа " - AV MARKET"
            title = re.sub(r'\s*-\s*AV\s+MARKET.*$', '', title, flags=re.IGNORECASE)
            # Убираем дополнительные описания после двоеточия
            title = re.sub(r':\s+.*$', '', title)
            return title
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет 1: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            if desc and len(desc) > 20:
                return desc
        
        # Приоритет 2: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if desc and len(desc) > 20:
                return desc
        
        # Приоритет 3: первый параграф после h1
        h1 = self.soup.find('h1')
        if h1:
            # Ищем следующий элемент p
            next_elem = h1.find_next('p')
            if next_elem:
                text = self.clean_text(next_elem.get_text())
                # Проверяем, что это не слишком короткий текст
                if text and len(text) > 20:
                    return text
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Dict[str, Optional[str]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "Булвės: 6 vnt." или "Pievagrybiai"
            
        Returns:
            Словарь с полями name, amount, units
        """
        ingredient_text = self.clean_text(ingredient_text)
        
        # Паттерн: "Name: amount units" или "Name: units"
        match = re.match(r'^(.+?):\s*(.+)$', ingredient_text)
        
        if match:
            name = self.clean_text(match.group(1))
            quantity_part = self.clean_text(match.group(2))
            
            # Пытаемся извлечь количество и единицы
            # Паттерн: число (может быть с дробью или диапазоном) + единицы
            qty_match = re.match(r'^([\d\s,./\-]+)\s*(.*)$', quantity_part)
            
            if qty_match:
                amount = self.clean_text(qty_match.group(1))
                units = self.clean_text(qty_match.group(2)) if qty_match.group(2) else None
                return {
                    "name": name,
                    "units": units,
                    "amount": amount
                }
            else:
                # Только единицы без количества
                return {
                    "name": name,
                    "units": quantity_part if quantity_part else None,
                    "amount": None
                }
        else:
            # Ингредиент без количества
            return {
                "name": ingredient_text,
                "units": None,
                "amount": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем первый h2 с "Ingredientai:" или секцией ингредиентов
        h2_tags = self.soup.find_all('h2')
        
        for h2 in h2_tags:
            h2_text = self.clean_text(h2.get_text())
            
            # Проверяем, что это секция ингредиентов
            if h2_text and ('ingredientai' in h2_text.lower() or
                           (h2_text.endswith(':') and any(keyword in h2_text.lower() 
                            for keyword in ['kotletams', 'padažui', 'kukuliams', 'sriubai']))):
                
                # Ищем следующий ul после этого h2
                next_ul = h2.find_next_sibling('ul')
                if next_ul:
                    items = next_ul.find_all('li', recursive=False)
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                    
                    # Проверяем, нашли ли мы хотя бы несколько ингредиентов
                    # Если да, продолжаем искать другие секции того же рецепта
                    if ingredients:
                        # Ищем следующий h2
                        next_h2 = h2.find_next_sibling('h2')
                        
                        # Если следующий h2 также секция ингредиентов того же рецепта
                        # (например, "Padažui:"), продолжаем
                        if next_h2:
                            next_h2_text = self.clean_text(next_h2.get_text())
                            if next_h2_text and next_h2_text.endswith(':') and any(keyword in next_h2_text.lower() 
                                for keyword in ['kotletams', 'padažui', 'kukuliams', 'sriubai', 'ingredientai']):
                                # Это еще одна секция ингредиентов того же рецепта, продолжаем цикл
                                continue
                            else:
                                # Это уже другой раздел (Gaminimas: или новый рецепт), прекращаем
                                break
                        else:
                            # Нет следующего h2, прекращаем
                            break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        steps = []
        
        # Ищем секции с инструкциями для первого рецепта
        # Обычно это h3 с текстом "Gaminimo eiga:" после первого рецепта
        h2_tags = self.soup.find_all('h2')
        h3_tags = self.soup.find_all('h3')
        
        # Флаг, указывающий, что мы нашли первый рецепт
        found_first_recipe = False
        
        # Сначала найдем первый рецепт
        for h2 in h2_tags:
            h2_text = self.clean_text(h2.get_text())
            if h2_text and not h2_text.endswith(':') and len(h2_text) > 10:
                found_first_recipe = True
                break
        
        # Ищем секцию с инструкциями (обычно это первый h3 с "Gaminimo eiga:")
        for h3 in h3_tags:
            h3_text = self.clean_text(h3.get_text())
            
            # Проверяем, что это секция с инструкциями
            if h3_text and ('gaminimo' in h3_text.lower() or 'gaminimas' in h3_text.lower()):
                
                # Ищем следующий ol после этого h3
                next_ol = h3.find_next_sibling('ol')
                if next_ol:
                    items = next_ol.find_all('li', recursive=False)
                    for item in items:
                        step_text = item.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        if step_text:
                            steps.append(step_text)
                    # Берем только первую секцию с инструкциями
                    break
        
        # Если шаги не найдены через h3, ищем через h2
        if not steps:
            for h2 in h2_tags:
                h2_text = self.clean_text(h2.get_text())
                
                if h2_text and ('gaminimas' in h2_text.lower() or 'gaminimo' in h2_text.lower()):
                    next_ol = h2.find_next_sibling('ol')
                    if next_ol:
                        items = next_ol.find_all('li', recursive=False)
                        for item in items:
                            step_text = item.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            if step_text:
                                steps.append(step_text)
                        break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пытаемся определить категорию по URL или контексту
        # Для avmarket.lt обычно это "Main Course" для kotletai, "Soup" для sriuba
        
        # Проверяем URL или заголовок
        title = self.extract_dish_name()
        if title:
            title_lower = title.lower()
            if 'sriuba' in title_lower or 'sriubos' in title_lower:
                return "Soup"
            elif 'kotlet' in title_lower or 'kukuliai' in title_lower:
                return "Main Course"
            elif 'desertas' in title_lower or 'pyragas' in title_lower:
                return "Dessert"
        
        # Можем также проверить URL из canonical link
        canonical = self.soup.find('link', rel='canonical')
        if canonical and canonical.get('href'):
            href = canonical['href'].lower()
            if 'sriuba' in href:
                return "Soup"
            elif 'kotlet' in href or 'kukul' in href:
                return "Main Course"
        
        # По умолчанию возвращаем Main Course для рецептов с мясом
        return "Main Course"
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем упоминания времени в тексте
        # Паттерны: "30 minučių", "20-25 minutes", "maždaug 30 minučių"
        
        text_content = self.soup.get_text()
        
        # Ищем паттерны времени
        patterns = [
            r'(\d+)\s*minu[cč]i[uų]',
            r'(\d+)\s*minutes?',
            r'(\d+)\s*min',
            r'(\d+[-–]\d+)\s*minu[cč]i[uų]',
            r'(\d+[-–]\d+)\s*minutes?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                time_value = match.group(1)
                return f"{time_value} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В доступных примерах prep_time всегда None
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В доступных примерах total_time всегда None
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок"""
        # Ищем параграфы в конце рецепта с дополнительной информацией
        # Обычно это советы или рекомендации
        
        # В доступных примерах notes всегда None
        # Можно добавить логику поиска заметок, если они появятся
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Извлекаем теги из URL или заголовка
        title = self.extract_dish_name()
        if title:
            # Разбиваем заголовок на слова и берем ключевые
            words = re.findall(r'\w+', title.lower())
            # Фильтруем служебные слова
            stop_words = {'su', 'ir', 'receptas', 'receptai', 'kaip', 'pagal', 'gardus', 'tobulas', 'jaukiam'}
            tags = [w for w in words if len(w) > 2 and w not in stop_words]
        
        # Можем также добавить теги из URL
        canonical = self.soup.find('link', rel='canonical')
        if canonical and canonical.get('href'):
            href = canonical['href']
            # Извлекаем последнюю часть URL
            url_part = href.rstrip('/').split('/')[-1]
            # Разбиваем по дефисам
            url_words = url_part.split('-')
            for word in url_words:
                if len(word) > 2 and word not in stop_words and word not in tags:
                    tags.append(word)
        
        # Ограничиваем количество тегов
        tags = tags[:10]
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        image_urls = []
        
        # Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url and url.startswith('http'):
                image_urls.append(url)
        
        # Ищем изображения в основном контенте
        main_content = self.soup.find('div', class_='et_pb_text_inner')
        if main_content:
            imgs = main_content.find_all('img', src=True)
            for img in imgs:
                src = img['src']
                if src and src.startswith('http') and 'wp-content/uploads' in src:
                    # Проверяем, что это не дублирующееся изображение
                    if src not in image_urls:
                        image_urls.append(src)
        
        # Ограничиваем количество изображений
        image_urls = image_urls[:5]
        
        return ','.join(image_urls) if image_urls else None
    
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта"""
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
    """Точка входа для обработки директории с HTML файлами"""
    # Путь к директории с HTML файлами
    preprocessed_dir = Path(__file__).parent.parent / "preprocessed" / "avmarket_lt"
    
    if preprocessed_dir.exists():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(AvmarketLtExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")


if __name__ == "__main__":
    main()
