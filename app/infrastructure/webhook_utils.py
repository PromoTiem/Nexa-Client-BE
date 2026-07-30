from typing import Any, Dict, Optional, Tuple


def extract_webhook_metadata(payload: Dict[str, Any]) -> Tuple[Optional[str], str, str]:
    action = payload.get("action")
    repo = ""
    repository = payload.get("repository")
    if isinstance(repository, dict):
        repo = repository.get("full_name", "")
    sender = ""
    s = payload.get("sender")
    if isinstance(s, dict):
        sender = s.get("login", "")
    return action, repo, sender
