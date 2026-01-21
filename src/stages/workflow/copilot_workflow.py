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
    
    def create_issues_for_parsers(self):
        """Создает GitHub issues с промптами для создания парсеров на основе preprocessed данных."""

        current_branch = self.branch_manager.get_current_branch()
        prompts = self.prompt_generator.generate_all_prompts()
        if not prompts:
            logger.info("Нет промптов для создания issues.")
            return
        
        current_issues = self.github_client.list_repository_issues(state="all")
        existing_titles = {issue['title'] for issue in current_issues} if current_issues else set()
        # создаем только новые issues
        new_modules = [i for i in prompts if ISSUE_PREFIX + i not in existing_titles] 

        if not new_modules:
            logger.info("Нет новых модулей для создания issues.")
            return

        logger.info(f"Создание {len(new_modules)} новых issues для парсеров...")

        for module_name in new_modules:
            title = ISSUE_PREFIX + module_name
            issue = self.github_client.create_issue_from_dict(
                title=title,
                body=prompts[module_name],
                branch=current_branch
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
                logger.info(f"Очищена директория: {preprocessed_dir}")
        else:
            logger.info(f"Директория не найдена или не является директорией: {preprocessed_dir}")

    def check_review_requested_prs(self):
        """Проверяет завершенные PR и обновляет статусы задач."""
        prs = self.github_client.list_pr()
        prs = [pr for pr in prs if len(pr.get('requested_reviewers')) > 0]
        logger.info(f"Найдено {len(prs)} PR с запрошенным ревью.")
        for pr in prs:
            logger.info(f"Проверка PR #{pr['number']}: {pr['title']}")
            errors = self.branch_manager.check_branch(pr['head']['ref'])
            print(errors)
            if not errors:
                logger.info(f"PR #{pr['number']} прошел валидацию. Закрытие ревью, мердж pull request.")
                if self.github_client.merge_pr(pr['number'], auto_mark_ready=True):
                    self.github_client.close_pr_linked_issue(pr['number'], pr)
                # удаление ветки после мерджа pr и получение изменений в локальную ветку
                self.branch_manager.delete_branch(pr['head']['ref'])
                self.branch_manager.update_current_branch()
                self.clear_preprocessed_data()
            else: 
                # оставить комментарий с ошибками и потребовать исправления
                pass


if __name__ == "__main__":
    workflow = CopilotWorkflow()
    workflow.check_review_requested_prs()