"""
Генератор промптов для создания парсеров на основе preprocessed данных
"""

import os
import sys
import logging
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.repositories.site import SiteRepository

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PromptGenerator:
    """Генератор промптов для парсеров рецептов"""
    
    def __init__(self, 
                 preprocessed_dir: str = "preprocessed",
                 template_file: str = "parser_prompt.md",
                 output_dir: str = "prompts"):
        """
        Args:
            preprocessed_dir: Директория с preprocessed данными
            template_file: Файл-шаблон промпта
            output_dir: Директория для сохранения промптов
        """
        self.preprocessed_dir = Path(preprocessed_dir)
        self.template_file = Path(template_file)
        self.output_dir = Path(output_dir)
        self.site_repository = SiteRepository()
        
        # Создаем директорию для промптов если не существует
        self.output_dir.mkdir(exist_ok=True)
    
    def scan_preprocessed_folders(self) -> List[str]:
        """
        Сканирует папку preprocessed и получает имена всех подпапок
        
        Returns:
            Список имен модулей (названий папок)
        """
        if not self.preprocessed_dir.exists():
            logger.error(f"Директория не найдена: {self.preprocessed_dir}")
            return []
        
        module_names = []
        for item in self.preprocessed_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                module_names.append(item.name)
        
        logger.info(f"Найдено {len(module_names)} модулей в preprocessed/")
        return module_names
    
    def load_template(self) -> str:
        """
        Загружает шаблон промпта из файла
        
        Returns:
            Содержимое шаблона
        """
        if not self.template_file.exists():
            logger.error(f"Файл шаблона не найден: {self.template_file}")
            return ""
        
        with open(self.template_file, 'r', encoding='utf-8') as f:
            template = f.read()
        
        logger.info(f"Шаблон загружен из {self.template_file}")
        return template
    
    def generate_prompt(self, module_name: str, site_domain: str, template: str) -> str:
        """
        Генерирует промпт для конкретного сайта
        
        Args:
            module_name: Имя модуля (например, allrecipes_com)
            site_domain: Базовый URL сайта (например, https://www.allrecipes.com)
            template: Шаблон промпта
        
        Returns:
            Сгенерированный промпт
        """
        # Удаляем протокол и www из домена для чистоты
        clean_domain = site_domain.replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')
        
        prompt = template.replace('{MODULE_NAME}', module_name)
        prompt = prompt.replace('{SITE_DOMAIN}', clean_domain)
        
        return prompt
    
    def save_prompt(self, module_name: str, prompt: str) -> bool:
        """
        Сохраняет промпт в файл
        
        Args:
            module_name: Имя модуля
            prompt: Содержимое промпта
        
        Returns:
            True если успешно сохранено
        """
        output_file = self.output_dir / f"{module_name}_prompt.md"
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(prompt)
            
            logger.info(f"✓ Промпт сохранен: {output_file}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения промпта для {module_name}: {e}")
            return False
    
    def generate_all_prompts(self, save_to_files: bool = False) -> dict:
        """
        Генерирует промпты для всех модулей из preprocessed
        
        Returns:
            dict {имя_модуля: промпт}
        """
        # Загружаем шаблон
        template = self.load_template()
        if not template:
            logger.error("Не удалось загрузить шаблон")
            return {}
        
        # Получаем список модулей
        module_names = self.scan_preprocessed_folders()
        if not module_names:
            logger.warning("Не найдено модулей для генерации")
            return {}
        
        logger.info(f"\n{'='*70}")
        logger.info(f"ГЕНЕРАЦИЯ ПРОМПТОВ ДЛЯ {len(module_names)} МОДУЛЕЙ")
        logger.info(f"{'='*70}\n")
        
        prompt_dict = {}
        
        for idx, module_name in enumerate(module_names, 1):
            logger.info(f"\n[{idx}/{len(module_names)}] Обработка модуля: {module_name}")
            
            # Получаем сайт из БД по имени
            site = self.site_repository.get_by_name(module_name)
            
            if not site:
                logger.warning(f"  ⚠ Сайт '{module_name}' не найден в БД, пропускаем")
                continue
            
            logger.info(f"  Найден сайт: {site.base_url}")
            
            # Генерируем промпт
            prompt = self.generate_prompt(module_name, site.base_url, template)
            
            # Сохраняем
            if save_to_files:
                if self.save_prompt(module_name, prompt):
                    prompt_dict[module_name] = prompt
                else:
                    logger.error(f"  ✗ Ошибка сохранения промпта для {module_name}")
            else:
                prompt_dict[module_name] = prompt
        
        logger.info(f"\n{'='*70}")
        logger.info(f"ИТОГО: {len(prompt_dict)}/{len(module_names)} промптов создано")
        logger.info(f"Директория: {self.output_dir.absolute()}")
        logger.info(f"{'='*70}\n")
        
        return prompt_dict


def main():
    """Точка входа"""
    generator = PromptGenerator()
    
    try:
        count = generator.generate_all_prompts()
        
        if count > 0:
            logger.info(f"✓ Успешно сгенерировано {count} промптов")
        else:
            logger.warning("Ни одного промпта не было создано")
    
    except KeyboardInterrupt:
        logger.info("\n⌨Прервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        generator.site_repository.close()


if __name__ == "__main__":
    main()
