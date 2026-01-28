"""
Скрипт для исследования структуры сайта и сбора уникальных ссылок
"""
import os
import sys
import time
import json
import random
import threading
from pathlib import Path
from typing import Dict, List, Optional
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from utils.languages import COOKIE_KEYWORDS, COOKIE_SELECTORS
from src.common.gpt.client import GPTClient

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CoockieHandler:
    
    # Селекторы для поиска cookie-баннеров/контейнеров
    COOKIE_BANNER_SELECTORS = [
        # По ID
        '[id*="cookie"]', '[id*="consent"]', '[id*="gdpr"]', '[id*="privacy"]',
        '[id*="onetrust"]', '[id*="cookielaw"]', '[id*="cc-"]', '[id*="cmp"]',
        # По классам
        '[class*="cookie-banner"]', '[class*="cookie-consent"]', '[class*="gdpr"]',
        '[class*="consent-banner"]', '[class*="privacy-banner"]', '[class*="cookie-notice"]',
        '[class*="cc-banner"]', '[class*="cc-window"]', '[class*="cmp-"]',
        # По role и aria
        '[role="dialog"][aria-label*="cookie" i]', '[role="dialog"][aria-label*="consent" i]',
        '[aria-label*="cookie" i]', '[aria-describedby*="cookie" i]',
        # По data атрибутам
        '[data-testid*="cookie"]', '[data-testid*="consent"]',
        '[data-nosnippet]',  # Часто используется для cookie баннеров
    ]
    
    def __init__(self, driver: webdriver.Chrome):
        """
        Args:
            driver: Экземпляр Selenium WebDriver
            gpt_client: Экземпляр GPTClient для взаимодействия с GPT
        """
        self.driver = driver
        self.gpt_client = GPTClient()
        self.logger = logger

    def build_css_selector(self, elem) -> List[str]:
        """
        Строит CSS селекторы для элемента через BS4, без GPT
        
        Returns:
            Список CSS селекторов от наиболее специфичного к менее
        """
        selectors = []
        
        # 1. По ID - самый надежный
        elem_id = elem.get('id', '')
        if elem_id:
            selectors.append(f"#{elem_id}")
        
        # 2. По data-атрибутам
        for attr, value in elem.attrs.items():
            if attr.startswith('data-') and value:
                if isinstance(value, list):
                    value = value[0]
                # Экранируем спецсимволы
                value_escaped = str(value).replace('"', '\\"')
                selectors.append(f'[{attr}="{value_escaped}"]')
        
        # 3. По тегу + классам
        tag = elem.name
        classes = elem.get('class', [])
        if classes:
            # Фильтруем классы с спецсимволами
            safe_classes = [c for c in classes if c and not any(char in c for char in '[]():')]
            if safe_classes:
                selectors.append(f"{tag}.{'.'.join(safe_classes[:3])}")
                if len(safe_classes) > 0:
                    selectors.append(f"{tag}.{safe_classes[0]}")
        
        # 4. С контекстом родителя
        parent = elem.parent
        if parent and parent.name:
            parent_id = parent.get('id', '')
            parent_classes = parent.get('class', [])
            
            if parent_id:
                if elem_id:
                    selectors.append(f"#{parent_id} #{elem_id}")
                elif classes:
                    selectors.append(f"#{parent_id} {tag}.{classes[0]}")
                else:
                    selectors.append(f"#{parent_id} > {tag}")
            elif parent_classes:
                safe_parent_classes = [c for c in parent_classes if c and not any(char in c for char in '[]():')]
                if safe_parent_classes:
                    if classes:
                        selectors.append(f"{parent.name}.{safe_parent_classes[0]} > {tag}.{classes[0]}")
                    else:
                        selectors.append(f"{parent.name}.{safe_parent_classes[0]} > {tag}")
        
        return selectors

    def build_xpath_selector(self, elem) -> List[str]:
        """
        Строит XPath селекторы для элемента через BS4, без GPT
        
        Returns:
            Список XPath селекторов
        """
        selectors = []
        tag = elem.name
        elem_id = elem.get('id', '')
        classes = elem.get('class', [])
        text = elem.get_text(strip=True)[:50]
        
        # 1. По ID
        if elem_id:
            selectors.append(f"//*[@id='{elem_id}']")
        
        # 2. По data-атрибутам
        for attr, value in elem.attrs.items():
            if attr.startswith('data-') and value:
                if isinstance(value, list):
                    value = value[0]
                selectors.append(f"//*[@{attr}='{value}']")
        
        # 3. По тексту
        if text:
            # Экранируем кавычки
            if "'" in text and '"' in text:
                # Используем concat для сложных случаев
                pass
            elif "'" in text:
                selectors.append(f'//{tag}[contains(text(), "{text[:30]}")]')
            else:
                selectors.append(f"//{tag}[contains(text(), '{text[:30]}')]")
            
            # Точное совпадение с normalize-space
            if len(text) < 30:
                if "'" not in text:
                    selectors.append(f"//{tag}[normalize-space()='{text}']")
        
        # 4. По классам
        if classes:
            for cls in classes[:2]:
                if cls and "'" not in cls:
                    selectors.append(f"//{tag}[contains(@class, '{cls}')]")
        
        # 5. Комбинация класса и текста
        if classes and text and "'" not in text and "'" not in classes[0]:
            selectors.append(f"//{tag}[contains(@class, '{classes[0]}') and contains(text(), '{text[:20]}')]")
        
        return selectors

    def find_cookie_banner(self, soup: BeautifulSoup):
        """
        Ищет cookie-баннер/контейнер на странице
        
        Returns:
            BeautifulSoup element или None
        """
        for selector in self.COOKIE_BANNER_SELECTORS:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    # Проверяем что элемент видимый (не скрыт через style)
                    style = elem.get('style', '')
                    if 'display: none' in style or 'visibility: hidden' in style:
                        continue
                    
                    # Проверяем что внутри есть кнопки или ссылки
                    buttons = elem.find_all(['button', 'a', 'input'])
                    if buttons:
                        self.logger.info(f"🎯 Найден cookie-баннер: {selector}")
                        return elem
            except Exception as e:
                self.logger.debug(f"Ошибка при поиске баннера {selector}: {e}")
        
        return None

    def extract_buttons_from_banner(self, banner) -> List[Dict]:
        """
        Извлекает кнопки из найденного cookie-баннера
        """
        buttons = []
        found_elements = set()
        
        # Ищем все кликабельные элементы внутри баннера
        clickable_selectors = ['button', 'a', 'input[type="button"]', 'input[type="submit"]', 
                               '[role="button"]', '[onclick]']
        
        for selector in clickable_selectors:
            try:
                elements = banner.select(selector)
                for elem in elements:
                    elem_str = str(elem)[:200]
                    if elem_str in found_elements:
                        continue
                    found_elements.add(elem_str)
                    
                    # Для баннера берем все кнопки, не только с ключевыми словами
                    button_info = {
                        'tag': elem.name,
                        'text': elem.get_text(strip=True)[:100],
                        'id': elem.get('id', ''),
                        'class': ' '.join(elem.get('class', [])),
                        'role': elem.get('role', ''),
                        'type': elem.get('type', ''),
                        'onclick': elem.get('onclick', ''),
                        'data_attrs': {k: v for k, v in elem.attrs.items() if k.startswith('data-')},
                        'html_snippet': str(elem)[:300],
                        'parent_tag': elem.parent.name if elem.parent else '',
                        'parent_class': ' '.join(elem.parent.get('class', [])) if elem.parent else '',
                        'element': elem  # Сохраняем сам элемент для построения селекторов
                    }
                    buttons.append(button_info)
                    
            except Exception as e:
                self.logger.debug(f"Ошибка при извлечении кнопок: {e}")
        
        return buttons

    def rank_buttons_locally(self, buttons: List[Dict]) -> List[int]:
        """
        Ранжирует кнопки локально без GPT по эвристикам
        
        Returns:
            Список индексов отсортированных по приоритету
        """
        scored_buttons = []
        
        # Ключевые слова для accept (высокий приоритет)
        accept_keywords = ['accept all', 'accept', 'allow all', 'allow', 'agree', 'ok', 'got it',
                          'i agree', 'понятно', 'принять', 'согласен', 'akceptuj', 'accetta',
                          'aceitar', 'aceptar', 'accepter', 'zustimmen', 'akzeptieren']
        
        # Ключевые слова для reject (низкий приоритет)
        reject_keywords = ['reject', 'decline', 'deny', 'refuse', 'settings', 'manage', 
                          'customize', 'preferences', 'отклонить', 'настройки']
        
        for i, btn in enumerate(buttons):
            score = 0
            text = btn['text'].lower()
            classes = btn['class'].lower()
            btn_id = btn['id'].lower()
            
            # Проверяем accept keywords
            for kw in accept_keywords:
                if kw in text:
                    score += 10
                    if 'all' in text:
                        score += 5  # "accept all" выше чем просто "accept"
                    break
            
            # Проверяем классы на accept
            if any(kw in classes for kw in ['accept', 'agree', 'allow', 'confirm', 'primary', 'success']):
                score += 5
            
            # Проверяем ID на accept
            if any(kw in btn_id for kw in ['accept', 'agree', 'allow', 'confirm']):
                score += 5
            
            # Штраф за reject keywords
            for kw in reject_keywords:
                if kw in text:
                    score -= 15
                    break
            
            # Предпочитаем кнопки с коротким текстом (обычно основные действия)
            if len(btn['text']) < 20:
                score += 2
            
            # Предпочитаем button над a
            if btn['tag'] == 'button':
                score += 2
            
            scored_buttons.append((i, score))
        
        # Сортируем по убыванию score
        scored_buttons.sort(key=lambda x: x[1], reverse=True)
        
        # Возвращаем только с положительным или нулевым score
        return [i for i, score in scored_buttons if score >= 0]

    def extract_cookie_buttons(self, html_content: str) -> List[Dict]:
        """
        Шаг 1: Извлечение всех потенциальных кнопок cookies из HTML
        
        Args:
            html_content: HTML код страницы
            
        Returns:
            Список словарей с информацией о кнопках
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        buttons = []
        
        found_elements = set()  # Для избежания дубликатов
        
        for selector in COOKIE_SELECTORS:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    # Проверяем что элемент еще не добавлен
                    elem_str = str(elem)[:300]  # Уникальный идентификатор
                    if elem_str in found_elements:
                        continue
                    
                    text = elem.get_text(strip=True).lower()
                    
                    # Проверяем наличие ключевых слов
                    if any(keyword in text for keyword in COOKIE_KEYWORDS):
                        found_elements.add(elem_str)
                        
                        # Собираем информацию о кнопке
                        button_info = {
                            'tag': elem.name,
                            'text': elem.get_text(strip=True)[:100],  # Ограничиваем длину
                            'id': elem.get('id', ''),
                            'class': ' '.join(elem.get('class', [])),
                            'role': elem.get('role', ''),
                            'type': elem.get('type', ''),
                            'onclick': elem.get('onclick', ''),
                            'data_attrs': {k: v for k, v in elem.attrs.items() if k.startswith('data-')},
                            'html_snippet': str(elem)[:300],
                            'parent_tag': elem.parent.name if elem.parent else '',
                            'parent_class': ' '.join(elem.parent.get('class', [])) if elem.parent else ''
                        }
                        buttons.append(button_info)
                        
            except Exception as e:
                self.logger.debug(f"Ошибка при обработке селектора {selector}: {e}")
        
        self.logger.info(f"📋 Найдено потенциальных кнопок cookies: {len(buttons)}")
        return buttons

    def analyze_buttons_with_gpt(self, buttons: List[Dict]) -> List[int]:
        """
        Шаг 2: GPT анализирует кнопки и выбирает несколько наиболее подходящих для принятия cookies
        
        Args:
            buttons: Список кнопок из extract_cookie_buttons
            
        Returns:
            Список индексов кнопок-кандидатов (отсортированных по приоритету) или пустой список
        """
        if not buttons:
            return []
        
        system_prompt = """You are an expert at analyzing HTML buttons to identify cookie consent buttons.
