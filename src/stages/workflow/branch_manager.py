from pathlib import Path
import subprocess
import os
import logging

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.stages.workflow.validate_extractor import ValidateParser
from src.stages.workflow.validation_models import ValidationReport

logger = logging.getLogger(__name__)


class BranchManager:
    """Класс для управления git ветками и валидации парсеров."""
    
    def __init__(self):
        self.repo_root = Path(__file__).parent.parent.parent.parent
        self.validator = ValidateParser()
    
    def _run_git_command(self, command: list[str]) -> str:
        """Выполняет git команду и возвращает её вывод."""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                cwd=self.repo_root
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка при выполнении команды '{' '.join(command)}': {e.stderr.strip()}")
            raise e
        
    def commit_specific_directory(self, directory: str, commit_message: str, push: bool = False) -> None:
        """Коммитит изменения в указанной директории с заданным сообщением.
        
        Args:
            directory: Путь к директории для коммита
            commit_message: Сообщение коммита
        """
        try:
            self._run_git_command(['git', 'add', directory])
            self._run_git_command(['git', 'commit', '-m', commit_message])
            logger.info(f"Изменения в директории {directory} успешно закоммичены.")
            if push:
                self._run_git_command(['git', 'push', 'origin', self.get_current_branch()])
                logger.info(f"Изменения в директории {directory} успешно запушены.")
        except Exception as e:
            logger.error(f"Ошибка при коммите изменений в директории {directory}: {e}")
            raise e
    
    def get_current_branch(self) -> str:
        """Получает имя текущей ветки."""
        output = self._run_git_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        return output
    
    def get_added_files(self, base_branch: str, target_branch: str) -> list[str]:
        """Получает список файлов, добавленных в target_branch относительно base_branch."""
        output = self._run_git_command([
            'git', 'log', 
            f'{base_branch}..{target_branch}',
            '--diff-filter=A',
            '--name-only',
            '--pretty=format:'
        ])
        
        # Фильтруем пустые строки и убираем дубликаты
        files = [f.strip() for f in output.split('\n') if f.strip()]
        return sorted(set(files))
    
    def check_branch(self, branch: str, chck_all_with_gpt: bool = False) -> list[ValidationReport]:
        """Обрабатывает одну ветку: переключается на нее, получает добавленные файлы и запускает валидацию.
        
        Args:
            branch: имя ветки для обработки
        
        Returns:
            Список ошибок валидации
        """
        current_branch = self.get_current_branch()
        branch_errors = []
        try:
            try:
                self._run_git_command(['git', 'checkout', branch])
                self._run_git_command(['git', 'pull', '--rebase', 'origin', branch]) # обновляем ветку после переключения на случай изменений копилотом
            except Exception:
                self._run_git_command(['git', 'fetch', 'origin'])
                self._run_git_command(['git', 'checkout', branch])
                logger.info(f"Переключились на ветку {branch} после fetch.")

            added_files = [f for f in self.get_added_files(current_branch, branch) 
                        if 'extractor' in f and f.endswith('.py') and 'test' not in f.lower()]
            
            if not added_files:
                logger.info(f"В ветке {branch} нет добавленных файлов парсеров.")
                return []

            for file in added_files:
                logger.info(f"Проверяем файл: {file}")
                module_name = os.path.basename(file).replace('.py', '')
                result = self.validator.validate(
                    module_name=module_name,
                    use_gpt=chck_all_with_gpt,
                    required_fields=['dish_name', 'ingredients', 'instructions'],
                    use_gpt_on_missing_fields=True
                )
                if result.failed > 0 or result.passed == 0:
                    branch_errors.append(result)
        
        except Exception as e:
            logger.error(f"Ошибка при проверке ветки {branch}: {e}")
            raise e
        finally:
            self._run_git_command(['git', 'checkout', current_branch])

        return branch_errors
    
    def delete_branch(self, branch: str) -> bool:
        """Удаляет локальную и удаленную ветку.
        
        Args:
            branch: имя ветки для удаления
        
        Returns:
            True если успешно удалена
        """
        try:
            self._run_git_command(['git', 'branch', '-D', branch])
            self._run_git_command(['git', 'push', 'origin', '--delete', branch])
            logger.info(f"Ветка {branch} успешно удалена локально и на удаленном репозитории.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении ветки {branch}: {e}")
            return False
    
    def update_current_branch(self) -> None:
        """Обновляет текущую ветку с удаленного репозитория."""
        current_branch = self.get_current_branch()
        self._run_git_command(['git', 'pull', '--rebase', 'origin', current_branch])
        logger.info(f"Текущая ветка {current_branch} обновлена из удаленного репозитория.")

if __name__ == '__main__':
    manager = BranchManager()
    manager.delete_branch('copilot/create-parser-for-sallysbakingaddiction')