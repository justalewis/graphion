"""OJS 3.4 REST-API client for galley submission.

Two-step upload flow that mirrors what OJS's own editor UI does:

  1. POST {base}/temporaryFiles with the file — returns a
     `temporaryFileId` that OJS holds in staging until it's bound to
     a submission file record.
  2. POST {base}/submissions/{sid}/publications/{pid}/galleys with
     the temporaryFileId + label + locale — OJS creates the galley on
     the current publication and attaches the staged file to it.

The publication id (`pid`) is not in the article's URL in OJS; the
editor UI resolves it from the submission's `currentPublicationId`,
which is what this client does too.

The token is a personal API key generated from the OJS user profile.
It is passed as `Authorization: Bearer <token>` on every request.
Both the API base URL and the token live in the journal row so they
travel with the journal across deployments; env vars override the DB
so a per-deployment key is easy.

The OJS REST surface still shifts between minor versions. Errors are
re-raised with the response body preserved so the UI can show what
OJS actually said, which is the fastest way to diagnose a version
mismatch.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def _requests():
    import requests
    return requests


def _config_from_journal(journal: Dict) -> Dict[str, Optional[str]]:
    """Assemble the effective OJS config for a journal row. Env vars win
    over stored fields so an operator can override without editing DB.
    """
    return {
        "url": os.environ.get("OJS_URL") or journal.get("ojs_url"),
        "token": os.environ.get("OJS_API_TOKEN") or journal.get("ojs_api_token"),
        "context_id": (
            os.environ.get("OJS_CONTEXT_ID")
            or (str(journal.get("ojs_context_id")) if journal.get("ojs_context_id") else None)
        ),
    }


def ojs_configured(journal: Dict) -> bool:
    cfg = _config_from_journal(journal)
    return bool(cfg["url"] and cfg["token"])


def _base_and_headers(journal: Dict) -> tuple[str, dict]:
    cfg = _config_from_journal(journal)
    if not cfg["url"] or not cfg["token"]:
        raise RuntimeError(
            "OJS is not configured for this journal. Set OJS_URL and "
            "OJS_API_TOKEN env vars, or fill the OJS fields in Journal "
            "Settings."
        )
    return cfg["url"].rstrip("/"), {"Authorization": f"Bearer {cfg['token']}"}


def _describe(response) -> str:
    """A compact one-line summary of an OJS response for error text."""
    body = response.text[:600] if response.text else ""
    return f"{response.status_code} {response.reason} — {body}".strip()


def upload_galley(
    journal: Dict,
    submission_id: int,
    galley_label: str,
    galley_locale: str,
    file_path: Path,
) -> Dict[str, Any]:
    """Upload one file as a galley on the submission's current publication.

    `galley_label`: shown to readers, e.g. "PDF", "HTML", "EPUB".
    `galley_locale`: BCP-47 code as OJS expects it — usually "en".
    `file_path`: any file OJS accepts; the label communicates the format.
    """
    requests = _requests()
    base, headers = _base_and_headers(journal)

    # 1. Stage the file in OJS's temporaryFiles store.
    with open(file_path, "rb") as fh:
        r = requests.post(
            f"{base}/temporaryFiles",
            headers=headers,
            files={"file": (file_path.name, fh)},
            timeout=180,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"OJS temporaryFiles upload failed: {_describe(r)}")
    staged = r.json() if r.text else {}
    temp_id = staged.get("id") or staged.get("temporaryFileId")
    if not temp_id:
        raise RuntimeError(f"OJS temporaryFiles returned no id: {staged!r}")

    # 2. Look up the submission's current publication id — galleys live
    #    on publications, not on the submission directly.
    r = requests.get(f"{base}/submissions/{submission_id}", headers=headers, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(
            f"OJS submission {submission_id} lookup failed: {_describe(r)}"
        )
    submission = r.json()
    publication_id = submission.get("currentPublicationId")
    if not publication_id:
        # Fall back to the last entry in the publications list, which is
        # what the editor UI does when currentPublicationId is unset on
        # a very new submission.
        pubs = submission.get("publications") or []
        if pubs:
            publication_id = pubs[-1].get("id")
    if not publication_id:
        raise RuntimeError(
            f"OJS submission {submission_id} has no publication to attach the galley to."
        )

    # 3. Create the galley + bind the staged file in one call.
    payload = {
        "label": galley_label,
        "locale": galley_locale,
        "temporaryFileId": temp_id,
    }
    r = requests.post(
        f"{base}/submissions/{submission_id}/publications/{publication_id}/galleys",
        headers=headers,
        json=payload,
        timeout=180,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"OJS galley create failed: {_describe(r)}")
    return r.json() if r.text else {}


def list_submissions(journal: Dict) -> List[Dict[str, Any]]:
    """List submissions on the configured journal for a picker dropdown.

    Returns [] on any error rather than raising, because the picker is a
    convenience: the upload form still accepts a submission id typed by
    hand when this returns nothing.
    """
    requests = _requests()
    try:
        base, headers = _base_and_headers(journal)
    except RuntimeError:
        return []
    try:
        r = requests.get(f"{base}/submissions", headers=headers, timeout=30)
    except Exception:
        return []
    if r.status_code >= 400:
        return []
    body = r.json() if r.text else {}
    items = body.get("items", []) if isinstance(body, dict) else body
    out: List[Dict[str, Any]] = []
    for s in items or []:
        title = ""
        pubs = s.get("publications") if isinstance(s, dict) else None
        if isinstance(pubs, list) and pubs:
            title_obj = pubs[0].get("fullTitle") or pubs[0].get("title") or {}
            if isinstance(title_obj, dict):
                title = next(iter(title_obj.values()), "") or ""
            else:
                title = str(title_obj)
        out.append({"id": s.get("id"), "title": title or f"Submission {s.get('id')}"})
    return out


__all__ = [
    "ojs_configured",
    "upload_galley",
    "list_submissions",
]
