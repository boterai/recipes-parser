import subprocess
from pathlib import Path
import os

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.stages.validate.validate_branch import ValidateParser
import json

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
        print(f"Ошибка при выполнении команды '{command}': {e.stderr.strip()}")
        return ""

def get_copilot_branches() -> list[str]:
    """Получает список всех веток (локальных и удаленных)."""
    # Получить все ветки
    run_git_command(['git', 'fetch', '--all'])
    
    # Получить список веток
    output = run_git_command(['git', 'branch', '-a'])
    
    # Парсим вывод (берем только copilot ветки)
    branches = []
    for line in output.split('\n'):
        branch = line.strip().replace('* ', '')
        if 'copilot' in branch:
            # Убираем префикс remotes/origin/
            #if branch.startswith('remotes/origin/'):
            #    branch = branch.replace('remotes/origin/', '')
            branches.append(branch)
    
    # Убираем дубликаты
    return list(set(branches))

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

def check_all_branches():
    current_branch = get_current_branch()
    print(f"Текущая ветка: {current_branch}")
    copilot_branches = get_copilot_branches()
    # получаем список изменений для каждой ветки
    parsers: dict[str, list[str]] = {}
    for branch in copilot_branches:
        added_files = [f for f in get_added_files('feature/parser', branch) if ('extractor' in f and f.endswith('.py'))]
        if len(added_files) == 0:
            print(f"Ветка {branch} не содержит изменений в парсере, пропускаем.")
            continue  

        parsers[branch] = added_files

    print("Ветки с изменениями в парсере:")
    for branch, files in parsers.items():
        print(f"Ветка: {branch}")
        run_git_command(['git', 'checkout', branch])
        run_git_command(['git', 'cherry-pick', '3746ae4']) # временный фикс для импорта
        vp = ValidateParser()

        branch_errors = []
        try:
            for file in files:
                print(f"Проверяем файл: {file}")
                module_name = os.path.basename(file).replace('.py', '')
                branch_errors.append(vp.validate(
                    module_name=module_name,
                    use_gpt=False,
                    required_fields=['dish_name', 'ingredients', 'instructions'],
                    use_gpt_on_errors_only=True
                ))
        except Exception as e:
            print(f"Ошибка при валидации ветки {branch}: {e}")
            branch_errors.append({'error': str(e)})
            run_git_command(['git', 'checkout', current_branch])
            continue
        # запускаем валидацию
        run_git_command(['git', 'checkout', current_branch])
        if not branch_errors:
            print(f"Ветка {branch} прошла валидацию без ошибок.")
            # производим merge ветки в текущую и удаляем ее
            run_git_command(['git', 'merge', branch])
            run_git_command(['git', 'branch', '-d', branch])
        else:
            print(f"Ветка {branch} содержит ошибки валидации:")
            print(json.dumps(branch_errors, ensure_ascii=False, indent=2))
            os.makedirs(os.path.join("parsers_errors"), exist_ok=True)
            with open(os.path.join("parsers_errors", f"errors_{branch.replace('/', '_')}.json"), 'w', encoding='utf-8') as f:
                json.dump(branch_errors, f, ensure_ascii=False, indent=2)

    # переключаемся на каждую ветку и запускаем валидацию с сохранением ошибку в папку, 
    # при наличии ошибки результат возаращаем
        


if __name__ == '__main__':
    check_all_branches()
    
    vp = ValidateParser()
    
    # Пример: валидация с GPT
    result = vp.validate(
        module_name="xrysessyntages_com",
        use_gpt=False,
        required_fields=['dish_name', 'ingredients', 'instructions'],
        use_gpt_on_errors_only=True
    )
    
    print(json.dumps(result, ensure_ascii=False, indent=2))