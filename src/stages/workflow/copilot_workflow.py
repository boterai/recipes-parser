from pathlib import Path
import os
import logging

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.stages.workflow.generate_prompt import PromptGenerator
from src.common.github.client import GitHubClient
from src.stages.workflow.branch_manager import BranchManager
from src.stages.workflow.validation_models import ValidationReport
import tempfile
import json
from datetime import datetime
from config.config import config

logger = logging.getLogger(__name__)

def get_tempdir():
    if os.name == 'posix':
        try:
            test_filename = os.path.join('/var','tmp','test_file.txt')
            with open(test_filename, 'wb') as f: f.write(b'test')
            with open(test_filename, 'rb') as f: f.read()
            os.remove(test_filename)
            return os.path.join('/var','tmp')
        except Exception as e:
            logger.warning(f"Не удалось использовать /var/tmp в качестве временной директории: {e}. Будет использована стандартная временная директория.")
    return tempfile.gettempdir()

ISSUE_PREFIX = "Создать парсер "
TEMPDIR = get_tempdir()

class CopilotWorkflow:

    def __init__(self):
        self.prompt_generator = PromptGenerator()
        self.github_client = GitHubClient()
        self.branch_manager = BranchManager()
        self.pr_filename = os.path.join(TEMPDIR, "pr_changes.json")

    def autocommit_preprocessed_data(self, commit_message: str = "Автокоммит тестовых данных на основе которых нужно делать парсеры", push: bool = True):
        """Автокоммитит preprocessed данные в текущую ветку.
        
        Args:
            commit_message: Сообщение коммита
        """
        self.branch_manager.commit_specific_directory(
            directory=str(self.prompt_generator.preprocessed_dir),
            commit_message=commit_message,
            push=push
        )
        
    def create_issues_for_parsers(self, issue_prefix: str = ISSUE_PREFIX):
        """Создает GitHub issues с промптами для создания парсеров на основе preprocessed данных."""
        current_issues = self.github_client.list_repository_issues(state="all")
        existing_titles = {issue['title'] for issue in current_issues} if current_issues else set()

        preprocessed_sites = self.prompt_generator.scan_preprocessed_folders()
        present_extractors = self.prompt_generator.scan_extractor_folder()
        site_names = [i for i in preprocessed_sites if issue_prefix + i not in existing_titles and i not in present_extractors] 

        if not site_names:
            logger.info("Нет новых модулей для создания issues.")
            return

        prompts = self.prompt_generator.generate_prompts_for_sites(site_names)
        if not prompts:
            logger.info("Нет промптов для создания issues.")
            return
        
        logger.info(f"Создание {len(site_names)} новых issues для парсеров...")

        for module_name in site_names:
            title = issue_prefix + module_name
            issue = self.github_client.create_issue_from_dict(
                title=title,
                body=prompts[module_name]
            )
            if issue:
                logger.info(f"Создан issue: {issue['html_url']}")
            else:
                logger.error(f"Не удалось создать issue для модуля: {module_name}")

    def make_pr_comment_from_errors(self, errors: list[ValidationReport]) -> str:
        """Формирует комментарий к PR на основе ошибок валидации парсера.
        
        Args:
            errors: Список ошибок валидации
        
        Returns:
            Текст комментария
        """
        pr_comment = "Валидация парсера выявила следующие проблемы, исправь их:\n\n"
        pr_comment += "⚠️ **ВАЖНО**: Обязательны только 3 поля: dish_name, ingredients, instructions\n"
        pr_comment += "Остальные поля (cook_time, prep_time, tags и т.д.) опциональны и их отсутствие допустимо.\n\n"
        
        for error in errors:
            pr_comment += f"### Модуль: `{error.module}`\n"
            pr_comment += f"- Всего файлов: {error.total_files}\n"
            pr_comment += f"- Ошибок: {error.failed}\n\n"
            
            for detail in error.details:
                pr_comment += f"#### 📄 Файл: `{detail.file}`\n"
                pr_comment += f"- Статус: **{detail.status}**\n"
                
                pr_comment += f"- Валидация: {'✅ Корректно' if detail.is_valid else '❌ Некорректно'}\n"
                pr_comment += f"- Это рецепт: {'Да' if detail.is_recipe else 'Нет'}\n"
                
                if not detail.is_valid:
                    if detail.feedback:
                        pr_comment += f"- **Отзыв**: {detail.feedback}\n\n"
                    
                    if detail.missing_fields:
                        pr_comment += f"- **Отсутствующие поля**: {', '.join(detail.missing_fields)}\n"
                    
                    if detail.incorrect_fields:
                        pr_comment += f"- **Некорректные поля**: {', '.join(detail.incorrect_fields)}\n"
                    
                    if detail.fix_recommendations:
                        pr_comment += "\n**Рекомендации по исправлению:**\n\n"
                        for idx, rec in enumerate(detail.fix_recommendations, 1):
                            pr_comment += f"{idx}. **Поле**: `{rec.field}`\n"
                            pr_comment += f"   - Проблема: {rec.issue}\n"
                            
                            # Отображаем доступные поля из FieldValidation
                            if rec.correct_value_from_text:
                                pr_comment += f"   - Правильное значение из текста: `{rec.correct_value_from_text}`\n"
                            
                            if rec.actual_extracted_value:
                                pr_comment += f"   - Извлеченное значение: `{rec.actual_extracted_value}`\n"
                            
                            if rec.text_context:
                                pr_comment += f"   - Контекст в тексте: _{rec.text_context}_\n"
                            
                            if rec.pattern_hint:
                                pr_comment += f"   - Паттерн: {rec.pattern_hint}\n"
                            
                            if rec.fix_suggestion:
                                pr_comment += f"   - **Как исправить**: {rec.fix_suggestion}\n\n"
                else:
                    pr_comment += "\n"
                
                pr_comment += "---\n\n"
        
        return pr_comment
    
    def save_pr_request_changes(self, pr_number: int):
        """Сохраняет в локальную директорию временные данные для PR с требованием изменений.
        
        Args:
            pr_number: Номер pull request
        """
        pr_data = {}
        if  os.path.exists(self.pr_filename):        
            with open(self.pr_filename, 'r', encoding='utf-8') as f:
                pr_data = json.load(f)
        
        pr_data[str(pr_number)] = datetime.now().astimezone().isoformat()

        with open(self.pr_filename, 'w', encoding='utf-8') as f:
            json.dump(pr_data, f, ensure_ascii=False, indent=2)

    def is_pr_updated_since_last_check(self, pr_number: int) -> bool:
        """Проверяет, были ли новые коммиты в PR с момента последней проверки.
        """
        if not os.path.exists(self.pr_filename):
            return True  # файл не существует, значит проверяем впервые
        
        with open(self.pr_filename, 'r', encoding='utf-8') as f:
            pr_data = json.load(f)

        pr_key = str(pr_number)
        if pr_key not in pr_data:
            return True  # PR не найден в истории, проверяем впервые
        
        saved_commit_date_str = pr_data[pr_key]
        
        current_commit_date = self.github_client.get_last_commit_date(pr_number)
        if not current_commit_date:
            logger.warning(f"Не удалось получить дату последнего коммита для PR #{pr_number}")
            return False
        
        saved_commit_date = datetime.fromisoformat(saved_commit_date_str)
        
        return current_commit_date > saved_commit_date

    def is_pr_completed_by_copilot(self, pr_number: int) -> bool:
        """Проверяет, завершил ли Copilot работу над PR.
        
        Args:
            pr_number: Номер pull request
        """
        timeline_events = self.github_client.get_pr_timeline_events(pr_number)
        if not timeline_events:
            logger.warning(f"Не удалось получить timeline для PR #{pr_number}")
            return False
        
        for event in reversed(timeline_events):
            if event.get('event') == 'committed' or event.get('event') == 'copilot_work_started':
                return False  # если видим коммит или старт работы, значит copilot еще не закончил
            if event.get('event') == 'copilot_work_finished':
                return True

        logger.info(f"Для PR #{pr_number}, Copilot еще не завершил работу.")
        return False


    def check_review_requested_prs(self):
        """Проверяет завершенные PR и обновляет статусы задач.
        Для каждого PR с запрошенным ревью выполняет валидацию парсера.
        Note: аккаунт назначающий copilot и reviewer должен быть одним и тем же, иначе не сработает.
        """
        prs = self.github_client.list_pr()
        completed_prs = [pr for pr in prs if self.is_pr_completed_by_copilot(pr['number'])]
        logger.info(f"Найдено {len(completed_prs)} PR с завершенной работой Copilot.")
        new_files_added: bool = False
        for pr in completed_prs:
            logger.info(f"Проверка PR #{pr['number']}: {pr['title']}")
            # проверяем были ли новые коммиты с момента последней проверки
            if not self.is_pr_updated_since_last_check(pr['number']):
                logger.info(f"В PR #{pr['number']} нет новых коммитов с момента последней проверки. Пропуск валидации.")
                continue
            errors: list[ValidationReport] = self.branch_manager.check_branch(pr['head']['ref'], chck_all_with_gpt=True) # проверяем гпт только если нет каких-то нужных полей
            # проверка, чтобы в результате не было системной ошибки иначе пропускаем обновление статуса pr
            if any(err.system_errors for err in errors):
                logger.error(f"PR #{pr['number']} не прошел валидацию из-за системной ошибки. Пропуск обновления статуса, попробуем позже.")
                continue
            if any(err.skipped for err in errors):
                logger.error(f"PR #{pr['number']} не прошел валидацию из-за пропущенных файлов. Пропуск обновления статуса, проверьте наличие файлов.")
                continue

            if errors:
                logger.info(f"PR #{pr['number']} не прошел валидацию.")
                pr_comment = self.make_pr_comment_from_errors(errors)
                print(pr_comment)
                if self.github_client.add_review_to_pr(pr['number'], pr_comment, "REQUEST_CHANGES"):
                    logger.info(f"Добавлено требование изменений к PR #{pr['number']}.")
                    self.save_pr_request_changes(pr['number'])
                continue

            logger.info(f"PR #{pr['number']} прошел валидацию. Забираем парсер в текущую ветку и закрываем issue.")
            if self.branch_manager.pull_extractor_changes(pr['head']['ref'], only_new=True) is False:
                logger.error(f"Не удалось забрать изменения из PR #{pr['number']}. .")
                continue

            new_files_added = True
            self.github_client.close_pr(pr['number'])
            self.github_client.close_pr_linked_issue(pr['number'], pr)
            # удаление ветки после мерджа pr и получение изменений в локальную ветку
            self.branch_manager.delete_branch(pr['head']['ref'])

        if not new_files_added:
            logger.info("Новые файлы не были добавлены, пропуск автокоммита.")
            return
        
        try:
            self.branch_manager.commit_specific_directory(config.EXTRACTOR_FOLDER, "Автокоммит после проверки парсеров", push=False)
        except Exception as e:
            logger.error(f"Не удалось закоммитить текущую ветку автоматически: {e}.")

if __name__ == "__main__":
    workflow = CopilotWorkflow()
    workflow.check_review_requested_prs()
