#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
CONFIG_PATH = BASE_DIR / "config.yaml"
STYLE_PATH = BASE_DIR / "style.yaml"
VENV_PYTHON = BASE_DIR / ".venv" / "bin" / "python"
PYTHON_BIN = str(VENV_PYTHON) if VENV_PYTHON.exists() else (sys.executable or "/usr/bin/python3")


def run_command(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part).strip()


def ensure_success(result: subprocess.CompletedProcess[str], action: str) -> str:
    text = combined_output(result)
    if result.returncode != 0:
        raise RuntimeError(f"{action} failed.\n{text}".strip())
    return text


def parse_json_stdout(result: subprocess.CompletedProcess[str], action: str) -> dict[str, Any]:
    if result.returncode != 0:
        raise RuntimeError(f"{action} failed.\n{combined_output(result)}".strip())
    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(f"{action} returned no stdout.")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{action} returned non-JSON stdout.\n{stdout}") from exc


def json_section(payload: dict[str, Any]) -> None:
    print("\n--- JSON ---")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def latest_markdown() -> Path | None:
    candidates = sorted(OUTPUT_DIR.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    non_smoke = [path for path in candidates if path.name != "smoke-test.md"]
    return non_smoke[0] if non_smoke else candidates[0]


def resolve_article(arg: str | None, fallback_to_smoke: bool = True) -> Path:
    if arg:
        candidate = Path(arg)
        if not candidate.is_absolute():
            candidate = (BASE_DIR / candidate).resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"Article not found: {candidate}")
        return candidate

    latest = latest_markdown()
    if latest:
        return latest

    smoke = OUTPUT_DIR / "smoke-test.md"
    if fallback_to_smoke and smoke.exists():
        return smoke

    raise FileNotFoundError("No markdown article found under output/.")


def extract_media_id(text: str) -> str | None:
    match = re.search(r"media_id:\s*([A-Za-z0-9_\-]+)", text)
    return match.group(1) if match else None


def extract_output_path(text: str) -> str | None:
    match = re.search(r"^Output:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def command_help() -> int:
    print("WeWrite 已接入 OpenClaw。")
    print("可用命令：help, status, hotspots, preview, publish, smoke")
    print("")
    print("推荐测试顺序：")
    print("1. python3 /config/.openclaw/workspace/wewrite/openclaw_skill.py hotspots")
    print("2. python3 /config/.openclaw/workspace/wewrite/openclaw_skill.py preview")
    print("3. python3 /config/.openclaw/workspace/wewrite/openclaw_skill.py publish")
    print("")
    print("推荐在 OpenClaw 里直接说：")
    print("- 用 wewrite 帮我做一篇今天 AI/金融/币圈/美股热点解读，并推到公众号草稿箱")
    print("- 先用 wewrite 抓热点并给我 10 个选题")
    payload = {
        "project": "wewrite",
        "skill_repo": str(BASE_DIR),
        "workspace_skill": "/config/.openclaw/workspace/skills/wewrite/SKILL.md",
        "available_commands": ["help", "status", "hotspots", "preview", "publish", "smoke"],
    }
    json_section(payload)
    return 0


def command_status() -> int:
    latest = latest_markdown()
    payload = {
        "project": "wewrite",
        "repo": str(BASE_DIR),
        "skill_installed": (BASE_DIR.parent / "skills" / "wewrite" / "SKILL.md").exists(),
        "config_present": CONFIG_PATH.exists(),
        "style_present": STYLE_PATH.exists(),
        "latest_article": str(latest) if latest else None,
        "latest_article_mtime": datetime.fromtimestamp(latest.stat().st_mtime).isoformat() if latest else None,
    }
    print("WeWrite 当前状态已检查。")
    if latest:
        print(f"最新文章：{latest.name}")
    else:
        print("output/ 下还没有可用文章。")
    json_section(payload)
    return 0


def command_hotspots(limit: int = 8) -> int:
    result = run_command([PYTHON_BIN, "scripts/fetch_hotspots.py", "--limit", str(limit)], timeout=300)
    payload = parse_json_stdout(result, "fetch_hotspots")
    print(f"热点抓取完成，共 {payload.get('count', 0)} 条，来源：{', '.join(payload.get('sources', [])) or '无'}")
    for index, item in enumerate(payload.get("items", [])[:5], start=1):
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or item.get("platform") or "unknown").strip()
        print(f"{index}. [{source}] {title}")
    json_section(payload)
    return 0


