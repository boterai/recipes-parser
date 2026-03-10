"""
deploy в aws только обновленных файлов
"""
import dotenv
import aioboto3
import asyncio
import os
from pathlib import Path
from typing import Set, List

def get_local_files(folder_path: str) -> Set[str]:
    """Получить список всех локальных файлов относительно базовой папки."""
    local_files = set()
    base_path = Path(folder_path)
    
    if not base_path.exists():
        print(f"Папка {folder_path} не существует")
        return local_files
    
    for file_path in base_path.rglob('*'):
        if file_path.is_file():
            relative_path = file_path.relative_to(base_path)
            local_files.add(str(relative_path))
    
    return local_files

async def get_s3_files(s3_client, bucket_name: str) -> Set[str]:
    """Получить список всех файлов в S3 бакете."""
    s3_files = set()
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name)
        
        async for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    s3_files.add(obj['Key'])
        
        print(f"Найдено {len(s3_files)} файлов в бакете {bucket_name}")
    except Exception as e:
        print(f"Ошибка при получении списка файлов из S3: {e}")
    
    return s3_files

async def upload_file(s3_client, local_path: str, bucket_name: str, s3_key: str, semaphore: asyncio.Semaphore) -> tuple:
    """Загрузить один файл в S3."""
    async with semaphore:
        try:
            with open(local_path, 'rb') as f:
                await s3_client.upload_fileobj(f, bucket_name, s3_key)
            return (s3_key, True, None)
        except Exception as e:
            return (s3_key, False, str(e))

async def upload_files_batch(s3_client, files_to_upload: List[tuple], bucket_name: str, max_concurrent: int = 10):
    """Загрузить файлы батчами используя асинхронность."""
    total = len(files_to_upload)
    uploaded = 0
    failed = 0
    
    print(f"\nНачинается загрузка {total} файлов (макс. {max_concurrent} одновременных)...")
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    tasks = [
        upload_file(s3_client, local_path, bucket_name, s3_key, semaphore)
        for local_path, s3_key in files_to_upload
    ]
    
    for coro in asyncio.as_completed(tasks):
        s3_key, success, error = await coro
        if success:
            uploaded += 1
            if uploaded % 100 == 0:
                print(f"Загружено {uploaded}/{total} файлов...")
        else:
            failed += 1
            print(f"Ошибка загрузки {s3_key}: {error}")
    
    print(f"\nЗагрузка завершена: {uploaded} успешно, {failed} ошибок")

async def deploy(folder_to_upload: str, bucket_name: str, max_concurrent: int = 10):
    """
    Загрузить в S3 только те файлы, которых там еще нет.
    
    Args:
        folder_to_upload: Путь к локальной папке
        bucket_name: Имя S3 бакета
        max_concurrent: Количество одновременных загрузок
    """
    aws_access = {
        "region_name": os.getenv('AWS_REGION'),
        "aws_access_key_id": os.getenv('AWS_ACCESS_KEY_ID'),
        "aws_secret_access_key": os.getenv('AWS_SECRET_ACCESS_KEY')
    }
    
    session = aioboto3.Session(**aws_access)
    
    print(f"Сканирование локальной папки: {folder_to_upload}")
    local_files = get_local_files(folder_to_upload)
    print(f"Найдено {len(local_files)} локальных файлов")
    
    async with session.client('s3') as s3:
        print(f"\nПолучение списка файлов из бакета {bucket_name}...")
        s3_files = await get_s3_files(s3, bucket_name)
        
        # Файлы, которых нет в S3
        files_to_upload = local_files - s3_files
        
        if not files_to_upload:
            print("\nВсе файлы уже загружены в S3. Нечего обновлять.")
            return
        
        print(f"\nНайдено {len(files_to_upload)} новых файлов для загрузки")
        
        # Подготовить список с полными путями
        base_path = Path(folder_to_upload)
        upload_list = [
            (str(base_path / file_path), file_path)
            for file_path in files_to_upload
        ]
        
        # Загрузить файлы батчами
        await upload_files_batch(s3, upload_list, bucket_name, max_concurrent=max_concurrent)


if __name__ == '__main__':
    dotenv.load_dotenv()
    
    folder = "recipe-parser-frontend/dist"
    bucket = os.getenv('S3_BUCKET_NAME', 'sdfjdsfd324i234j3223nrecipesite')
    
    asyncio.run(deploy(folder, bucket, max_concurrent=20))
    