Your task is to find ALL buttons that could potentially accept cookies.
Better to include extra candidates than miss the right one.
Consider button text, classes, parent context, and data attributes.
Return ONLY a JSON object with multiple button candidates."""
        
        # Формируем расширенное представление кнопок с контекстом
        buttons_info = []
        for i, btn in enumerate(buttons):
            buttons_info.append({
                'index': i,
                'text': btn['text'],
                'id': btn['id'],
                'class': btn['class'],
                'tag': btn['tag'],
                'parent_tag': btn.get('parent_tag', ''),
                'parent_class': btn['parent_class'],
                'data_attrs': btn.get('data_attrs', {}),
                'onclick': btn.get('onclick', '')[:100],  # Ограничиваем длину
                'html_snippet': btn.get('html_snippet', '')[:200]  # Контекст HTML
            })
        
        user_prompt = f"""Analyze these buttons and find ALL that could accept cookies.
Rank them by likelihood of being the "Accept All" button.

Prioritize buttons with:
- Text like "Accept all", "Allow all", "Accetta tutti", "Akceptuj wszystkie", "Принять все", "OK", "Agree", "I agree", "Got it", etc.
- Classes containing: accept, agree, allow, consent, confirm, ok, primary
- Data attributes indicating acceptance action
- Being inside cookie/consent/gdpr containers

