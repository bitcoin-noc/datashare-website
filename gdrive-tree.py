#!/usr/bin/env python3
"""
gdrive_tree.py — Fetch a public Google Drive folder tree and generate a static HTML page.

Usage:
    python gdrive_tree.py --folder-id FOLDER_ID [--output drive.html] [--title "My Drive"]

Environment:
    GDRIVE_API_KEY   Google Drive API key (required for Shared Drives;
                     may work without it for fully public My Drive folders)

The target folder must be shared as "Anyone with the link can view".
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DRIVE_API = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def api_get(path, params, api_key):
    if api_key:
        params["key"] = api_key
    params["supportsAllDrives"] = "true"
    params["includeItemsFromAllDrives"] = "true"
    url = f"{DRIVE_API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()}")


def list_folder(folder_id, api_key):
    items, page_token = [], None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "nextPageToken,files(id,name,mimeType,size,owners,modifiedTime,webViewLink)",
            "pageSize": "1000",
            "orderBy": "folder,name",
        }
        if page_token:
            params["pageToken"] = page_token
        data = api_get("files", params, api_key)
        items.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------

def build_tree(folder_id, api_key, depth=0):
    nodes = []
    for f in list_folder(folder_id, api_key):
        is_folder = f.get("mimeType") == FOLDER_MIME
        print(f"  {'  ' * depth}{'[d]' if is_folder else '[f]'} {f['name']}", file=sys.stderr)
        node = {
            "name": f["name"],
            "url": f.get("webViewLink", ""),
            "size": int(f["size"]) if f.get("size") else None,
            "owner": (f.get("owners") or [{}])[0].get("displayName", ""),
            "modified": f.get("modifiedTime", "")[:16].replace("T", " "),
            "mimeType": f.get("mimeType", ""),
            "isFolder": is_folder,
            "children": build_tree(f["id"], api_key, depth + 1) if is_folder else [],
        }
        nodes.append(node)
    return nodes


def fmt_size(n):
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def folder_size(node):
    if not node["isFolder"]:
        return node["size"] or 0
    return sum(folder_size(c) for c in node["children"])


def count(nodes):
    files = folders = total = 0
    for n in nodes:
        if n["isFolder"]:
            folders += 1
            f, fo, b = count(n["children"])
            files += f; folders += fo; total += b
        else:
            files += 1
            total += n["size"] or 0
    return files, folders, total


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_nodes(nodes, depth=0):
    parts = []
    for n in nodes:
        size = fmt_size(folder_size(n) if n["isFolder"] else n["size"])
        meta = " · ".join(filter(None, [n["mimeType"], size, n["modified"], n["owner"]]))
        name = f'<a href="{esc(n["url"])}">{esc(n["name"])}</a>' if n["url"] else esc(n["name"])

        if n["isFolder"]:
            inner = render_nodes(n["children"], depth + 1)
            parts.append(
                f'<li><details{"" if depth > 0 else " open"}>'
                f"<summary>{name} <small>{meta}</small></summary>"
                f"<ul>{inner}</ul>"
                f"</details></li>"
            )
        else:
            parts.append(f"<li>{name} <small>{meta}</small></li>")
    return "".join(parts)


HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: sans-serif; font-size: 14px; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
h1 {{ font-size: 1.2rem; margin-bottom: .25rem; }}
p.meta {{ color: #666; font-size: .85rem; margin: 0 0 1rem; }}
input {{ width: 100%; box-sizing: border-box; padding: .4rem .6rem; font-size: .9rem; margin-bottom: 1rem; border: 1px solid #ccc; border-radius: 4px; }}
ul {{ list-style: none; padding-left: 1.2rem; margin: .2rem 0; }}
ul:first-child {{ padding-left: 0; }}
li {{ padding: .15rem 0; }}
summary {{ cursor: pointer; }}
a {{ color: inherit; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
small {{ color: #888; font-size: .8rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="meta">{files} files · {folders} folders · {size} · {date}</p>
<input type="search" id="q" placeholder="Filter…" oninput="filter(this.value)">
<ul id="tree">{tree}</ul>
<script>
function filter(q) {{
  q = q.toLowerCase();
  document.querySelectorAll('#tree li').forEach(li => {{
    const text = li.querySelector('a,summary,span')?.textContent.toLowerCase() ?? '';
    li.style.display = (!q || text.includes(q)) ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--folder-id", required=True)
    p.add_argument("--output", default="drive.html")
    p.add_argument("--title", default="Drive")
    p.add_argument("--api-key")
    args = p.parse_args()

    api_key = args.api_key or os.environ.get("GDRIVE_API_KEY")
    if not api_key:
        print("[warn] No API key — will fail for Shared Drives", file=sys.stderr)

    print(f"Fetching {args.folder_id} …", file=sys.stderr)
    tree = build_tree(args.folder_id, api_key)
    n_files, n_folders, total = count(tree)

    html = HTML.format(
        title=esc(args.title),
        files=f"{n_files:,}",
        folders=f"{n_folders:,}",
        size=fmt_size(total) or "0 B",
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        tree=render_nodes(tree),
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"Written → {args.output}  ({n_files} files, {n_folders} folders, {fmt_size(total)})", file=sys.stderr)


if __name__ == "__main__":
    main()
