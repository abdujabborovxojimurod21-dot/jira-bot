"""
Jira REST API bilan ishlash uchun klient
"""

from datetime import datetime, timedelta
from typing import Optional
import requests
from requests.auth import HTTPBasicAuth

from config import JIRA_BASE_URL


class JiraClient:
    def __init__(self, username: str, password: str):
        self.base_url = JIRA_BASE_URL.rstrip("/")
        self.auth = HTTPBasicAuth(username, password)
        self.username = username
        self.display_name = username
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _get(self, endpoint: str, params: dict = None):
        """GET so'rov yuborish."""
        url = f"{self.base_url}/rest/api/2/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json(), None
        except requests.exceptions.ConnectionError:
            return None, "Serverga ulanib bo'lmadi. Internet aloqasini tekshiring."
        except requests.exceptions.Timeout:
            return None, "Server javob bermadi (timeout)."
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status == 401:
                return None, "Login yoki parol noto'g'ri."
            elif status == 403:
                return None, "Ruxsat yo'q (403)."
            elif status == 404:
                return None, "Topilmadi (404)."
            else:
                return None, f"HTTP xatolik: {status}"
        except Exception as e:
            return None, str(e)

    def test_connection(self) -> tuple[bool, str]:
        """Ulanishni va login/parolni tekshirish."""
        data, error = self._get("myself")
        if error:
            return False, error
        self.display_name = data.get("displayName", self.username)
        return True, ""

    def get_my_issues(self, max_results: int = 20) -> tuple[list, Optional[str]]:
        """
        Foydalanuvchiga tayinlangan barcha ochiq topshiriqlar.
        """
        jql = f"assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
        data, error = self._get("search", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,assignee,reporter,duedate,description",
        })
        if error:
            return [], error
        return data.get("issues", []), None

    def search_issues(self, query: str, max_results: int = 10) -> tuple[list, Optional[str]]:
        """
        Matn bo'yicha topshiriqlarni qidirish.
        query - oddiy matn yoki JQL bo'lishi mumkin.
        """
        # JQL ekanligini tekshirish (= yoki AND/OR bor bo'lsa)
        is_jql = any(kw in query.upper() for kw in ["=", " AND ", " OR ", "ORDER BY", "PROJECT"])

        if is_jql:
            jql = query
        else:
            # Matn qidirish
            safe_query = query.replace('"', '\\"')
            jql = (
                f'text ~ "{safe_query}" '
                f'ORDER BY updated DESC'
            )

        data, error = self._get("search", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,assignee,reporter,duedate,description",
        })
        if error:
            return [], error
        return data.get("issues", []), None

    def get_issue(self, issue_key: str) -> tuple[Optional[dict], Optional[str]]:
        """Bitta issue to'liq ma'lumotini olish."""
        data, error = self._get(f"issue/{issue_key}", params={
            "fields": "summary,status,priority,assignee,reporter,duedate,description,comment,created,updated",
        })
        return data, error

    def get_upcoming_deadlines(self, days: int = 7) -> tuple[list, Optional[str]]:
        """
        Muddati yaqinlashgan yoki o'tib ketgan topshiriqlar.
        days - necha kun ichida muddati tugaydigan topshiriqlar.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

        jql = (
            f"assignee = currentUser() "
            f"AND duedate >= \"{today}\" "
            f"AND duedate <= \"{future}\" "
            f"AND statusCategory != Done "
            f"ORDER BY duedate ASC"
        )
        data, error = self._get("search", params={
            "jql": jql,
            "maxResults": 20,
            "fields": "summary,status,priority,assignee,duedate",
        })
        if error:
            return [], error

        # O'tib ketgan muddatlarni ham qo'shish
        overdue_jql = (
            f"assignee = currentUser() "
            f"AND duedate < \"{today}\" "
            f"AND statusCategory != Done "
            f"ORDER BY duedate ASC"
        )
        overdue_data, _ = self._get("search", params={
            "jql": overdue_jql,
            "maxResults": 10,
            "fields": "summary,status,priority,assignee,duedate",
        })

        issues = []
        if overdue_data:
            issues.extend(overdue_data.get("issues", []))
        if data:
            issues.extend(data.get("issues", []))

        return issues, None

    def get_notifications(self, max_results: int = 10) -> tuple[list, Optional[str]]:
        """
        So'nggi yangilangan topshiriqlar (xabarnomalar o'rniga).
        Jira Cloud'da /rest/api/2/mypreferences/notification mavjud emas,
        shu sababli so'nggi o'zgarishlarni qaytaramiz.
        """
        jql = (
            f"assignee = currentUser() "
            f"AND updated >= -1d "
            f"ORDER BY updated DESC"
        )
        data, error = self._get("search", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,assignee,updated",
        })
        if error:
            return [], error
        return data.get("issues", []), None
