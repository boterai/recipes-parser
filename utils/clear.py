from pathlib import Path
import re

def get_dir_size(path: Path| str) -> int:
    total_size = 0
    path = Path(path)
    for item in path.rglob('*'):
        if item.is_file():
            total_size += item.stat().st_size
    return total_size


def clear_folder(path: Path| str, max_size_bytes: float | None = None, exclude_files: list[str] = None):
    """
    Очищает папку от всех файлов и папок, кроме указанных в exclude_files. Если max_size_gb указан, очищает только если размер папки превышает этот порог.
    Args:
        path: Путь к папке для очистки
        max_size_gb: Максимальный размер папки в GB, при котором очистка не требуется (по умолчанию: None - очистка всегда)
        exclude_files: Список имен (могут быть переданы regex выражения) файлов, которые не будут удалены (по умолчанию: None - все файлы будут удалены)
    """
    path = Path(path)
    current_size = get_dir_size(path)
    print(f"Текущий размер папки {path.name}: {current_size:.2f} Bytes")
    if max_size_bytes and current_size <= max_size_bytes:
        print(f"Размер папки {current_size:.2f} не превышает {max_size_bytes}, очистка не требуется.")
        return
    if not exclude_files: exclude_files = []

    for item in path.rglob('*'):
        if item.is_file():
            if not any(re.match(pattern, item.name) is not None for pattern in exclude_files):
                item.unlink()
        elif item.is_dir():
            clear_folder(item, exclude_files=exclude_files)  # Рекурсивно очищаем папки
            if not any(item.iterdir()):  # Если папка пуста после очистки, удаляем её
                item.rmdir()