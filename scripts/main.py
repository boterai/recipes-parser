"""
основной скрипт запуска
"""
import sys
import logging
from pathlib import Path
import argparse
import asyncio
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

# Базовая настройка только для консоли
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    """
    1. генерация тестовых данных для парсера
    1.1. автосоздание парсеров и их проверка (не совсем автоматизировано)
    2. создание и проверка созданных парсеров
    3. векторизация рецептов и изображений
    4. создание похожих рецептов (конкретно тут пока merge на одинаковых языках из одного кластера тк переводы недоступны)
    
    5. Полный pipeline (в идеале все должно работать из одного скрипта, основаная проблема в п 1.1)
    """    
    parser = argparse.ArgumentParser(description="Recipes Parser — управление парсингом и обработкой рецептов")
    subparsers = parser.add_subparsers(dest='command', help='Доступные команды')
    
   # 1. Генерация тестовых данных для создания парсеров
    prepare_parser = subparsers.add_parser('prepare', help='Генерация тестовых данных для создания парсеров при помощи copilot')
    prepare_parser.add_argument('--ports', type=int, nargs='+', default=[9222], help='Список портов Chrome (по умолчанию: 9222)')
    prepare_parser.add_argument('--target-sites-count', type=int, default=100, help='Колличество сайтов для подготовки (по умолчанию: 10)')
    prepare_parser.add_argument('--from-recipes', action='store_true', default=False, help='Генерировать запросы для поиска сайтов из уже собранных рецептов (по умолчанию: False)')
    prepare_parser.add_argument('--with-gpt', action='store_true', default=True, help='Генерировать новые запросы для поиска сайтов с помощью GPT (по умолчанию: True)')
    
    # 1.1. Создание парсеров и их проверка (пока автматизировано на уровне отдельных команд из-за отсуствия токена для аккаунта и невозможности тестирвоания)
    create_parser = subparsers.add_parser('create_parsers', help='Создание и проверка парсеров для сайтов')
    create_parser.add_argument('--issue-prefix', type=str, default="Создать парсер ", help='Префикс для названия issue (по умолчанию: "Создать парсер ")')
    create_parser.add_argument('--create-issues', action='store_true', default=False, help='Создавать новые issues для парсеров (по умолчанию: False)')
    create_parser.add_argument('--merge-prs', action='store_true', default=False, help='Проверять и сливать завершенные PRs (по умолчанию: False)')

    # 2. Парсинг сайтов
    parse_parser = subparsers.add_parser('parse', help='Запуск парсинга рецептов')
    parse_parser.add_argument('--ports',type=int,nargs='+', default=[9222], help='Список портов для параллельного запуска (по умолчанию: 9222)')
    parse_parser.add_argument('--modules',type=str, nargs='+', default=None, help='Имя модуля экстрактора для одиночного запуска (по умолчанию: None - параллельный запуск всех доступных модулей), имя модуля совпадает с именем сайта с заменой . на _(например: "eda.ru" имеет модуль "eda_ru")')
    parse_parser.add_argument('--max_recipes_per_site', type=int, default=4000, help='Максимальное количество рецептов для каждого модуля при параллельном запуске (если рецептов для модуля уже больше, парсер не запускается и будет пропущен) (по умолчанию: 10 000)')
    parse_parser.add_argument('--max_urls',type=int,default=10_000, help='Максимальное количество просмотренных URL для каждого сайта')
    parse_parser.add_argument('--max_depth',type=int,default=4, help='Максимальная глубина обхода ссылок при парсинге сайта')

    # 3. Векторизация
    vectorize_parser = subparsers.add_parser('vectorize', help='Векторизация рецептов и изображений')
    vectorize_parser.add_argument('--batch-size', type=int, default=9, help='Размер батча для embedding')
    vectorize_parser.add_argument('--images', action='store_true', help='Векторизовать изображения')
    vectorize_parser.add_argument('--recipes', action='store_true', help='Векторизовать рецепты')
    vectorize_parser.add_argument('--all', action='store_true', help='Векторизовать и рецепты и изображения')
    vectorize_parser.add_argument('--translate', action='store_true', default=True, help='Перевести рецепты перед векторизацией. Если выбрана векторизация рецептов, проверяется наличие не переведенных рецептов и при их наличии в начале выполняется перевод все рецептов (по умолчанию: True)')
    vectorize_parser.add_argument('--target-language', type=str, default="en", help='Целевой язык для перевода рецептов (по умолчанию: "en")')
    
    # 4. merge рецептов
    merge_parser = subparsers.add_parser('merge', help='Слияние похожих рецептов для создания новых рецептов')
    merge_parser.add_argument('--threshold', type=float, default=0.94, help='Порог схожести для слияния')
    merge_parser.add_argument('--cluster-type', type=str, choices=['ingredients', 'images', 'full'], default='ingredients', help='тип кластеризации для слияния (по умолчанию: ingredients), схожесть по ингредиентам, изображениям или по полной тех карте рецепта исключая изображение')
    merge_parser.add_argument('--limit', type=int, default=5, help='Максимальное количество похожих рецептов для слияния (по умолчанию: 5)')
    merge_parser.add_argument('--validate-gpt', action='store_true', default=True, help='Валидировать слияния с помощью GPT (по умолчанию: True)')
    merge_parser.add_argument('--save-to-db', action='store_true', default=True, help='Сохранять новые рецепты в базу данных (по умолчанию: True)')
    merge_parser.add_argument('--max-merged-recipes', type=int, default=3, help='Максимальное количество рецептов в одном слиянии (по умолчанию: 3)')
    merge_parser.add_argument('--merge-different-langs', action='store_true', default=False, help='Выполнять слияние рецептов из разных языков (по умолчанию: False). Слияние выполняется только для рецептов на одинаковых языках, при этом не используется mysql')

    if len(sys.argv) == 1:
        sys.argv.extend(['vectorize', '--recipes'])
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)

    match args.command:
        case 'prepare': 
            from scripts.prepare_site import run_parallel_preparation

            run_parallel_preparation(
                ports=args.ports,
                target_sites_count=args.target_sites_count,
                generate_from_recipes=args.from_recipes,
                generate_with_gpt=args.with_gpt
            )
        case 'create_parsers':
            if args.create_issues:
                from scripts.prepare_site import create_issues
                create_issues(issue_prefix=args.issue_prefix)
            if args.merge_prs:
                from scripts.prepare_site import merge_completed_prs
                merge_completed_prs()
        case 'parse':
            from scripts.parse import run_parallel
            run_parallel(
                modules=args.modules if args.modules else None,
                ports=args.ports,
                max_recipes_per_module=args.max_recipes_per_site,
                max_urls=args.max_urls,
                max_depth=args.max_depth
            )
        case 'vectorize':
            from scripts.vectorize import vectorise_all_images, vectorise_all_recipes
            if args.recipes or args.all:
                vectorise_all_recipes(
                    translate=args.translate,
                    target_language=args.target_language
                )
            if args.images or args.all:
                vectorise_all_images(batch_size=args.batch_size)
        case 'merge':
                from scripts.merge import run_merge_with_same_lang
                asyncio.run(run_merge_with_same_lang(
                    score_thresold=args.threshold,
                    build_type=args.cluster_type,
                    max_merged_recipes=args.limit,
                    max_variations=args.max_merged_recipes,
                    validate_gpt=args.validate_gpt,
                    save_to_db=args.save_to_db
                ))

        
