import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

FABRIC_API_BASE = os.environ.get("FABRIC_API_BASE", "https://api.fabric.microsoft.com/v1").rstrip("/")
FABRIC_RESOURCE = "https://api.fabric.microsoft.com"


class FabricError(RuntimeError):
    pass


class FabricConfigError(FabricError):
    pass


class FabricApiError(FabricError):
    pass


@dataclass(frozen=True)
class FabricItem:
    id: str
    display_name: str
    type: str
    raw: dict[str, Any]


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise FabricConfigError(f"Missing required environment variable: {name}")
    return value


def read_bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_azure_access_token(resource: str) -> str:
    az_command = shutil.which("az") or shutil.which("az.cmd")
    if not az_command:
        default_az_cmd = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
        if os.path.exists(default_az_cmd):
            az_command = default_az_cmd
    if not az_command:
        raise FabricConfigError("Azure CLI not found in PATH. Install Azure CLI and run az login.")

    command = [
        az_command,
        "account",
        "get-access-token",
        "--resource",
        resource,
        "--query",
        "accessToken",
        "-o",
        "tsv",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise FabricConfigError(
            f"Failed to acquire Azure token for {resource}: {result.stderr.strip() or result.stdout.strip()}"
        )
    token = result.stdout.strip()
    if not token:
        raise FabricConfigError(f"Azure token for {resource} was empty")
    return token


def _response_body(response: Any) -> Any:
    raw = response.read()
    if not raw:
        return None
    text = raw.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


class FabricClient:
    def __init__(self, api_base: str = FABRIC_API_BASE):
        self.api_base = api_base.rstrip("/")
        self.token = get_azure_access_token(FABRIC_RESOURCE)

    def _request(self, method: str, path_or_url: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, str], Any]:
        url = path_or_url if path_or_url.startswith("http") else urljoin(self.api_base + "/", path_or_url.lstrip("/"))
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=120) as response:
                return response.status, dict(response.headers.items()), _response_body(response)
        except HTTPError as exc:
            raise FabricApiError(
                f"{method.upper()} {url} failed with HTTP {exc.code}: {_response_body(exc)}"
            ) from exc

    def poll_operation(self, location: str, timeout_seconds: int = 900) -> Any:
        deadline = time.time() + timeout_seconds
        while True:
            if time.time() >= deadline:
                raise FabricApiError(f"Timed out waiting for operation at {location}")
            status, headers, body = self._request("GET", location)
            if isinstance(body, dict) and body.get("status") in {"Succeeded", "Failed", "Canceled"}:
                if body["status"] != "Succeeded":
                    raise FabricApiError(f"Operation failed at {location}: {body}")
                return body
            if isinstance(body, dict) and body:
                return body
            delay = int(headers.get("Retry-After", "5"))
            time.sleep(max(1, delay))

    def list_workspaces(self) -> list[dict[str, Any]]:
        _, _, body = self._request("GET", "/workspaces")
        if isinstance(body, dict):
            return body.get("value", [])
        return body or []

    def resolve_workspace(self, workspace_name: str) -> dict[str, Any]:
        matches = [workspace for workspace in self.list_workspaces() if workspace.get("displayName") == workspace_name]
        if not matches:
            raise FabricConfigError(f"Workspace not found: {workspace_name}")
        if len(matches) > 1:
            raise FabricConfigError(f"More than one workspace matched name: {workspace_name}")
        return matches[0]

    def list_items(self, workspace_id: str, collection: str) -> list[dict[str, Any]]:
        _, _, body = self._request("GET", f"/workspaces/{workspace_id}/{collection}")
        if isinstance(body, dict):
            return body.get("value", [])
        return body or []

    def find_item(self, workspace_id: str, collection: str, display_name: str) -> dict[str, Any] | None:
        matches = [item for item in self.list_items(workspace_id, collection) if item.get("displayName") == display_name]
        if not matches:
            return None
        if len(matches) > 1:
            raise FabricApiError(f"More than one {collection} matched name: {display_name}")
        return matches[0]

    def _create_item(self, workspace_id: str, collection: str, payload: dict[str, Any]) -> dict[str, Any]:
        status, headers, body = self._request("POST", f"/workspaces/{workspace_id}/{collection}", payload)
        if status in {200, 201} and isinstance(body, dict) and body.get("id"):
            return body
        location = headers.get("Location") or headers.get("location")
        if location:
            self.poll_operation(location)
        deadline = time.time() + 90
        while time.time() < deadline:
            created = self.find_item(workspace_id, collection, payload["displayName"])
            if created:
                return created
            time.sleep(5)
        raise FabricApiError(f"Could not find created item {payload['displayName']} in {collection}")

    def ensure_item(self, workspace_id: str, collection: str, display_name: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        existing = self.find_item(workspace_id, collection, display_name)
        if existing:
            return existing
        payload = {"displayName": display_name}
        if extra:
            payload.update(extra)
        return self._create_item(workspace_id, collection, payload)

    def get_item(self, workspace_id: str, collection: str, item_id: str) -> dict[str, Any]:
        _, _, body = self._request("GET", f"/workspaces/{workspace_id}/{collection}/{item_id}")
        if not isinstance(body, dict):
            raise FabricApiError(f"Unexpected response when reading {collection}/{item_id}: {body}")
        return body

    def get_eventhouse_query_service_uri(self, workspace_id: str, eventhouse_id: str) -> str:
        eventhouse = self.get_item(workspace_id, "eventhouses", eventhouse_id)
        properties = eventhouse.get("properties", {})
        query_service_uri = properties.get("queryServiceUri")
        if not query_service_uri:
            raise FabricApiError(f"Eventhouse {eventhouse_id} does not expose queryServiceUri")
        return query_service_uri.rstrip("/")

    def update_eventstream_definition(
        self,
        workspace_id: str,
        eventstream_id: str,
        definition_parts: list[dict[str, Any]],
        update_metadata: bool = False,
    ) -> None:
        query = "true" if update_metadata else "false"
        path = f"/workspaces/{workspace_id}/eventstreams/{eventstream_id}/updateDefinition?updateMetadata={query}"
        status, headers, body = self._request(
            "POST",
            path,
            {"definition": {"parts": definition_parts}},
        )
        if status in {200, 201}:
            return
        location = headers.get("Location") or headers.get("location")
        if location:
            self.poll_operation(location)
            return
        raise FabricApiError(f"Unexpected response updating eventstream definition: status={status}, body={body}")

    def delete_item(self, workspace_id: str, collection: str, item_id: str) -> None:
        status, headers, body = self._request("DELETE", f"/workspaces/{workspace_id}/{collection}/{item_id}")
        if status in {200, 202, 204}:
            location = headers.get("Location") or headers.get("location")
            if location:
                self.poll_operation(location)
            return
        raise FabricApiError(f"Unexpected response deleting {collection}/{item_id}: status={status}, body={body}")

    def create_item_with_definition(
        self,
        workspace_id: str,
        display_name: str,
        item_type: str,
        definition_parts: list[dict[str, Any]],
        description: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "displayName": display_name,
            "type": item_type,
            "definition": {"parts": definition_parts},
        }
        if description:
            payload["description"] = description

        status, headers, body = self._request("POST", f"/workspaces/{workspace_id}/items", payload)
        if status in {200, 201} and isinstance(body, dict) and body.get("id"):
            return body

        location = headers.get("Location") or headers.get("location")
        if location:
            self.poll_operation(location)

        # item list collections are lower camel with plural; for Eventstream this is "eventstreams"
        collection = f"{item_type[0].lower()}{item_type[1:]}s"
        deadline = time.time() + 120
        while time.time() < deadline:
            created = self.find_item(workspace_id, collection, display_name)
            if created:
                return created
            time.sleep(5)
        raise FabricApiError(f"Could not find created item {display_name} in {collection}")

    def create_or_get_eventhouse_database(self, workspace_id: str, eventhouse_id: str, database_name: str) -> dict[str, Any]:
        existing = self.find_item(workspace_id, "kqlDatabases", database_name)
        if existing:
            return existing
        payload = {
            "displayName": database_name,
            "creationPayload": {
                "databaseType": "ReadWrite",
                "parentEventhouseItemId": eventhouse_id,
            },
        }
        return self._create_item(workspace_id, "kqlDatabases", payload)


def run_kusto_management(query_service_uri: str, database_name: str, command: str) -> Any:
    token = get_azure_access_token("https://kusto.kusto.windows.net")
    url = f"{query_service_uri.rstrip('/')}/v1/rest/mgmt"
    payload = {"db": database_name, "csl": command}
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            return _response_body(response)
    except HTTPError as exc:
        raise FabricApiError(f"Kusto command failed: {command}: {_response_body(exc)}") from exc