Include even uncertain candidates - better to have extra options than miss the right button.
Avoid buttons that clearly say "reject", "decline", "settings only", "manage", "customize".

Buttons:
{json.dumps(buttons_info, indent=2, ensure_ascii=False)}

Return ONLY this JSON format:
{{
  "candidates": [
    {{
      "button_index": <number>,
      "confidence": "high" or "medium" or "low",
      "reasoning": "brief explanation"
    }}
  ]
}}

Return at least 1-3 candidates, ordered by confidence (best first).
If unsure, include more candidates rather than fewer."""
        
        try:
            response = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=500
            )
            
            self.logger.info(f"GPT ответ: {response}")
            
            candidates = response.get('candidates', [])
            
            # Если GPT вернул старый формат с одним button_index
            if not candidates and 'button_index' in response:
                candidates = [{'button_index': response['button_index'], 'confidence': response.get('confidence', 'medium')}]
            
            valid_indices = []
            for candidate in candidates:
                idx = candidate.get('button_index')
                if idx is not None and 0 <= idx < len(buttons):
                    valid_indices.append(idx)
                    confidence = candidate.get('confidence', 'unknown')
                    reasoning = candidate.get('reasoning', '')
                    self.logger.info(f"✓ Кандидат #{idx}: '{buttons[idx]['text'][:50]}' (confidence: {confidence})")
                    if reasoning:
                        self.logger.info(f"  Обоснование: {reasoning}")
            
            if not valid_indices:
                self.logger.warning("GPT не вернул валидных кандидатов")
                # Fallback: возвращаем все индексы если GPT не справился
                return list(range(len(buttons)))
            
            self.logger.info(f"📋 Всего кандидатов: {len(valid_indices)}")
            return valid_indices
                
        except Exception as e:
            self.logger.error(f"Ошибка при анализе через GPT: {e}")
            # Fallback: возвращаем все кнопки для перебора
            return list(range(len(buttons)))

    def get_selector_from_gpt(self, button_info: Dict, html_content: str) -> Optional[Dict]:
        """
        Шаг 3: GPT создает наиболее специфичный селектор для кнопки
        
        Args:
            button_info: Информация о выбранной кнопке
            html_content: Полный HTML или контекст вокруг кнопки
            
        Returns:
            Словарь с типом селектора и самим селектором
        """
        # Извлекаем контекст вокруг кнопки
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Ищем элемент кнопки в HTML
        button_elem = None
        if button_info['id']:
            button_elem = soup.find(id=button_info['id'])
        
        if not button_elem and button_info['class']:
            # Поиск по классам
            classes = button_info['class'].split()
            if classes:
                for elem in soup.find_all(button_info['tag']):
                    elem_classes = elem.get('class', [])
                    if classes[0] in elem_classes:
                        if elem.get_text(strip=True)[:50] == button_info['text'][:50]:
                            button_elem = elem
                            break
        
        if not button_elem and button_info['text']:
            # Поиск по тексту
            for elem in soup.find_all([button_info['tag']]):
                if elem.get_text(strip=True) == button_info['text']:
                    button_elem = elem
                    break
        
        # Получаем HTML контекст (родители) и собираем путь к элементу
        context_html = button_info.get('html_snippet', '')
        element_path = []
        siblings_info = []
        
        if button_elem:
            # Собираем путь от элемента к корню (до 5 уровней)
            current = button_elem
            for level in range(5):
                if current and current.name:
                    elem_info = {
                        'tag': current.name,
                        'id': current.get('id', ''),
                        'classes': current.get('class', []),
                        'level': level
                    }
                    element_path.append(elem_info)
                    current = current.parent
                else:
                    break
            
            # Собираем информацию о соседних элементах (siblings)
            if button_elem.parent:
                for sibling in button_elem.parent.children:
                    if hasattr(sibling, 'name') and sibling.name:
                        siblings_info.append({
                            'tag': sibling.name,
                            'id': sibling.get('id', ''),
                            'classes': sibling.get('class', [])[:3],  # Первые 3 класса
                            'text': sibling.get_text(strip=True)[:30],
                            'is_target': sibling == button_elem
                        })
            
            # Берем 4 уровня родителей для контекста
            parent = button_elem.parent
            grandparent = parent.parent if parent else None
            great_grandparent = grandparent.parent if grandparent else None
            great_great_grandparent = great_grandparent.parent if great_grandparent else None
            
            if great_great_grandparent:
                context_html = str(great_great_grandparent)[:4000]
            elif great_grandparent:
                context_html = str(great_grandparent)[:3500]
            elif grandparent:
                context_html = str(grandparent)[:3000]
            elif parent:
                context_html = str(parent)[:2500]
            else:
                context_html = str(button_elem)[:2000]
        
        # Формируем список всех классов для анализа
        classes_list = button_info['class'].split() if button_info['class'] else []
        
        # Собираем все атрибуты элемента
        all_attrs = {
            'id': button_info.get('id', ''),
            'class': classes_list,
            'role': button_info.get('role', ''),
            'type': button_info.get('type', ''),
            'onclick': button_info.get('onclick', '')[:150],
            'data_attrs': button_info.get('data_attrs', {}),
        }
        
        system_prompt = """You are an expert at creating robust CSS selectors and XPath expressions for Selenium WebDriver.