def command_preview(article_arg: str | None = None) -> int:
    article = resolve_article(article_arg)
    output_path = article.with_suffix(".html")
    result = run_command(
        [PYTHON_BIN, "toolkit/cli.py", "preview", str(article), "--no-open", "-o", str(output_path)],
        timeout=300,
    )
    text = ensure_success(result, "preview")
    print(f"预览生成完成：{article.name}")
    payload = {
        "article": str(article),
        "html_output": extract_output_path(text) or str(output_path),
        "raw_output": text,
    }
    json_section(payload)
    return 0


def command_publish(article_arg: str | None = None, title_arg: str | None = None) -> int:
    article = resolve_article(article_arg)
    args = [PYTHON_BIN, "toolkit/cli.py", "publish", str(article)]
    if title_arg:
        args.extend(["--title", title_arg])
    result = run_command(args, timeout=300)
    text = ensure_success(result, "publish")
    media_id = extract_media_id(text)
    print(f"草稿箱发布完成：{article.name}")
    if media_id:
        print(f"media_id: {media_id}")
    payload = {
        "article": str(article),
        "media_id": media_id,
        "raw_output": text,
    }
    json_section(payload)
    return 0


def command_smoke() -> int:
    hotspots_result = run_command([PYTHON_BIN, "scripts/fetch_hotspots.py", "--limit", "8"], timeout=300)
    hotspots_payload = parse_json_stdout(hotspots_result, "fetch_hotspots")

    smoke_article = OUTPUT_DIR / "smoke-test.md"
    article = resolve_article(str(smoke_article) if smoke_article.exists() else None)

    preview_result = run_command(
        [PYTHON_BIN, "toolkit/cli.py", "preview", str(article), "--no-open", "-o", str(article.with_suffix(".html"))],
        timeout=300,
    )
    preview_text = ensure_success(preview_result, "preview")

    smoke_title = f"WeWrite 联调 {datetime.now().date().isoformat()}"
    publish_result = run_command(
        [PYTHON_BIN, "toolkit/cli.py", "publish", str(article), "--title", smoke_title],
        timeout=300,
    )
    publish_text = ensure_success(publish_result, "publish")
    media_id = extract_media_id(publish_text)

    print("WeWrite smoke 流程已跑通。")
    print(f"热点条数：{hotspots_payload.get('count', 0)}")
    print(f"文章：{article.name}")
    if media_id:
        print(f"草稿 media_id: {media_id}")
    payload = {
        "hotspots": {
            "count": hotspots_payload.get("count", 0),
            "sources": hotspots_payload.get("sources", []),
            "sources_failed": hotspots_payload.get("sources_failed", []),
        },
        "article": str(article),
        "preview_output": extract_output_path(preview_text),
        "draft_media_id": media_id,
    }
    json_section(payload)
    return 0


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "help"
    try:
        if action == "help":
            return command_help()
        if action == "status":
            return command_status()
        if action == "hotspots":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 8
            return command_hotspots(limit)
        if action == "preview":
            article_arg = sys.argv[2] if len(sys.argv) > 2 else None
            return command_preview(article_arg)
        if action == "publish":
            article_arg = sys.argv[2] if len(sys.argv) > 2 else None
            title_arg = sys.argv[3] if len(sys.argv) > 3 else None
            return command_publish(article_arg, title_arg)
        if action == "smoke":
            return command_smoke()
        print(f"未知命令：{action}")
        print("可用命令：help, status, hotspots, preview, publish, smoke")
        return 1
    except Exception as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
