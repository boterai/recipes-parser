import os
import logging
import requests
from typing import Optional, Any
from dotenv import load_dotenv
# Загрузка переменных окружения
load_dotenv()

logger = logging.getLogger(__name__)

# OpenAI API настройки
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_OWNER = os.getenv('GITHUB_REPO_OWNER')
GITHUB_REPO = os.getenv('GITHUB_REPO_NAME')

class GitHubClient:
    def __init__(self, owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO, token: str = GITHUB_TOKEN):
        self.owner = owner
        self.repo = repo
        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28"
        }

    def create_issue_from_dict(
        self,
        title: str,
        body: str,
        assignees: list[str] = None,
        labels: list[str] = None,
        branch: Optional[str] = None
    ) -> Optional[dict]:
        """
        Создает issue из словаря
        
        Args:
            title: заголовок
            body: тело issue (Markdown)
            assignees: кому назначить
            labels: метки
        
        Returns:
            Данные созданного issue
        """
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/issues"
        payload: dict[str, Any] = {
            "title": title,
            "body": body
        }
        if assignees:
            payload["assignees"] = assignees
        if labels:
            payload["labels"] = labels
        
        response = requests.post(url, headers=self.headers, json=payload)
        
        if response.status_code == 201:
            data = response.json()
            if branch:
                logger.info(f"Issue '{title}' создана. Установка development branch: {branch}")
                self.set_issue_development_branch(issue_number=data['number'], branch_name=branch)
            return data
        else:
            logger.error(f"Failed to create issue '{title}': {response.status_code} - {response.text}")
            return None

    def create_issue_from_file(
        self,
        title: str,
        filepath: str,
        assignees: list[str] = None,
        labels: list[str] = None,
        branch: Optional[str] = None
    ) -> Optional[dict]:
        """
        Создает issue из файла с описанием
        
        Args:
            title: заголовок
            body_file: путь к файлу с телом issue (Markdown)
            assignees: кому назначить
            labels: метки
        
        Returns:
            Данные созданного issue
        """        
        if not os.path.exists(filepath):
            print(f"❌ Body file not found: {filepath}")
            return None
        
        with open(filepath, 'r', encoding='utf-8') as f:
            body = f.read()
        
        return self.create_issue_from_dict(
            title=title,
            body=body,
            assignees=assignees,
            labels=labels,
            branch=branch

        )
    
    def list_repository_issues(self, state: str = "open") -> Optional[list[dict]]:
        """
        Получает список issues репозитория
        
        Args:
            state: состояние issues (open, closed, all)
        
        Returns:
            Список issues
        """
        # TODO добавить поддержку на больше чем 100 issues
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/issues"
        params = {
            "state": state,
            "per_page": 100
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to fetch issues: {response.status_code} - {response.text}")
            return None
        
    def list_branches(self) -> Optional[list[dict]]:
        """
        Получает список веток репозитория
        
        Returns:
            Список веток
        """
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/branches"

        params = {
            "per_page": 100
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to fetch branches: {response.status_code} - {response.text}")
            return None
        
    def list_pr(self) -> Optional[list[dict]]:
        """
        Получает список pull requests репозитория
        
        Returns:
            Список pull requests
        """
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/pulls"

        params = {
            "state": "open",
            "per_page": 100
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to fetch pull requests: {response.status_code} - {response.text}")
            return None
        
    def mark_pr_ready(self, pr_number: int) -> bool:
        """
        Помечает draft PR как ready for review
        
        Args:
            pr_number: номер pull request
        
        Returns:
            True если успешно
        """
        # Получаем информацию о PR для node_id (нужен для GraphQL)
        pr_url = f"{self.base_url}/repos/{self.owner}/{self.repo}/pulls/{pr_number}"
        pr_response = requests.get(pr_url, headers=self.headers)
        
        if pr_response.status_code != 200:
            logger.error(f"Failed to get PR info: {pr_response.status_code} - {pr_response.text}")
            return False
        
        pr_data = pr_response.json()
        
        # Проверяем, является ли PR draft
        if not pr_data.get('draft', False):
            logger.info(f"PR #{pr_number} уже не является draft")
            return True
        
        node_id = pr_data.get('node_id')
        
        # GitHub API требует GraphQL для изменения draft статуса
        graphql_url = "https://api.github.com/graphql"
        graphql_headers = self.headers.copy()
        
        mutation = """
        mutation MarkPullRequestReadyForReview($pullRequestId: ID!) {
          markPullRequestReadyForReview(input: {pullRequestId: $pullRequestId}) {
            pullRequest {
              id
              isDraft
            }
          }
        }
        """
        
        payload = {
            "query": mutation,
            "variables": {
                "pullRequestId": node_id
            }
        }
        
        response = requests.post(graphql_url, headers=graphql_headers, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            if 'errors' in result:
                logger.error(f"GraphQL errors: {result['errors']}")
                return False
            logger.info(f"PR #{pr_number} помечен как ready for review")
            return True
        else:
            logger.error(f"Failed to mark PR ready: {response.status_code} - {response.text}")
            return False
    
    def merge_pr(self, pr_number: int, auto_mark_ready: bool = True) -> bool:
        """
        Мерджит pull request
        
        Args:
            pr_number: номер pull request
            auto_mark_ready: автоматически помечать draft PR как ready перед мерджем
        
        Returns:
            True если успешно
        """
        # Если включен auto_mark_ready, пытаемся пометить PR как ready
        if auto_mark_ready:
            if not self.mark_pr_ready(pr_number):
                logger.warning(f"Не удалось пометить PR #{pr_number} как ready, пробуем мерджить...")
        
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/pulls/{pr_number}/merge"
        
        response = requests.put(url, headers=self.headers)
        
        if response.status_code == 200:
            logger.info(f"PR #{pr_number} успешно замерджен")
            return True
        else:
            logger.error(f"Failed to merge PR #{pr_number}: {response.status_code} - {response.text}")
            return False
        
    def add_review_to_pr(self, pr_number: int, body: str, event: str = "COMMENT") -> bool:
        """
        Добавляет ревью к pull request
        
        Args:
            pr_number: номер pull request
            body: текст ревью
            event: тип ревью (COMMENT, APPROVE, REQUEST_CHANGES)
        
        Returns:
            True если успешно
        """
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/pulls/{pr_number}/reviews"
        
        payload = {
            "body": body,
            "event": event
        }
        
        response = requests.post(url, headers=self.headers, json=payload)
        
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Failed to add review to PR #{pr_number}: {response.status_code} - {response.text}")
            return False
        
    def mark_issue_as_completed(self, issue_number: int) -> bool:
        """
        Помечает issue как закрытую
        
        Args:
            issue_number: номер issue
        
        Returns:
            True если успешно
        """
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/issues/{issue_number}"
        
        payload = {
            "state": "closed"
        }
        
        response = requests.patch(url, headers=self.headers, json=payload)
        
        if response.status_code == 200:
            logger.info(f"Issue #{issue_number} успешно закрыта")
            return True
        else:
            logger.error(f"Failed to close issue #{issue_number}: {response.status_code} - {response.text}")
            return False
        
    def mark_issue_as_completed_by_title(self, issue_title: str) -> bool:
        """
        Помечает issue как закрытую по заголовку
        
        Args:
            issue_title: заголовок issue
        
        Returns:
            True если успешно
        """
        issues = self.list_repository_issues(state="open")
        if not issues:
            logger.error("Не удалось получить список открытых issues")
            return False
        
        for issue in issues:
            if issue.get('title') == issue_title:
                return self.mark_issue_as_completed(issue.get('number'))
        
        logger.warning(f"Issue с заголовком '{issue_title}' не найдена")
        return False
    
    def assign_issue_to_copilot(self, issue_number: int) -> bool:
        """
        Назначает issue пользователю Copilot
        
        Args:
            issue_number: номер issue
        
        Returns:
            True если успешно
        """
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/issues/{issue_number}/assignees"
        
        payload = {
            "assignees": ["Copilot"]
        }
        
        response = requests.post(url, headers=self.headers, json=payload)
        
        if response.status_code == 201:
            logger.info(f"Issue #{issue_number} успешно назначена Copilot")
            return True
        else:
            logger.error(f"Failed to assign issue #{issue_number} to Copilot: {response.status_code} - {response.text}")
            return False
        
    def set_issue_development_branch(self, issue_number: int, branch_name: str) -> bool:
        """
        Устанавливает development branch для issue через GitHub Projects API.
        
        Args:
            issue_number: номер issue
            branch_name: имя ветки (например, 'main' или 'develop')
        
        Returns:
            True если успешно
        """
        graphql_url = "https://api.github.com/graphql"
        
        # 1. Получаем node_id issue
        issue = self.get_issue(issue_number)
        if not issue:
            logger.error(f"Cannot find issue #{issue_number} to set development branch")
            return False
        
        issue_node_id = issue.get('node_id')
        
        # 2. Создаём development branch через GraphQL
        mutation = """
        mutation CreateLinkedBranch($issueId: ID!, $name: String!, $repositoryId: ID!) {
          createLinkedBranch(input: {
            issueId: $issueId
            name: $name
            repositoryId: $repositoryId
          }) {
            linkedBranch {
              ref {
                name
              }
            }
          }
        }
        """
        
        # Получаем repository node_id
        repo_url = f"{self.base_url}/repos/{self.owner}/{self.repo}"
        repo_resp = requests.get(repo_url, headers=self.headers)
        if repo_resp.status_code != 200:
            logger.error(f"Failed to get repo info: {repo_resp.status_code}")
            return False
        
        repo_node_id = repo_resp.json().get('node_id')
        
        payload = {
            "query": mutation,
            "variables": {
                "issueId": issue_node_id,
                "name": branch_name,
                "repositoryId": repo_node_id
            }
        }
        
        response = requests.post(graphql_url, headers=self.headers, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            if 'errors' in result:
                logger.error(f"GraphQL errors: {result['errors']}")
                return False
            logger.info(f"Issue #{issue_number} linked to branch '{branch_name}'")
            return True
        else:
            logger.error(f"Failed to link branch: {response.status_code} - {response.text}")
            return False
        
    def get_issue(self, issue_number: int) -> Optional[dict]:
        """
        Получает информацию об issue по номеру
        
        Args:
            issue_number: номер issue
        
        Returns:
            Данные issue или None при ошибке
        """
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/issues/{issue_number}"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to fetch issue #{issue_number}: {response.status_code} - {response.text}")
            return None
        
if __name__ == "__main__":
    gh_client = GitHubClient()
    pr = gh_client.get_issue(178)
    print(pr)