Your selectors MUST work with Selenium's By.CSS_SELECTOR and By.XPATH.

CRITICAL RULES:
1. CSS :contains() is NOT supported in Selenium - use XPath for text matching
2. Prefer simple, direct selectors that are less likely to break
3. Always provide multiple fallback options  
4. XPath is more reliable for text-based selection
5. Use the element path and siblings info to create unique selectors
6. Analyze the full banner HTML to understand the structure

Return ONLY a valid JSON object."""
        
        user_prompt = f"""Create MULTIPLE reliable selectors for this button to click in Selenium.

=== BUTTON DETAILS ===
Tag: {button_info['tag']}
Text content: "{button_info['text']}"
All attributes: {json.dumps(all_attrs, ensure_ascii=False)}

=== ELEMENT PATH (from button to root) ===
{json.dumps(element_path, indent=2, ensure_ascii=False)}

=== SIBLING ELEMENTS (same parent) ===
{json.dumps(siblings_info, indent=2, ensure_ascii=False)}

=== BUTTON HTML CONTEXT (4 levels of parents) ===
{context_html}

=== SELECTOR PRIORITY ===
1. By ID: "#exact-id" (most reliable if exists)
2. By data attribute: "[data-testid='value']", "[data-action='accept']"
3. By unique class combination: "tag.class1.class2"
4. By parent context: "div.parent-class > button.child-class"
5. By XPath with text: "//button[contains(text(), 'Accept')]"
6. By XPath with normalized space: "//button[normalize-space()='Accept All']"
7. By XPath combining attributes: "//button[@class and contains(text(), 'OK')]"

