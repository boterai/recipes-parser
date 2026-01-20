from pathlib import Path
import subprocess
import os
import logging

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.stages.workflow.validate_extractor import ValidateParser

logger = logging.getLogger(__name__)

def run_git_command(command: list[str]) -> str:
    """Выполняет git команду и возвращает её вывод."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent.parent.parent.parent
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при выполнении команды '{command}': {e.stderr.strip()}")
        raise e

def get_added_files(base_branch: str, target_branch: str) -> list[str]:
    """Получает список файлов, добавленных в target_branch относительно base_branch."""
    output = run_git_command([
        'git', 'log', 
        f'{base_branch}..{target_branch}',
        '--diff-filter=A',
        '--name-only',
        '--pretty=format:'
    ])
    
    # Фильтруем пустые строки и убираем дубликаты
    files = [f.strip() for f in output.split('\n') if f.strip()]
    return sorted(set(files))

def get_current_branch() -> str:
    """Получает имя текущей ветки."""
    output = run_git_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
    return output

def check_one_branch(branch: str) -> list[dict]:
    """Обрабатывает одну ветку: переключается на нее, получает добавленные файлы и запускает валидацию.
    
    Args:
        branch: имя ветки для обработки
        current_branch: имя текущей ветки (для возврата после обработки)
    
    Returns:
        Список ошибок валидации
    """
    current_branch = get_current_branch()
    try:
        run_git_command(['git', 'checkout', branch])
    except Exception as e:
        run_git_command(['git', 'fetch', 'origin'])
        run_git_command(['git', 'checkout', branch])
        logger.info(f"Переключились на ветку {branch} после fetch.")

    added_files = [f for f in get_added_files(current_branch, branch) if ('extractor' in f and f.endswith('.py'))]
    
    if len(added_files) == 0:
        logger.info(f"В ветке {branch} нет добавленных файлов парсеров.")
        return []  

    vp = ValidateParser()

    branch_errors = []
    try:
        for file in added_files:
            print(f"Проверяем файл: {file}")
            module_name = os.path.basename(file).replace('.py', '')
            result = vp.validate(
                module_name=module_name,
                use_gpt=False,
                required_fields=['dish_name', 'ingredients', 'instructions'],
                use_gpt_on_errors_only=True
            )
            if result.get('failed', 0) > 0 or result.get('total_files', 0) == 0:
                branch_errors.append(result)
    except Exception as e:
        print(f"Ошибка при валидации ветки {branch}: {e}")
        branch_errors.append({'error': str(e)})
    
    run_git_command(['git', 'checkout', current_branch])

    return branch_errors


if __name__ == '__main__':
    check_one_branch('copilot/create-parser-for-sallysbakingaddiction')