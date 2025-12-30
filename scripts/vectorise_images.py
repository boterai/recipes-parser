import logging
import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.embedding import get_image_embedding_function
from src.stages.search.vectorise import RecipeVectorizer
from src.repositories.page import PageRepository
from src.repositories.image import ImageRepository
from src.models.image import ImageORM, download_image_async
from itertools import batched
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


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

async def migrate_image_urls(save_image: bool = False, batch_size: int = 10):
    """
    переносит image_urls из таблицы pages в таблицу images
    1. для каждой страницы с image_urls
    2. если в images нет такой записи, скачивает и сохраняет изображение
    3. если запись есть, пропускает
    """
    pr = PageRepository()
    ir = ImageRepository()

    for site in pr.get_recipe_sites():
        if site <= 5:
            continue
        error_pages = []
        while  (pages := pr.get_pages_without_images(site_id=site, limit=batch_size, exclude_pages=error_pages)):
            if not pages:
                break
            logger.info(f"Processing site {site}, found {len(pages)} pages batch with image URLs")
            

            # получаем все image_urls из страниц с привязкой к page_id
            url_page_mapping = []  # [(url, page_id), ...]
            for page in pages:
                url: str = page.image_urls
                if not url:
                    continue
                if ',' in url:
                    urls = [u.strip() for u in url.split(',') if u.strip()]
                    url_page_mapping.extend([(u, page.id) for u in urls])
                else:
                    url_page_mapping.append((url.strip(), page.id))
            
            if not url_page_mapping:
                logger.info(f"No image URLs found for site {site}")
                continue
            
            # скачиваем и сохраняем изображения
            if save_image:
                tasks = [validate_and_save_image(url, use_proxy=True) for url, _ in url_page_mapping]
                saved_paths = await asyncio.gather(*tasks)
            else:
                saved_paths = [None] * len(url_page_mapping)
            
            # создаем записи изображений
            new_images = []
            for (image_url, page_id), saved_path in zip(url_page_mapping, saved_paths):
                new_image = ImageORM(
                    page_id=page_id,
                    image_url=image_url,
                    local_path=saved_path,
                    vectorised=False
                )
                new_images.append(new_image)
            
            if new_images:
                updated_img = ir.bulk_create(new_images)
                if len(updated_img) < len(new_images):
                    logger.warning(f"Some images were not added to DB for site {site}")
                    error_img = set(new_images) - set(updated_img)
                    for img in error_img:
                        error_pages.append(img.page_id)

                logger.info(f"Added {len(new_images)} images to DB for site {site}")

async def vectorise_images():
    rv = RecipeVectorizer()
    embed_function, _ = get_image_embedding_function(
        batch_size=16
    )
    await rv.vectorise_images_async(
        embed_function=embed_function,
        limit=1000
    )

def search_similar(image_id: int = 1, limit: int = 6):
    rv = RecipeVectorizer()
    embed_function, _ = get_image_embedding_function(
        batch_size=1
    )
    results = rv.get_similar_images(
        embed_function=embed_function,
        image_id=image_id,
        limit=limit,
        score_threshold=0.0
    )
    for score, image in results:
        print(f"ID: {image.id}, URL: {image.image_url}, Score: {score}")



if __name__ == "__main__":
    asyncio.run(migrate_image_urls(save_image=True))
    #asyncio.run(vectorise_images())
    #migrate_image_urls(True)