=== IMPORTANT RULES ===
- Do NOT use CSS :contains() - it doesn't work in Selenium!
- For text matching, ALWAYS use XPath with contains() or normalize-space()
- If button has unique ID - use it first
- If button has data-* attributes - they are often stable selectors
- Use parent classes to make selector more specific
- Escape special characters properly
- Look at the FULL BANNER HTML to understand the complete structure

Return ONLY this JSON format:
{{
  "type": "css",
  "selector": "your best CSS selector (by id, data-attr, or class)",
  "fallback_selector": "alternative CSS selector using parent context",
  "xpath_selector": "XPath selector using text or attributes",
  "xpath_fallback": "alternative XPath with different approach",
  "confidence": "high" or "medium" or "low"
}}

=== GOOD SELECTOR EXAMPLES ===
CSS: "#onetrust-accept-btn-handler"
CSS: "button[data-action='accept-all']"
CSS: "div.cookie-banner button.accept-btn"
CSS: "[data-testid='cookie-consent-accept']"
XPath: "//button[@id='accept-cookies']"
XPath: "//button[normalize-space()='Accept All']"
XPath: "//div[contains(@class,'cookie')]//button[contains(text(),'Accept')]"
XPath: "//*[@data-action='accept' or contains(@class,'accept')]" """
        
        try:
            response = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=400
                                        )
            
            self.logger.info(f"🎯 GPT создал селектор: {response.get('selector')}")
            self.logger.info(f"   XPath: {response.get('xpath_selector')}")
            self.logger.info(f"   Уверенность: {response.get('confidence')}")
            
            return response
            
        except Exception as e:
            self.logger.error(f"Ошибка при создании селектора через GPT: {e}")
            return None

    def find_and_click_cookie_button(self, html_content: str) -> bool:
        """
        Полный процесс поиска и клика по кнопке cookies - гибридный подход:
        1. Сначала ищем cookie-баннер
        2. Если найден - ищем кнопки внутри и ранжируем локально
        3. Строим селекторы через BS4
        4. Если не сработало - fallback на GPT
        
        Args:
            html_content: HTML код страницы
            
        Returns:
            True если кнопка найдена и нажата, False иначе
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # === ЭТАП 1: Поиск cookie-баннера ===
            self.logger.info("🔍 Этап 1: Ищем cookie-баннер...")
            banner = self.find_cookie_banner(soup)
            
            buttons = []
            use_local_ranking = False
            
            if banner:
                self.logger.info("✅ Cookie-баннер найден, извлекаем кнопки из него")
                buttons = self.extract_buttons_from_banner(banner)
                use_local_ranking = True
            
            if not buttons:
                self.logger.info("📋 Баннер не найден или пуст, используем общий поиск кнопок")
                buttons = self.extract_cookie_buttons(html_content)
                use_local_ranking = False
            
            if not buttons:
                self.logger.warning("❌ Кнопки cookies не найдены в HTML")
                return False
            
            self.logger.info(f"📋 Найдено кнопок: {len(buttons)}")
            
            # === ЭТАП 2: Ранжирование кнопок ===
            if len(buttons) == 1:
                candidate_indices = [0]
                self.logger.info("ℹ️ Найдена только одна кнопка, выбираем её автоматически")
            elif use_local_ranking:
                # Локальное ранжирование без GPT (быстрее и надежнее для баннеров)
                self.logger.info("🔍 Этап 2: Локальное ранжирование кнопок...")
                candidate_indices = self.rank_buttons_locally(buttons)
                if not candidate_indices:
                    candidate_indices = list(range(len(buttons)))
            else:
                # Fallback на GPT для сложных случаев
                self.logger.info("🔍 Этап 2: GPT ранжирование кнопок...")
                candidate_indices = self.analyze_buttons_with_gpt(buttons)
            
            if not candidate_indices:
                self.logger.warning("❌ Не удалось определить кнопки-кандидаты")
                return False
            
            self.logger.info(f"🎯 Кнопок-кандидатов: {len(candidate_indices)}")
            
            # === ЭТАП 3: Попытки клика ===
            for candidate_num, button_index in enumerate(candidate_indices):
                target_button = buttons[button_index]
                self.logger.info(f"\n🔄 Попытка {candidate_num + 1}/{len(candidate_indices)}: '{target_button['text'][:50]}'")
                
                # Собираем селекторы
                selectors_to_try = []
                
                # 3.1 Селекторы построенные через BS4 (без GPT)
                if 'element' in target_button and target_button['element']:
                    elem = target_button['element']
                    
                    # CSS селекторы от BS4
                    css_selectors = self.build_css_selector(elem)
                    for sel in css_selectors:
                        selectors_to_try.append(('css', sel))
                    
                    # XPath селекторы от BS4
                    xpath_selectors = self.build_xpath_selector(elem)
                    for sel in xpath_selectors:
                        selectors_to_try.append(('xpath', sel))
                
                # 3.2 Простые селекторы по ID
                if target_button['id']:
                    selectors_to_try.insert(0, ('css', f"#{target_button['id']}"))
                    selectors_to_try.insert(1, ('xpath', f"//*[@id='{target_button['id']}']"))
                
                # 3.3 Data-атрибуты
                for attr, value in target_button.get('data_attrs', {}).items():
                    if value:
                        if isinstance(value, list):
                            value = value[0]
                        selectors_to_try.append(('css', f'[{attr}="{value}"]'))
                
                # 3.4 Селекторы по классам
                if target_button['class']:
                    classes = target_button['class'].split()
                    if classes:
                        safe_classes = [c for c in classes if c and not any(ch in c for ch in '[]():')]
                        if safe_classes:
                            selectors_to_try.append(('css', f"{target_button['tag']}.{safe_classes[0]}"))
                            if len(safe_classes) > 1:
                                selectors_to_try.append(('css', f"{target_button['tag']}.{'.'.join(safe_classes[:3])}"))
                
                # 3.5 XPath по тексту
                if target_button['text']:
                    text = target_button['text'][:30]
                    if "'" not in text:
                        selectors_to_try.append(('xpath', f"//{target_button['tag']}[contains(text(), '{text}')]"))
                        selectors_to_try.append(('xpath', f"//*[contains(text(), '{text}')]"))
                        if len(text) < 25:
                            selectors_to_try.append(('xpath', f"//{target_button['tag']}[normalize-space()='{target_button['text'][:50]}']"))
                
                # 3.6 Fallback: GPT селекторы (если локальные не сработают)
                gpt_selectors_added = False
                
                # Убираем дубликаты, сохраняя порядок
                seen = set()
                unique_selectors = []
                for s in selectors_to_try:
                    if s not in seen and s[1]:  # Проверяем что селектор не пустой
                        seen.add(s)
                        unique_selectors.append(s)
                
                self.logger.info(f"📋 Сформировано {len(unique_selectors)} уникальных селекторов")
                
                for selector_type, selector in unique_selectors:
                    try:
                        self.logger.debug(f"🔍 Пробуем {selector_type}: {selector}")
                        
                        if selector_type == 'css':
                            element = WebDriverWait(self.driver, 1.5).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                            )
                        else:  # xpath
                            element = WebDriverWait(self.driver, 1.5).until(
                                EC.element_to_be_clickable((By.XPATH, selector))
                            )
                        
                        # Прокручиваем к элементу
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                        time.sleep(0.2)
                        
                        # Кликаем
                        element.click()
                        self.logger.info(f"✅ Успешно кликнули используя {selector_type}: {selector}")
                        
                        time.sleep(1.5)
                        return True
                        
                    except TimeoutException:
                        continue
                    except Exception as e:
                        self.logger.debug(f"⚠️ Ошибка при клике: {e}")
                        continue
                
                # 3.7 Если локальные селекторы не сработали - пробуем GPT
                if not gpt_selectors_added and candidate_num < 2:
                    self.logger.info("🤖 Локальные селекторы не сработали, пробуем GPT...")
                    selector_info = self.get_selector_from_gpt(target_button, html_content)
                    
                    if selector_info:
                        gpt_selectors = []
                        if selector_info.get('selector'):
                            gpt_selectors.append((selector_info.get('type', 'css'), selector_info.get('selector')))
                        if selector_info.get('fallback_selector'):
                            gpt_selectors.append((selector_info.get('type', 'css'), selector_info.get('fallback_selector')))
                        if selector_info.get('xpath_selector'):
                            gpt_selectors.append(('xpath', selector_info.get('xpath_selector')))
                        if selector_info.get('xpath_fallback'):
                            gpt_selectors.append(('xpath', selector_info.get('xpath_fallback')))
                        
                        for selector_type, selector in gpt_selectors:
                            try:
                                self.logger.debug(f"🔍 GPT {selector_type}: {selector}")
                                
                                if selector_type == 'css':
                                    element = WebDriverWait(self.driver, 2).until(
                                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                                    )
                                else:
                                    element = WebDriverWait(self.driver, 2).until(
                                        EC.element_to_be_clickable((By.XPATH, selector))
                                    )
                                
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                                time.sleep(0.2)
                                element.click()
                                self.logger.info(f"✅ GPT селектор сработал: {selector_type}: {selector}")
                                
                                time.sleep(1.5)
                                return True
                                
                            except TimeoutException:
                                continue
                            except Exception as e:
                                self.logger.debug(f"⚠️ GPT ошибка: {e}")
                                continue
                
                self.logger.info(f"⚠️ Кандидат #{button_index} не сработал")
            
            self.logger.warning("❌ Не удалось кликнуть ни по одному из кандидатов")
            return False
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка в процессе поиска кнопки: {e}")
            return False


