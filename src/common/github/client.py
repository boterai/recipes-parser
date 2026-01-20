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
        labels: list[str] = None
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
            return response.json()
        else:
            logger.error(f"Failed to create issue '{title}': {response.status_code} - {response.text}")
            return None

    def create_issue_from_file(
        self,
        title: str,
        filepath: str,
        assignees: list[str] = None,
        labels: list[str] = None
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
            labels=labels
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
        
if __name__ == "__main__":
    gh_client = GitHubClient()
    issues = gh_client.list_repository_issues()
    if issues is not None:
        for issue in issues:
            print(f"Issue #{issue['number']}: {issue['title']}")