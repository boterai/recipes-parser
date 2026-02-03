"""
Скрипт для векторизации рецептов из БД в Qdrant
"""

import sys
import os
from pathlib import Path
import logging
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.embedding import get_embedding_function, get_siglip_embedding_function
from src.stages.search.vectorise import RecipeVectorizer
from src.stages.search.vectorise import RecipeVectorizer
from src.models.image import ImageORM, download_image_async
from src.stages.translate import Translator

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

def vectorise_all_recipes(translate: bool = True, target_language: str = "en", translate_batch_size: int = 9):
    if translate:
        translate_all_recipes(target_language=target_language, translate_batch_size=translate_batch_size)

    batch_size = 15 # примерный размер батча для векторизации и добавления в Qdrant при котором не происходит timeout
    rv = RecipeVectorizer()

    embed_func, dims = get_embedding_function(batch_size=batch_size)
    rv.vectorise_all_recipes(
        embedding_function=embed_func,
        batch_size=batch_size,
        dims=dims)


async def validate_and_save_image(image_url: str, save_dir: str = "images", use_proxy: bool = True) -> str | None:
    """
    Проверяет валидность URL, скачивает изображение и сохраняет локально.
    
    Args:
        image_url: URL изображения для проверки и скачивания
        save_dir: Директория для сохранения (по умолчанию: ./images)
        timeout: Таймаут запроса в секундах
    
    Returns:
        Путь к сохраненному файлу или None при ошибке
    """
    try:
        # Скачиваем изображение как PIL.Image
        img = await download_image_async(image_url, use_proxy=use_proxy)
        if img is None:
            return None
        
        os.makedirs(save_dir, exist_ok=True)
        
        hash_name = ImageORM.hash_url(image_url)[:16]
        
        img_format = img.format or 'JPEG'
        ext = '.jpg' if img_format == 'JPEG' else f'.{img_format.lower()}'
        
        filename = hash_name + ext
        file_path = os.path.join(save_dir, filename)
        
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
            ext = '.jpg'
            filename = hash_name + ext
            file_path = os.path.join(save_dir, filename)
        
        img.save(file_path, quality=90, optimize=True)
        
        logger.info(f"Saved image: {image_url} -> {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"Failed to validate/save image {image_url}: {e}")
        return None

async def vectorise_all_images():
    rv = RecipeVectorizer()
    embed_function, dims = get_siglip_embedding_function(
        batch_size=16
    )
    await rv.vectorise_images_async(embed_function=embed_function, image_dims=dims)

def translate_all_recipes(target_language: str = "en", translate_batch_size: int = 10):
    translator = Translator(target_language=target_language)
    asyncio.run(translator.translate_all(batch_size=translate_batch_size))

if __name__ == '__main__':
    #asyncio.run(vectorise_all_images())
    asyncio.run(vectorise_all_recipes()) # Векторизация рецептов (по дефолту всех рецептов, содержащихся в clickhouse)