class CapchaAccepter:
    
    def __init__(self, debug_mode: bool = True, debug_port: int = None, driver: webdriver.Chrome = None):
        """
        Args:
            base_url: Базовый URL сайта
            debug_mode: Если True, подключается к открытому Chrome с отладкой
            recipe_pattern: Regex паттерн для поиска URL с рецептами (опционально)
            max_errors: Максимальное количество ошибок подряд перед остановкой
            max_urls_per_pattern: Максимальное количество URL на один паттерн (None = без ограничений)
            debug_port: Порт для подключения к Chrome (по умолчанию из config)
            driver: Переданный экземпляр webdriver.Chrome (если None, создается новый)
            custom_logger: Пользовательский логгер (если None, используется стандартный)
            max_no_recipe_pages: Максимальное количество страниц без рецепта подряд (None = без ограничений). Если указано прерывает исследвоание сайта при достижении лимита
        """
        self.debug_mode = debug_mode
        self.debug_port = debug_port if debug_port is not None else 9222
        self.driver = driver
        self.recipe_regex = None
        self.analyzer = None
        self.logger = logger
        self.coockie_handler = CoockieHandler(driver=self.driver)
        
        # Файлы для сохранения
        self.save_dir = os.path.join("capcha")
        os.makedirs(self.save_dir, exist_ok=True)
        self.gpt_client = GPTClient()

    
    def connect_to_chrome(self):
        """Подключение к Chrome в отладочном режиме"""

        if self.driver is not None:
             # Проверяем что подключение работает
            try:
                _ = self.driver.current_url
                self.logger.info("✓ Успешное подключение к браузеру")
                self.logger.info("Используется переданный экземпляр webdriver.Chrome")
                return
            except Exception as e:
                self.logger.warning(f"Подключение установлено, но проблема с сессией: {e}")
                self.driver.quit()

        chrome_options = Options()
        
        if self.debug_mode:
            # Проверяем доступность Chrome на указанном порту
            if not self._is_chrome_running(self.debug_port):
                error_msg = (
                    f"\n{'='*60}\n"
                    f"ОШИБКА: Chrome не запущен на порту {self.debug_port}\n\n"
                    f"Запустите Chrome командой:\n"
                    f"  google-chrome --remote-debugging-port={self.debug_port} "
                    f"--user-data-dir=./chrome_debug_{self.debug_port}\n\n"
                    f"Или проверьте что порт не занят:\n"
                    f"  lsof -i :{self.debug_port}\n"
                    f"{'='*60}\n"
                )
                self.logger.error(error_msg)
                raise WebDriverException(
                    f"Chrome не запущен на порту {self.debug_port}"
                )
            
            chrome_options.add_experimental_option(
                "debuggerAddress", 
                f"localhost:{self.debug_port}"
            )
            self.logger.info(f"Подключение к Chrome на порту {self.debug_port}")
        else:
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            
            # Отключение ненужных сервисов Google (убирает ошибки GCM)
            chrome_options.add_argument("--disable-sync")
            chrome_options.add_argument("--disable-background-networking")
            chrome_options.add_argument("--disable-default-apps")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--log-level=3")
            
            # Ротация User-Agent для меньшей детекции
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ]
            chrome_options.add_argument(f"user-agent={random.choice(user_agents)}")
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(15)
            self.driver.set_page_load_timeout(30)
            
            # Проверяем что подключение работает
            try:
                _ = self.driver.current_url
                self.logger.info("✓ Успешное подключение к браузеру")
            except Exception as e:
                self.logger.warning(f"Подключение установлено, но проблема с сессией: {e}")
                self.driver.quit()
                raise
                
        except WebDriverException as e:
            self.logger.error(f"Ошибка подключения к браузеру: {e}")
            if self.debug_mode:
                self.logger.error(
                    f"\nУбедитесь что Chrome запущен:\n"
                    f"  ps aux | grep chrome | grep {self.debug_port}\n"
                )
            raise
    
    def _is_chrome_running(self, port: int) -> bool:
        """
        Проверка запущен ли Chrome на указанном порту
        
        Args:
            port: Порт для проверки
        
        Returns:
            True если Chrome доступен
        """
        import socket
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def slow_scroll_page(self, quick_mode: bool = False):
        """Прокрутка страницы для загрузки контента
        
        Args:
            quick_mode: Если True, делает быструю прокрутку (для ускорения)
        """
        try:
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            
            if quick_mode:
                # Быстрая прокрутка: 2-3 шага с короткими паузами
                num_scrolls = random.randint(2, 3)
                scroll_step = total_height // num_scrolls
                
                current_position = 0
                for i in range(num_scrolls):
                    current_position += scroll_step
                    self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                    time.sleep(random.uniform(0.3, 0.5))
                
                # Быстрая прокрутка в конец
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(0.3, 0.6))
            else:
                # Обычная прокрутка
                num_scrolls = random.randint(3, 5)
                scroll_step = total_height // num_scrolls
                
                current_position = 0
                for i in range(num_scrolls):
                    current_position += scroll_step
                    self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                    time.sleep(random.uniform(0.4, 0.8))
                
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(0.5, 1.0))
            
        except Exception as e:
            self.logger.debug(f"Ошибка при прокрутке: {e}")


    def save_page_as_file(self, pattern: str, page_index: int) -> str:
        """        
        Сохранение HTML страницы на файловую систему
        Args:
            pattern: Паттерн URL
            page_index: Индекс страницы в рамках паттерна
        Returns:
            Путь к сохраненному файлу HTML
        """

        html_content = self.driver.page_source
            
        # Создание имени файла из паттерна
        safe_pattern = pattern.replace('/', '_').replace('#', 'N').replace('{', '').replace('}', '').strip('_')
        if not safe_pattern:
            safe_pattern = 'index'
        
        filename = f"{safe_pattern}_{page_index}.html"
        filepath = os.path.join(self.save_dir,filename)
        
        # Сохранение HTML
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return filepath

    def _navigate_with_timeout(self, url: str, timeout: int = 90) -> bool:
        """
        Переход на страницу с гарантированным timeout через отдельный поток
        
        Args:
            url: URL для загрузки
            timeout: Максимальное время ожидания в секундах
            
        Returns:
            True если загрузка успешна, False если timeout
        """
        load_complete = threading.Event()
        navigation_error = [None]  # Для передачи исключений из потока
        
        def navigate():
            try:
                self.driver.get(url)
                load_complete.set()
            except Exception as e:
                navigation_error[0] = e
                load_complete.set()
        
        # Запуск загрузки в отдельном потоке
        nav_thread = threading.Thread(target=navigate, daemon=True)
        nav_thread.start()
        
        # Ожидание с timeout
        if not load_complete.wait(timeout=timeout):
            # Timeout - принудительная остановка
            self.logger.warning(f"⏱ Timeout {timeout}s при загрузке, останавливаем")
            try:
                self.driver.execute_script("window.stop();")
            except Exception:
                pass
            return False
        
        # Проверка на ошибки навигации
        if navigation_error[0]:
            if isinstance(navigation_error[0], TimeoutException):
                self.logger.warning("⏱ Selenium TimeoutException при загрузке")
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
                return False
            else:
                # Другие ошибки пробрасываем
                raise navigation_error[0]
        
        return True
    
    def accept_capcha(self, current_url: str):
        """
        Исследование структуры сайта
        
        Args:
            max_urls: Максимальное количество URL для посещения
            max_depth: Максимальная глубина обхода
            session_urls: Если True, то не учитывает старые посещенные URL при подсчтее max urls
            check_pages_with_extractor: Если True, проверяет каждую страницу экстрактором рецептов
            check_url: Если True, проверяет каждый на реджекс паттерн перед экстракцией (парамтер касается только экстракции)
        Returns:
            urls_explored: Количество успешно посещенных URL в этой сессии
        """
        # Используем новый метод с гарантированным timeout
        if not self._navigate_with_timeout(current_url, timeout=90):
            self.logger.error("Не удалось загрузить страницу, пропускаем")
            return
        
        # Более надежное ожидание загрузки
        try:
            # Ждем либо полной загрузки, либо interactive (достаточно для парсинга)
            WebDriverWait(self.driver, 10).until(
                lambda d: d.execute_script('return document.readyState') in ['complete', 'interactive']
            )
        except TimeoutException:
            self.logger.warning("⏱ Timeout при ожидании загрузки, но продолжаем")
            # Проверяем что хоть что-то загрузилось
            try:
                body = self.driver.find_element("tag name", "body")
                if not body:
                    raise RuntimeError("Страница пустая")
            except Exception:
                self.logger.error("Страница не загрузилась, пропускаем")
                return
                
        # Проверка на Cloudflare/Captcha
        try:
            page_title = self.driver.title.lower()
            page_source = self.driver.page_source.lower()  # Только начало для скорости
            
            # Проверка на защиту
            protection_indicators = [
                'cloudflare', 'captcha', 'are you a robot', 'access denied',
                'just a moment', 'challenge', 'verify you are human'
            ]
            
            if any(indicator in page_title or indicator in page_source 
                    for indicator in protection_indicators):
                self.logger.warning(f"🛡️ Обнаружена защита от ботов на {current_url}")
                self.logger.warning("Пауза 10 секунд для ручного решения...")
                time.sleep(10)  # Даем время решить вручную
                
                # Проверяем еще раз
                if any(indicator in self.driver.title.lower() for indicator in protection_indicators):
                    self.logger.error("Защита не пройдена, пропускаем URL")
                    return
        except Exception as e:
            self.logger.debug(f"Ошибка проверки защиты: {e}")
        
        self.slow_scroll_page(quick_mode=True)
        self.save_page_as_file("capcha_page", 1)
        time.sleep(2)  # Ждем стабилизации страницы
        page_source = self.driver.page_source
        # Применяем двухэтапный подход для поиска кнопки cookies
        self.logger.info("🔍 Начинаем поиск кнопки принятия cookies...")
        success = self.coockie_handler.find_and_click_cookie_button(page_source)
        
        if success:
            self.logger.info("✅ Cookies успешно приняты")
        else:
            self.logger.warning("⚠️ Не удалось найти или нажать кнопку cookies")



if __name__ == "__main__":
    ca = CapchaAccepter(debug_mode=True)
    ca.connect_to_chrome()
    ca.accept_capcha("https://www.teleculinaria.pt/receitas/lasanha-atum-legumes/")