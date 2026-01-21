from pathlib import Path
import os
import logging

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.stages.workflow.generate_prompt import PromptGenerator
from src.common.github.client import GitHubClient
from src.stages.workflow.branch_manager import check_one_branch, get_current_branch

logger = logging.getLogger(__name__)

ISSUE_PREFIX = "Создать парсер "

class CopilotWorkflow:

    def __init__(self):
        self.prompt_generator = PromptGenerator()
        self.github_client = GitHubClient()
    
    def create_issues_for_parsers(self):
        """Создает GitHub issues с промптами для создания парсеров на основе preprocessed данных."""

        current_branch = get_current_branch()
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

    def check_review_requested_prs(self):
        """Проверяет завершенные PR и обновляет статусы задач."""
        prs = self.github_client.list_pr()
        prs = [pr for pr in prs if len(pr.get('requested_reviewers')) > 0]
        logger.info(f"Найдено {len(prs)} PR с запрошенным ревью.")
        for pr in prs:
            logger.info(f"Проверка PR #{pr['number']}: {pr['title']}")
            errors = check_one_branch(pr['head']['ref'])
            if not errors:
                logger.info(f"PR #{pr['number']} прошел валидацию. Закрытие ревью, мердж pull request.")
                if self.github_client.merge_pr(pr['number'], auto_mark_ready=True):
                    issue_id = pr.get("_links", {}).get("issue", {}).get('href', "").split('/')[-1]
                    self.github_client.mark_issue_as_completed(issue_number=int(issue_id))
            else:
                # оставить комментарий с ошибками и потребовать исправления
                pass


if __name__ == "__main__":
    workflow = CopilotWorkflow()
    workflow.create_issues_for_parsers()