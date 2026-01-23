from pathlib import Path
import os
import logging

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.stages.workflow.generate_prompt import PromptGenerator
from src.common.github.client import GitHubClient
from src.stages.workflow.branch_manager import BranchManager

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

    def make_pr_comment_from_errors(self, errors: list[dict]) -> str:
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
            pr_comment += f"### Модуль: `{error['module']}`\n"
            pr_comment += f"- Всего файлов: {error['total_files']}\n"
            pr_comment += f"- Ошибок: {error['failed']}\n\n"
            
            for detail in error.get('details', []):
                pr_comment += f"#### 📄 Файл: `{detail.get('file', 'N/A')}`\n"
                pr_comment += f"- Статус: **{detail.get('status', 'unknown')}**\n"
                
                gpt_val = detail.get('gpt_validation')
                if gpt_val:
                    is_valid = gpt_val.get('is_valid', False)
                    is_recipe = gpt_val.get('is_recipe', True)
                    
                    pr_comment += f"- Валидация: {'✅ Корректно' if is_valid else '❌ Некорректно'}\n"
                    pr_comment += f"- Это рецепт: {'Да' if is_recipe else 'Нет'}\n"
                    
                    if not is_valid:
                        feedback = gpt_val.get('feedback', 'Нет описания')
                        pr_comment += f"- **Отзыв**: {feedback}\n\n"
                        
                        missing_fields = gpt_val.get('missing_fields', [])
                        if missing_fields:
                            pr_comment += f"- **Отсутствующие поля**: {', '.join(missing_fields)}\n"
                        
                        incorrect_fields = gpt_val.get('incorrect_fields', [])
                        if incorrect_fields:
                            pr_comment += f"- **Некорректные поля**: {', '.join(incorrect_fields)}\n"
                        
                        fix_recs = gpt_val.get('fix_recommendations', [])
                        if fix_recs:
                            pr_comment += "\n**Рекомендации по исправлению:**\n\n"
                            for idx, rec in enumerate(fix_recs, 1):
                                field = rec.get('field', 'N/A')
                                issue = rec.get('issue', 'N/A')
                                fix_suggestion = rec.get('fix_suggestion', 'N/A')
                                
                                pr_comment += f"{idx}. **Поле**: `{field}`\n"
                                pr_comment += f"   - Проблема: {issue}\n"
                                
                                # Разные поля в зависимости от типа валидации
                                if 'expected_value' in rec:
                                    # Валидация с reference JSON
                                    pr_comment += f"   - Ожидаемое значение: `{rec.get('expected_value', 'N/A')}`\n"
                                    pr_comment += f"   - Фактическое значение: `{rec.get('actual_value', 'N/A')}`\n"
                                elif 'correct_value_from_text' in rec:
                                    # Валидация с HTML текстом
                                    pr_comment += f"   - Правильное значение из текста: `{rec.get('correct_value_from_text', 'N/A')}`\n"
                                    pr_comment += f"   - Извлеченное значение: `{rec.get('actual_extracted_value', 'N/A')}`\n"
                                    if 'text_context' in rec:
                                        pr_comment += f"   - Контекст в тексте: _{rec.get('text_context', 'N/A')}_\n"
                                    if 'pattern_hint' in rec:
                                        pr_comment += f"   - Паттерн: {rec.get('pattern_hint', 'N/A')}\n"
                                
                                pr_comment += f"   - **Как исправить**: {fix_suggestion}\n\n"
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
            errors = self.branch_manager.check_branch(pr['head']['ref'])
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
                logger.error(f"Не удалось обновить текущую ветку автоматически: {e}")
            self.clear_preprocessed_data()

if __name__ == "__main__":
    workflow = CopilotWorkflow()
    workflow.check_review_requested_prs()