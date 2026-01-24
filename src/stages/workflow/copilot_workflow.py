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

logger = logging.getLogger(__name__)

ISSUE_PREFIX = "Создать парсер "

class CopilotWorkflow:

    def __init__(self):
        self.prompt_generator = PromptGenerator()
        self.github_client = GitHubClient()
        self.branch_manager = BranchManager()

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
        prompts = self.prompt_generator.generate_all_prompts()
        if not prompts:
            logger.info("Нет промптов для создания issues.")
            return
        
        current_issues = self.github_client.list_repository_issues(state="all")
        existing_titles = {issue['title'] for issue in current_issues} if current_issues else set()
        # создаем только новые issues
        new_modules = [i for i in prompts if issue_prefix + i not in existing_titles] 

        if not new_modules:
            logger.info("Нет новых модулей для создания issues.")
            return

        logger.info(f"Создание {len(new_modules)} новых issues для парсеров...")

        for module_name in new_modules:
            title = issue_prefix + module_name
            issue = self.github_client.create_issue_from_dict(
                title=title,
                body=prompts[module_name]
            )
            if issue:
                logger.info(f"Создан issue: {issue['html_url']}")
            else:
                logger.error(f"Не удалось создать issue для модуля: {module_name}")

    def clear_preprocessed_data(self):
        """Очищает директорию с preprocessed данными."""

        present_moules = [i.removesuffix('.py') for i in os.listdir("extractor") if not i.startswith("__") and i.endswith(".py")]
        preprocessed_dir = self.prompt_generator.preprocessed_dir
        if preprocessed_dir.exists() and preprocessed_dir.is_dir():
            for item in preprocessed_dir.iterdir():
                if item.is_dir() and item.name in present_moules:
                    for subitem in item.iterdir():
                        if subitem.is_file():
                            subitem.unlink()
                    item.rmdir()
                    logger.info(f"Очищена директория: {str(item)}")
        else:
            logger.info(f"Директория не найдена или не является директорией: {preprocessed_dir}")

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

    def check_review_requested_prs(self):
        """Проверяет завершенные PR и обновляет статусы задач.
        Для каждого PR с запрошенным ревью выполняет валидацию парсера.
        Note: аккаунт назначающий copilot и reviewer должен быть одним и тем же, иначе не сработает.
        """
        prs = self.github_client.list_pr()
        prs = [pr for pr in prs if len(pr.get('requested_reviewers')) > 0]
        logger.info(f"Найдено {len(prs)} PR с запрошенным ревью.")
        for pr in prs:
            logger.info(f"Проверка PR #{pr['number']}: {pr['title']}")
            errors: list[ValidationReport] = self.branch_manager.check_branch(pr['head']['ref'], chck_all_with_gpt=False) # проверяем гпт только если нет каких-то нужных полей
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
                continue

            logger.info(f"PR #{pr['number']} прошел валидацию. Закрытие ревью, мердж pull request.")
            if self.github_client.merge_pr(pr['number'], auto_mark_ready=True):
                self.github_client.close_pr_linked_issue(pr['number'], pr)
            # удаление ветки после мерджа pr и получение изменений в локальную ветку
            self.branch_manager.delete_branch(pr['head']['ref'])
            try:
                self.branch_manager.update_current_branch()
            except Exception as e:
                logger.error(f"Не удалось обновить текущую ветку автоматически: {e}, пожалуйста, выполните git pull вручную.")
            self.clear_preprocessed_data()

if __name__ == "__main__":
    workflow = CopilotWorkflow()
    workflow.check_review_requested_prs()
