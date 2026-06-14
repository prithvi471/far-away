from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .document_parsers import ParsedDocument, parse_document


class DocumentAdapterError(RuntimeError):
    pass


@dataclass
class AdapterFetch:
    parsed: ParsedDocument
    cleanup_path: Path | None = None


class DocumentAdapter:
    scheme = "file"

    def fetch(self, uri: str) -> AdapterFetch:
        raise NotImplementedError


class LocalFileAdapter(DocumentAdapter):
    scheme = "file"

    def fetch(self, uri: str) -> AdapterFetch:
        path = uri.removeprefix("file://")
        return AdapterFetch(parsed=parse_document(path))


class HttpTextAdapter(DocumentAdapter):
    scheme = "https"
    token_env: str | None = None

    def fetch(self, uri: str) -> AdapterFetch:
        headers = {}
        if self.token_env and os.environ.get(self.token_env):
            headers["Authorization"] = f"Bearer {os.environ[self.token_env]}"
        request = urllib.request.Request(uri, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
        suffix = _suffix_from_uri(uri)
        temp_path = _write_temp(body, suffix)
        return AdapterFetch(parsed=parse_document(temp_path), cleanup_path=temp_path)


class GoogleDriveAdapter(HttpTextAdapter):
    scheme = "google_drive"
    token_env = "GOOGLE_DRIVE_TOKEN"

    def fetch(self, uri: str) -> AdapterFetch:
        file_id = uri.split("://", 1)[1]
        url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(file_id)}?alt=media"
        return super().fetch(url)


class SharePointAdapter(HttpTextAdapter):
    scheme = "sharepoint"
    token_env = "MICROSOFT_GRAPH_TOKEN"

    def fetch(self, uri: str) -> AdapterFetch:
        item_path = uri.split("://", 1)[1]
        url = f"https://graph.microsoft.com/v1.0/{item_path}/content"
        return super().fetch(url)


class SlackAdapter(HttpTextAdapter):
    scheme = "slack"
    token_env = "SLACK_BOT_TOKEN"

    def fetch(self, uri: str) -> AdapterFetch:
        parsed = urllib.parse.urlparse(uri)
        query = urllib.parse.parse_qs(parsed.query)
        channel = parsed.netloc
        ts = query.get("ts", [""])[0]
        if not channel or not ts:
            raise DocumentAdapterError("Slack URI must look like slack://CHANNEL_ID?ts=MESSAGE_TS")
        url = f"https://slack.com/api/conversations.replies?channel={urllib.parse.quote(channel)}&ts={urllib.parse.quote(ts)}"
        headers = {"Authorization": f"Bearer {self._required_token()}"}
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = "\n".join(item.get("text", "") for item in payload.get("messages", []))
        temp_path = _write_temp(text.encode("utf-8"), ".txt")
        return AdapterFetch(parsed=parse_document(temp_path), cleanup_path=temp_path)

    def _required_token(self) -> str:
        token = os.environ.get(self.token_env or "")
        if not token:
            raise DocumentAdapterError(f"Missing required token env var: {self.token_env}")
        return token


class GitHubAdapter(HttpTextAdapter):
    scheme = "github"
    token_env = "GITHUB_TOKEN"

    def fetch(self, uri: str) -> AdapterFetch:
        parsed = urllib.parse.urlparse(uri)
        path_parts = parsed.path.strip("/").split("/", 1)
        if not parsed.netloc or len(path_parts) != 2:
            raise DocumentAdapterError("GitHub URI must look like github://owner/repo/path/to/file.md?ref=main")
        owner = parsed.netloc
        repo, file_path = path_parts
        query = urllib.parse.parse_qs(parsed.query)
        ref = query.get("ref", ["main"])[0]
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{urllib.parse.quote(ref)}/{file_path}"
        return super().fetch(url)


class JiraAdapter(HttpTextAdapter):
    scheme = "jira"
    token_env = "JIRA_API_TOKEN"

    def fetch(self, uri: str) -> AdapterFetch:
        parsed = urllib.parse.urlparse(uri)
        query = urllib.parse.parse_qs(parsed.query)
        site = query.get("site", [""])[0]
        email = query.get("email", [""])[0]
        issue_key = parsed.netloc or parsed.path.strip("/")
        token = os.environ.get(self.token_env or "")
        if not site or not email or not issue_key or not token:
            raise DocumentAdapterError("Jira URI must include issue, site, email, and JIRA_API_TOKEN.")
        auth = urllib.request.HTTPBasicAuthHandler()
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, site, email, token)
        opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(password_mgr))
        url = f"{site.rstrip('/')}/rest/api/3/issue/{urllib.parse.quote(issue_key)}"
        with opener.open(url, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        fields = payload.get("fields", {})
        text = f"{fields.get('summary', '')}\n\n{json.dumps(fields.get('description', {}), indent=2)}"
        temp_path = _write_temp(text.encode("utf-8"), ".txt")
        return AdapterFetch(parsed=parse_document(temp_path), cleanup_path=temp_path)


ADAPTERS: dict[str, DocumentAdapter] = {
    "file": LocalFileAdapter(),
    "": LocalFileAdapter(),
    "http": HttpTextAdapter(),
    "https": HttpTextAdapter(),
    "google_drive": GoogleDriveAdapter(),
    "sharepoint": SharePointAdapter(),
    "slack": SlackAdapter(),
    "github": GitHubAdapter(),
    "jira": JiraAdapter(),
}


def fetch_document(uri: str) -> AdapterFetch:
    scheme = urllib.parse.urlparse(uri).scheme
    adapter = ADAPTERS.get(scheme)
    if not adapter:
        raise DocumentAdapterError(f"Unsupported document adapter scheme: {scheme}")
    return adapter.fetch(uri)


def _suffix_from_uri(uri: str) -> str:
    suffix = Path(urllib.parse.urlparse(uri).path).suffix
    return suffix or ".txt"


def _write_temp(body: bytes, suffix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(body)
        return Path(handle.name)
    finally:
        handle.close()
