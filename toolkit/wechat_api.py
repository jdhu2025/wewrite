import time
import mimetypes
import requests
from pathlib import Path
from dataclasses import dataclass
from requests import RequestException

# Token cache
_token_cache: dict = {}


@dataclass
class TokenResult:
    access_token: str
    expires_at: float  # unix timestamp


def _format_network_error(action: str, exc: RequestException) -> str:
    message = str(exc)
    lowered = message.lower()
    if "unexpected_eof_while_reading" in lowered or "eof occurred in violation of protocol" in lowered:
        return (
            f"WeChat {action} network error: TLS handshake to api.weixin.qq.com failed before the API returned data. "
            "This machine or container currently cannot establish HTTPS to the WeChat API. "
            "If you use a proxy, make sure it allows CONNECT to api.weixin.qq.com:443; otherwise verify direct outbound access."
        )
    if "proxyerror" in lowered or "tunnel connection failed" in lowered:
        return (
            f"WeChat {action} network error: the configured HTTP(S) proxy blocked access to api.weixin.qq.com. "
            "Check HTTP_PROXY/HTTPS_PROXY or bypass the proxy for this domain."
        )
    return f"WeChat {action} network error: {message}"


def get_access_token(appid: str, secret: str, force_refresh: bool = False) -> str:
    """
    Get access_token with caching.
    Cache key: appid
    API: GET https://api.weixin.qq.com/cgi-bin/token
    Cache until expires_in - 300 seconds (5 min buffer).
    Raise ValueError on API error.
    """
    now = time.time()

    if not force_refresh and appid in _token_cache:
        cached: TokenResult = _token_cache[appid]
        if now < cached.expires_at:
            return cached.access_token

    try:
        resp = requests.get(
            "https://api.weixin.qq.com/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": appid,
                "secret": secret,
            },
            timeout=20,
        )
    except RequestException as exc:
        raise ValueError(_format_network_error("access_token", exc)) from exc
    data = resp.json()

    if "access_token" not in data:
        errcode = data.get("errcode", "unknown")
        errmsg = data.get("errmsg", "unknown error")
        if errcode == 40164:
            raise ValueError(
                "WeChat API error: errcode=40164, current outbound IP is not in the Official Account IP whitelist. "
                "Add this environment's egress IP in mp.weixin.qq.com -> Settings & Development -> Basic Configuration -> IP whitelist."
            )
        raise ValueError(f"WeChat API error: errcode={errcode}, errmsg={errmsg}")

    access_token = data["access_token"]
    expires_in = data.get("expires_in", 7200)

    _token_cache[appid] = TokenResult(
        access_token=access_token,
        expires_at=now + expires_in - 300,
    )

    return access_token


def _guess_content_type(file_path: str) -> str:
    """Detect content type from file extension."""
    content_type, _ = mimetypes.guess_type(file_path)
    return content_type or "application/octet-stream"


def upload_image(access_token: str, image_path: str) -> str:
    """
    Upload image for use inside article content.
    API: POST https://api.weixin.qq.com/cgi-bin/media/uploadimg
    Returns the url string.
    Raise ValueError on error.
    """
    path = Path(image_path)
    content_type = _guess_content_type(image_path)

    with open(path, "rb") as f:
        try:
            resp = requests.post(
                "https://api.weixin.qq.com/cgi-bin/media/uploadimg",
                params={"access_token": access_token},
                files={"media": (path.name, f, content_type)},
                timeout=60,
            )
        except RequestException as exc:
            raise ValueError(_format_network_error("upload_image", exc)) from exc

    data = resp.json()

    if "url" not in data:
        errcode = data.get("errcode", "unknown")
        errmsg = data.get("errmsg", "unknown error")
        raise ValueError(f"WeChat upload_image error: errcode={errcode}, errmsg={errmsg}")

    return data["url"]


def upload_thumb(access_token: str, image_path: str) -> str:
    """
    Upload cover image as permanent material.
    API: POST https://api.weixin.qq.com/cgi-bin/material/add_material
    Returns media_id string.
    Raise ValueError on error.
    """
    path = Path(image_path)
    content_type = _guess_content_type(image_path)

    with open(path, "rb") as f:
        try:
            resp = requests.post(
                "https://api.weixin.qq.com/cgi-bin/material/add_material",
                params={"access_token": access_token, "type": "image"},
                files={"media": (path.name, f, content_type)},
                timeout=60,
            )
        except RequestException as exc:
            raise ValueError(_format_network_error("upload_thumb", exc)) from exc

    data = resp.json()

    if "media_id" not in data:
        errcode = data.get("errcode", "unknown")
        errmsg = data.get("errmsg", "unknown error")
        raise ValueError(f"WeChat upload_thumb error: errcode={errcode}, errmsg={errmsg}")

    return data["media_id"]
