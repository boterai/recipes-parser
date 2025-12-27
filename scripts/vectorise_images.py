import requests
import logging
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.embedding import get_image_embedding_function
from src.stages.search.vectorise import RecipeVectorizer
from src.repositories.page import PageRepository
from src.repositories.image import ImageRepository
from src.models.image import ImageORM, download_image

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def validate_and_save_image(image_url: str, save_dir: str = "images", timeout: float = 30.0) -> str | None:
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
        img = download_image(image_url, timeout=timeout)
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

def migrate_image_urls(save_image: bool = False):
    """
    переносит image_urls из таблицы pages в таблицу images
    1. для каждой страницы с image_urls
    2. если в images нет такой записи, скачивает и сохраняет изображение
    3. если запись есть, пропускает
    """
    pr = PageRepository()
    ir = ImageRepository()

    for site in pr.get_recipe_sites():
        pages = pr.get_by_site(site_id=site)

        for page in pages:
            url: str = page.image_urls
            if not url:
                continue
            if ',' in url:
                url_list: list[str] = url.split(',')
                url_list = [u.strip() for u in url_list if u.strip()]
            else:
                url_list = [url.strip()]

            for image_url in url_list:
                existing_images: ImageORM = ir.get_by_page_id(page.id)
                if existing_images:
                    logger.info(f"Image already exists in DB: {image_url}")
                    continue
                
                # Скачиваем и сохраняем изображение
                local_path = None
                if save_image:
                    local_path = validate_and_save_image(image_url)
                    if local_path is None:
                        logger.warning(f"Skipping invalid/failed image URL: {image_url}")
                        continue
                
                new_image = ImageORM(
                    page_id=page.id,
                    image_url=image_url,
                    local_path=local_path,
                    vectorised=False
                )
                ir.upsert(new_image)
                logger.info(f"Added new image to DB: {image_url}")

def vectorise_images():
    rv = RecipeVectorizer()
    embed_function, _ = get_image_embedding_function(
        batch_size=16
    )
    rv.vectorise_images(
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
    vectorise_images()