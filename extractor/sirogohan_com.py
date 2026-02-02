"""
Экстрактор данных рецептов для сайта sirogohan.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

# Паттерн для извлечения чисел из японского текста
# Включает: полноширинные цифры (０-９), японские числительные (一二三 и т.д.), дроби (½¼¾)
NUMERIC_PATTERN = r'^([０-９0-9一二三四五六七八九十百千万½¼¾⅓⅔⅛⅜⅝⅞]+(?:[./][０-９0-9]+)?)'

# Глагольные окончания для фильтрации предложений с действиями
VERB_ENDINGS = ['ます', 'する', 'れる', 'える']


class SirogohanComExtractor(BaseRecipeExtractor):
    """Экстрактор для sirogohan.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта h1#recipe-name
        recipe_header = self.soup.find('h1', id='recipe-name')
        if recipe_header:
            title = self.clean_text(recipe_header.get_text())
            # Убираем суффиксы типа "のレシピ/作り方"
            title = re.sub(r'のレシピ.*$', '', title)
            title = re.sub(r'！.*のレシピ.*$', '', title)
            # Если есть восклицательный знак, берем текст после него
            if '！' in title:
                parts = title.split('！')
                if len(parts) > 1:
                    title = parts[-1].strip()
            return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'のレシピ.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Предпочтительно - из meta description (более краткое)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем префиксы и суффиксы сайта
            desc = re.sub(r'^白ごはん\.comの[『「].*?[』」]のレシピページです。', '', desc)
            
            # Берем только первые два предложения (до второй 。)
            sentences = desc.split('。')
            if len(sentences) >= 2:
                desc = '。'.join(sentences[:2]) + '。'
            
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_item(self, item_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в формате "Name … Amount(Unit)"
        
        Args:
            item_text: Строка вида "ごぼう　…　１本（150ｇ）"
            
        Returns:
            dict: {"name": "ごぼう", "amount": "1", "units": "本（150ｇ）"} или None
        """
        if not item_text:
            return None
        
        # Чистим текст
        text = self.clean_text(item_text)
        
        # Формат: "Name … Amount" или "Name … Amount(Unit)"
        # Разделитель может быть …, 　…　 или просто пробелы
        parts = re.split(r'[　\s]*[…・]+[　\s]*', text)
        
        if len(parts) < 2:
            # Если нет разделителя, возвращаем как есть
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        name = parts[0].strip()
        amount_unit = parts[1].strip()
        
        # Парсим amount и units
        # Ищем числа в начале используя предопределенный паттерн
        amount_match = re.match(NUMERIC_PATTERN, amount_unit)
        
        amount = None
        units = None
        
        if amount_match:
            amount_str = amount_match.group(1)
            # Конвертируем полноширинные цифры в обычные
            amount_str = self._convert_fullwidth_to_halfwidth(amount_str)
            amount = amount_str
            
            # Все что после числа - это units
            unit_str = amount_unit[amount_match.end():].strip()
            if unit_str:
                units = unit_str
        else:
            # Если нет числа в начале, весь текст - это units/amount
            if amount_unit:
                units = amount_unit
        
        return {
            "name": name,
            "units": units,
            "amount": amount
        }
    
    def _convert_fullwidth_to_halfwidth(self, text: str) -> str:
        """Конвертирует полноширинные числа в обычные"""
        if not text:
            return text
        
        # Полноширинные цифры
        fullwidth = '０１２３４５６７８９'
        halfwidth = '0123456789'
        trans = str.maketrans(fullwidth, halfwidth)
        
        # Японские числа
        japanese_nums = {
            '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
            '六': '6', '七': '7', '八': '8', '九': '9', '十': '10',
            '百': '100', '千': '1000', '万': '10000'
        }
        
        result = text.translate(trans)
        
        # Простая замена японских чисел (для базовых случаев)
        for jp, num in japanese_nums.items():
            if jp in result and len(result) <= 3:
                result = result.replace(jp, num)
        
        return result
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем оба списка ингредиентов (основные и приправы)
        # ul.disc-list и ul.a-list внутри .material-halfbox
        material_box = self.soup.find(class_='material-halfbox')
        
        if material_box:
            # Ищем все списки ингредиентов
            ingredient_lists = material_box.find_all('ul', class_=['disc-list', 'a-list'])
            
            for ul in ingredient_lists:
                items = ul.find_all('li')
                for item in items:
                    # Извлекаем текст ингредиента
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient_item(ingredient_text)
                    if parsed and parsed.get('name'):
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем все блоки с инструкциями .howto-block
        howto_blocks = self.soup.find_all(class_='howto-block')
        
        for block in howto_blocks:
            # Ищем заголовок шага (h3.howto-ttl)
            step_title = block.find('h3', class_='howto-ttl')
            if step_title:
                # Извлекаем номер шага из класса icon-num01, icon-num02, etc.
                step_num = None
                for cls in step_title.get('class', []):
                    if cls.startswith('icon-num'):
                        num_match = re.search(r'\d+', cls)
                        if num_match:
                            step_num = int(num_match.group())
                            break
                
                # Собираем только основные предложения из параграфов
                step_sentences = []
                for p in block.find_all('p'):
                    text = self.clean_text(p.get_text())
                    
                    # Пропускаем технические пометки и ссылки
                    if not text or any(x in text for x in [
                        '※', 'レシピ動画', '参考に', 'レシピに戻る', 
                        'の下ごしらえのまとめ', 'youtube', 'Channel'
                    ]):
                        continue
                    
                    # Разбиваем на предложения
                    sentences = re.split(r'[。！]', text)
                    for sent in sentences:
                        sent = sent.strip()
                        # Берем только предложения с действиями (содержащие глагольные окончания)
                        if sent and any(ending in sent for ending in VERB_ENDINGS):
                            # Убираем объяснения в скобках
                            sent = re.sub(r'[（(].*?[)）]', '', sent)
                            # Убираем лишние пробелы
                            sent = re.sub(r'\s+', '', sent)
                            if sent:
                                step_sentences.append(sent + '。')
                
                if step_sentences and step_num:
                    # Объединяем предложения одного шага
                    step_text = ''.join(step_sentences)
                    steps.append(f"{step_num}. {step_text}")
        
        return ''.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем .recipe-category
        category_elem = self.soup.find(class_='recipe-category')
        if category_elem:
            # Ищем ссылку внутри
            link = category_elem.find('a')
            if link:
                return self.clean_text(link.get_text())
        
        return None
    
    def extract_cooking_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Кешируем результат, чтобы избежать повторного парсинга
        if hasattr(self, '_cached_cooking_time'):
            return self._cached_cooking_time
        
        # Ищем #cooking-time
        time_elem = self.soup.find(id='cooking-time')
        if time_elem:
            time_text = time_elem.get_text(strip=True)
            # Формат: "調理時間：20分"
            # Извлекаем число и единицу
            time_match = re.search(r'(\d+)\s*分', time_text)
            if time_match:
                minutes = time_match.group(1)
                result = f"{minutes} minutes"
                self._cached_cooking_time = result
                return result
        
        self._cached_cooking_time = None
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На sirogohan.com нет отдельного prep time, возвращаем примерно половину
        total_time = self.extract_cooking_time()
        if total_time:
            match = re.search(r'(\d+)', total_time)
            if match:
                total_minutes = int(match.group(1))
                # Условно берем половину как prep time
                prep_minutes = total_minutes // 2
                return f"{prep_minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # На sirogohan.com нет отдельного cook time, возвращаем примерно половину
        total_time = self.extract_cooking_time()
        if total_time:
            match = re.search(r'(\d+)', total_time)
            if match:
                total_minutes = int(match.group(1))
                # Условно берем половину как cook time
                cook_minutes = total_minutes // 2
                return f"{cook_minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_cooking_time()
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем .point-box с .point-ttl
        point_box = self.soup.find(class_='point-box')
        
        if point_box:
            notes = []
            # Ищем список с пунктами
            ul = point_box.find('ul', class_='disc-list')
            if ul:
                items = ul.find_all('li')
                for item in items[:2]:  # Берем только первые 2 элемента
                    text = self.clean_text(item.get_text())
                    # Пропускаем технические обновления
                    if text and 'レシピ更新情報' not in text and '工程中の材料' not in text:
                        # Убираем "です" в конце для краткости
                        text = re.sub(r'です[。！]?$', '。', text)
                        notes.append(text)
            
            # Объединяем без пробела для соответствия формату
            return ''.join(notes) if notes else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем dl.recipe-keyword
        keyword_sections = self.soup.find_all('dl', class_='recipe-keyword')
        
        for section in keyword_sections:
            # Ищем dd элементы с ссылками
            dd_items = section.find_all('dd')
            for dd in dd_items:
                links = dd.find_all('a')
                for link in links:
                    tag_text = self.clean_text(link.get_text())
                    if tag_text:
                        tags.append(tag_text)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-теге og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем основное изображение с itemprop="image"
        main_image = self.soup.find('img', itemprop='image')
        if main_image and main_image.get('src'):
            src = main_image['src']
            # Преобразуем относительный URL в абсолютный
            if src.startswith('/'):
                src = f"https://www.sirogohan.com{src}"
            urls.append(src)
        
        # 3. Ищем изображения в шагах приготовления
        howto_images = self.soup.find_all('ul', class_='howto-imglist-col1')
        for img_list in howto_images:
            images = img_list.find_all('img')
            for img in images:
                src = img.get('src')
                if src:
                    if src.startswith('/'):
                        src = f"https://www.sirogohan.com{src}"
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
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Обработка директории с HTML файлами sirogohan.com"""
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join("preprocessed", "sirogohan_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(SirogohanComExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python sirogohan_com.py")


if __name__ == "__main__":
    main()
