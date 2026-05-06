"""Authenticated HTTP calls to Cloud Run services."""

import google.auth.transport.requests
import google.oauth2.id_token
import requests


def get_id_token(audience: str) -> str:
    """Fetch an identity token for the given audience (Cloud Run URL base)."""
    auth_req = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(auth_req, audience)


def post(url: str, json: dict, timeout: int) -> requests.Response:
    """Authenticated POST to a Cloud Run service using an identity token."""
    audience = "/".join(url.split("/", 3)[:3])
    token = get_id_token(audience)
    resp = requests.post(
        url,
        json=json,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp
