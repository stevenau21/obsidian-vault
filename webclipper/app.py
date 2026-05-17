from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx
import re
import os
import json

app = FastAPI(title="Obsidian WebClipper")

OBSIDIAN_API = os.getenv("OBSIDIAN_API", "http://obsidian:27123")
API_KEY = os.getenv("API_KEY", "")
HEADERS = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
VAULT_PATH = os.getenv("VAULT_PATH", "/vault/Desktop/xeveno")
PREFS_PATH = os.getenv("PREFS_PATH", "/vault/.webclipper")
YOUTUBE_PROXY = os.getenv("YOUTUBE_PROXY", "http://host.docker.internal:5000")

BUILTIN_TEMPLATES = [
    {"id": "goal", "name": "Goal", "fields": [
        {"key": "goal", "label": "Goal", "placeholder": "What do you want to achieve?", "type": "text"},
        {"key": "purpose", "label": "Purpose", "placeholder": "Why does this matter?", "type": "text"},
        {"key": "intent", "label": "User Intent", "placeholder": "What the user intends to do", "type": "text"},
        {"key": "outcome", "label": "Expected Outcome", "placeholder": "What success looks like", "type": "text"},
    ]},
    {"id": "freeform", "name": "Freeform", "fields": []},
]

class FolderCreate(BaseModel):
    path: str

class PrefsUpdate(BaseModel):
    favorites: list[str] | None = None
    lastFolder: str | None = None

class TagDelete(BaseModel):
    tag: str

def get_prefs():
    p = os.path.join(PREFS_PATH, "prefs.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {"favorites": [], "tagHistory": []}

def save_prefs(data):
    p = os.path.join(PREFS_PATH, "prefs.json")
    with open(p, "w") as f:
        json.dump(data, f, indent=2)

def parse_metadata(content):
    """Parse ## Metadata section from markdown content into a dict."""
    m = re.search(r"^## Metadata\s*\n(.*?)(?:\n---|\n#|\Z)", content, re.MULTILINE | re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    result = {}
    for line in block.split("\n"):
        fm = re.match(r"\*\*(.+?):\*\*\s*(.*)", line)
        if fm:
            result[fm.group(1).strip()] = fm.group(2).strip()
    return result

def slugify(title):
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "untitled"

async def api_put(path, content):
    async with httpx.AsyncClient() as c:
        r = await c.put(
            f"{OBSIDIAN_API}/vault/{path.lstrip('/')}",
            headers={**HEADERS, "Content-Type": "text/markdown"},
            content=content,
            timeout=10,
        )
        return r

async def api_get(path):
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{OBSIDIAN_API}/vault/{path.lstrip('/')}",
            headers=HEADERS,
            timeout=10,
        )
        return r

async def api_delete(path):
    async with httpx.AsyncClient() as c:
        r = await c.delete(
            f"{OBSIDIAN_API}/vault/{path.lstrip('/')}",
            headers=HEADERS,
            timeout=10,
        )
        return r

def scan_tags(folder_prefix=None):
    tags = {}
    if not os.path.isdir(VAULT_PATH):
        return tags
    for root, _, files in os.walk(VAULT_PATH):
        rel_root = os.path.relpath(root, VAULT_PATH).replace("\\", "/")
        if folder_prefix and folder_prefix != "/":
            prefix = folder_prefix.rstrip("/")
            if rel_root == "." or not rel_root.startswith(prefix):
                continue
        if "/.obsidian" in rel_root or "/.git" in rel_root:
            continue
        for f in files:
            if not f.endswith(".md"):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        for m in re.finditer(r"#([a-zA-Z0-9][a-zA-Z0-9_/-]*)", line):
                            t = m.group(1).lower()
                            tags[t] = tags.get(t, 0) + 1
            except: pass
    return [{"name": k, "count": v} for k, v in sorted(tags.items())]

def scan_folders(max_depth=6):
    folders = []
    if not os.path.isdir(VAULT_PATH):
        return folders
    for root, dirs, _ in os.walk(VAULT_PATH):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel = os.path.relpath(root, VAULT_PATH)
        if rel == ".":
            folders.append("/")
        else:
            depth = rel.replace("\\", "/").count("/") + 1
            if depth <= max_depth:
                folders.append("/" + rel.replace("\\", "/"))
        if rel != ".":
            depth = rel.replace("\\", "/").count("/") + 1
            if depth >= max_depth:
                dirs[:] = []
    return sorted(folders)

FORM_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Clipper</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
<style>
:root{--bg:#0f0f13;--card:#1a1a24;--input:#12121c;--text:#e8e8ed;--muted:#787890;--border:#2a2a3a;--accent:#7c6ff0;--accent-glow:#7c6ff066;--success:#34d399;--error:#f87171;--radius:16px;--radius-sm:10px;--safe-bottom:env(safe-area-inset-bottom,0px)}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Inter',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overscroll-behavior:none;-webkit-font-smoothing:antialiased}
.container{max-width:640px;width:100%;margin:0 auto;padding:8px 8px calc(var(--safe-bottom) + 8px)}
h1{text-align:center;font-size:1.3rem;font-weight:700;letter-spacing:-.02em;background:linear-gradient(135deg,#a78bfa,#7c6ff0);-webkit-background-clip:text;-webkit-text-fill-color:transparent;padding:16px 0 12px;opacity:0}
.card{background:var(--card);border-radius:var(--radius);padding:20px;box-shadow:0 8px 40px rgba(0,0,0,.4);border:1px solid var(--border)}
.field{margin-bottom:14px}
.field-label{display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
input,textarea{width:100%;padding:14px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--input);color:var(--text);font-size:.95rem;transition:border .2s,box-shadow .2s;outline:none}
input:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}
textarea{min-height:160px;resize:vertical;font-family:inherit;line-height:1.5}
.content-wrap{position:relative}
.content-wrap textarea{padding-right:96px;padding-bottom:58px}
.voice-dock{position:absolute;right:10px;bottom:10px;z-index:2;min-width:82px;height:42px;padding:0 12px;border:1px solid rgba(124,111,240,.22);border-radius:14px;display:flex;align-items:center;justify-content:center;gap:8px;background:rgba(18,18,28,.18);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);color:var(--accent);cursor:pointer;box-shadow:0 6px 18px rgba(0,0,0,.18);transition:transform .15s,background .15s,border-color .15s,color .15s}
.voice-dock svg{width:18px;height:18px;flex-shrink:0}
.voice-dock:active{transform:scale(.96)}
.voice-dock.active{background:rgba(124,111,240,.22);border-color:rgba(124,111,240,.45);color:#fff}
.voice-dock:disabled{opacity:.45;cursor:not-allowed}
.voice-meter{display:flex;align-items:flex-end;gap:2px;height:16px;width:18px}
.voice-meter span{width:3px;height:4px;border-radius:999px;background:currentColor;opacity:.5;transition:height .08s linear,opacity .12s linear}
.voice-label{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.voice-status{margin-top:8px;font-size:.78rem;color:var(--muted);min-height:1em}
.voice-status.error{color:var(--error)}
::placeholder{color:var(--muted);opacity:.6}

/* Favorites */
.fav-row{display:flex;gap:6px;overflow-x:auto;padding:2px 0 8px;scrollbar-width:none;-ms-overflow-style:none}
.fav-row::-webkit-scrollbar{display:none}
.fav-chip{flex-shrink:0;background:var(--input);border:1px solid var(--border);border-radius:20px;padding:6px 16px;font-size:.78rem;cursor:pointer;transition:all .2s;white-space:nowrap;color:var(--muted)}
.fav-chip.active{border-color:var(--accent);background:rgba(124,111,240,.12);color:var(--accent)}

/* Folder Browser */
.fold-btn{display:flex;align-items:center;gap:10px;width:100%;padding:14px;background:var(--input);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);font-size:.9rem;cursor:pointer;transition:all .2s;text-align:left}
.fold-btn:active{transform:scale(.98)}
.fold-btn svg{flex-shrink:0}
.fold-btn .cur-path{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--accent)}
.fold-btn .hint{color:var(--muted);font-size:.78rem}

/* Folder Modal */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;display:none;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
.modal{position:fixed;bottom:0;left:0;right:0;max-height:75vh;background:var(--card);border-radius:var(--radius) var(--radius) 0 0;z-index:101;padding:0;display:flex;flex-direction:column;transform:translateY(100%);box-shadow:0-4px 40px rgba(0,0,0,.5);border-top:1px solid var(--border)}
.modal-handle{width:36px;height:4px;border-radius:2px;background:var(--border);margin:10px auto 6px;flex-shrink:0}
.modal-header{display:flex;align-items:center;justify-content:space-between;padding:6px 16px 10px;flex-shrink:0}
.modal-header h2{font-size:.95rem;font-weight:600}
.modal-close{width:32px;height:32px;display:flex;align-items:center;justify-content:center;border:none;background:var(--input);color:var(--muted);border-radius:50%;cursor:pointer;font-size:1.1rem}
.modal-search{padding:0 12px 8px;flex-shrink:0}
.modal-search input{width:100%;padding:10px 12px;border-radius:var(--radius-sm);background:var(--input);border:1px solid var(--border);color:var(--text);font-size:.85rem;outline:none}
.modal-search input:focus{border-color:var(--accent)}
.modal-list{flex:1;overflow-y:auto;padding:0 0 8px;-webkit-overflow-scrolling:touch}
.fold-item{display:flex;align-items:center;gap:8px;padding:10px 16px;cursor:pointer;transition:background .15s;border-radius:6px;margin:0 6px}
.fold-item:active{background:rgba(124,111,240,.1)}
.fold-item .icon{width:20px;flex-shrink:0;color:var(--muted);font-size:.8rem;display:inline-flex;justify-content:center}
.fold-item .name{flex:1;font-size:.88rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fold-item .star-btn{width:28px;height:28px;display:flex;align-items:center;justify-content:center;border:none;background:none;color:var(--muted);font-size:1rem;cursor:pointer;border-radius:50%;flex-shrink:0}
.fold-item .star-btn.active{color:#fbbf24}
.fold-item .chevron{color:var(--muted);font-size:.7rem;flex-shrink:0;transition:transform .2s}
.fold-item .chevron.open{transform:rotate(90deg)}
.fold-children{padding-left:20px;overflow:hidden;max-height:0}
.fold-create{padding:8px 12px 4px;display:flex;gap:6px;flex-shrink:0}
.fold-create input{flex:1;padding:10px 12px;font-size:.85rem;border-radius:var(--radius-sm)}
.fold-create button{width:auto;padding:10px 16px;font-size:.82rem;font-weight:600;border:none;border-radius:var(--radius-sm);background:var(--accent);color:#fff;cursor:pointer;white-space:nowrap}
.fold-create button:active{transform:scale(.96)}
.empty-folder{padding:20px;text-align:center;color:var(--muted);font-size:.82rem}

/* Tag Selector */
.tag-field{border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px;background:var(--input);min-height:48px;cursor:text}
.tag-field:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}
.tag-chips{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px}
.tag-chip{display:inline-flex;align-items:center;gap:4px;background:rgba(124,111,240,.15);border:1px solid rgba(124,111,240,.25);border-radius:10px;padding:4px 10px;font-size:.78rem;transform:scale(0)}
.tag-chip .remove{width:16px;height:16px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%;font-size:12px;color:var(--muted);line-height:1}
.tag-chip .remove:active{background:rgba(248,113,113,.2);color:var(--error)}
.tag-input-wrap input{width:100%;border:none;background:transparent;color:var(--text);padding:6px 0;font-size:.88rem;outline:none}
.tag-suggestions{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;max-height:110px;overflow-y:auto}
.tag-suggestion{cursor:pointer;font-size:.76rem;padding:4px 10px;border:1px solid var(--border);border-radius:14px;color:var(--muted);transition:all .15s}
.tag-suggestion:active{background:rgba(124,111,240,.15);border-color:var(--accent);color:var(--accent)}
.tag-suggestion .cnt{color:var(--border);font-size:.68rem;margin-left:2px}
.tag-suggestion .del{margin-left:6px;color:var(--muted);font-size:.8rem}
.tag-suggestion .del:active{color:var(--error)}

/* Submit Button */
.submit-wrap{padding-top:4px}
.submit-btn{width:100%;padding:16px;border:none;border-radius:var(--radius-sm);background:linear-gradient(135deg,#7c6ff0,#a78bfa);color:#fff;font-size:1rem;font-weight:700;cursor:pointer;transition:transform .15s,box-shadow .15s;position:relative;overflow:hidden}
.submit-btn:active{transform:scale(.97)}
.submit-btn:disabled{opacity:.5;cursor:not-allowed;transform:none}
.submit-btn .btn-text{position:relative;z-index:1}
.submit-btn .btn-shine{position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.15),transparent);transform:translateX(-100%)}

/* YouTube */
#ytField input{font-family:monospace;font-size:.82rem}

/* Result banner */
#result{position:fixed;top:0;left:0;right:0;z-index:200;padding:14px 16px;font-size:.88rem;font-weight:500;text-align:center;transform:translateY(-100%);display:flex;align-items:center;justify-content:center;gap:6px}
#result.success{background:rgba(52,211,153,.12);color:var(--success);border-bottom:1px solid rgba(52,211,153,.2)}
#result.error{background:rgba(248,113,113,.12);color:var(--error);border-bottom:1px solid rgba(248,113,113,.2)}
#result svg{flex-shrink:0}

/* Spinner */
.spinner{display:none;text-align:center;padding:8px 0}
.spinner.show{display:block}
.spinner-ring{display:inline-block;width:22px;height:22px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* Scrollbar */
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* Template */
.tmpl-row{display:flex;gap:6px;overflow-x:auto;padding:2px 0 4px;scrollbar-width:none;-ms-overflow-style:none}
.tmpl-row::-webkit-scrollbar{display:none}
.tmpl-chip{flex-shrink:0;background:var(--input);border:1px solid var(--border);border-radius:20px;padding:6px 16px;font-size:.78rem;cursor:pointer;transition:all .2s;white-space:nowrap;color:var(--muted)}
.tmpl-chip.active{border-color:var(--accent);background:rgba(124,111,240,.12);color:var(--accent)}
.tmpl-fields{margin-top:2px;padding:12px;background:rgba(124,111,240,.04);border:1px solid rgba(124,111,240,.1);border-radius:var(--radius-sm)}
.tmpl-fields .field{margin-bottom:10px}
.tmpl-fields .field:last-child{margin-bottom:0}
.tmpl-fields input,.tmpl-fields textarea{background:var(--card);padding:10px 12px;font-size:.85rem}
#templateFields{margin-bottom:14px}
</style>
</head>
<body>

<div class="container" id="app">
  <h1 id="title">Clipper</h1>

  <div class="card" id="mainCard" style="opacity:0;transform:translateY(20px)">
    <form id="noteForm" onsubmit="return createNote(event)">

      <!-- Folder -->
      <div class="field">
        <div class="field-label">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          Folder
        </div>
        <div class="fav-row" id="favRow"></div>
        <button type="button" class="fold-btn" id="folderBtn">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          <span class="cur-path" id="folderLabel">/</span>
          <span class="hint">Browse</span>
        </button>
        <input type="hidden" name="folder" id="folderInput" value="/">
      </div>

      <!-- Title -->
      <div class="field">
        <div class="field-label">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          Title
        </div>
        <input type="text" id="title" name="title" placeholder="Note title" required autofocus>
      </div>

      <!-- Template -->
      <div class="field">
        <div class="field-label">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="9" x2="15" y2="9"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="12" y2="17"/></svg>
          Template
        </div>
        <div class="tmpl-row" id="tmplRow"></div>
      </div>
      <div id="templateFields"></div>

      <!-- Content -->
      <div class="field">
        <div class="field-label">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          Content
        </div>
        <div class="content-wrap">
          <textarea id="content" name="content" placeholder="Markdown content..."></textarea>
          <button type="button" class="voice-dock" id="voiceBtn" aria-label="Start voice input" title="Voice input">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 1v11"/><path d="M8 6a4 4 0 0 1 8 0v5a4 4 0 0 1-8 0V6z"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v4"/><path d="M8 22h8"/></svg>
            <span class="voice-meter" aria-hidden="true"><span></span><span></span><span></span></span>
            <span id="voiceLabel" class="voice-label">Speak</span>
          </button>
        </div>
        <div class="voice-status" id="voiceStatus"></div>
      </div>

      <!-- YouTube URL -->
      <div class="field" id="ytField">
        <div class="field-label">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 12a29 29 0 0 0 .46 5.58 2.78 2.78 0 0 0 1.94 2C5.12 20 12 20 12 20s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2A29 29 0 0 0 23 12a29 29 0 0 0-.46-5.58z"/><polygon points="9.75 15.02 15.5 12 9.75 8.98 9.75 15.02"/></svg>
          YouTube URL
        </div>
        <input type="url" id="youtubeUrl" name="youtube_url" placeholder="https://youtube.com/watch?v=..." autocomplete="off">
      </div>

      <!-- Tags -->
      <div class="field">
        <div class="field-label">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
          Tags
        </div>
        <div class="tag-field" id="tagField" onclick="document.getElementById('tagInput').focus()">
          <div class="tag-chips" id="tagChips"></div>
          <div class="tag-input-wrap">
            <input type="text" id="tagInput" placeholder="Add tag..." autocomplete="off">
          </div>
          <div class="tag-suggestions" id="tagSuggestions"></div>
        </div>
        <input type="hidden" name="tags" id="tagsInput" value="">
      </div>

      <div class="spinner" id="spinner"><div class="spinner-ring"></div></div>

      <div class="submit-wrap">
        <button type="submit" class="submit-btn" id="submitBtn">
          <span class="btn-shine" id="btnShine"></span>
          <span class="btn-text">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
            Create Note
          </span>
        </button>
      </div>
    </form>
  </div>
</div>

<!-- Folder Bottom Sheet -->
<div class="modal-overlay" id="modalOverlay" onclick="closeFolderModal()"></div>
<div class="modal" id="folderModal">
  <div class="modal-handle"></div>
  <div class="modal-header">
    <h2>Choose Folder</h2>
    <button class="modal-close" onclick="closeFolderModal()">&times;</button>
  </div>
  <div class="modal-search"><input type="text" id="foldSearch" placeholder="Search folders..." oninput="filterFolders(this.value)"></div>
  <div class="modal-list" id="foldList">
    <div class="fold-item" onclick="pickFolder('/')">
      <span class="icon">/</span>
      <span class="name">Root</span>
      <span class="star-btn" id="starRoot" onclick="event.stopPropagation();toggleFav('/')">&#9733;</span>
    </div>
  </div>
  <div class="fold-create">
    <input type="text" id="newFolderInput" placeholder="New folder name...">
    <button onclick="createNewFolder()">Create</button>
  </div>
</div>

<!-- Result Banner -->
<div id="result"></div>

<script>
// ---- State ----
let allFolders = [];
let flatFolders = [];
let favorites = [];
let selectedFolder = "/";
let allTags = [];
let selectedTags = [];
let folderTree = {};
let builtinTemplates = [];
let customTemplates = [];
let selectedTemplate = "goal";
let templateFieldValues = {};
let recognition = null;
let isListening = false;
let voiceWaveTimer = null;

// ---- GSAP Animations ----
function initAnim() {
  var tl = gsap.timeline({defaults:{ease:'power3.out'}});
  tl.to('#title', {opacity:1,y:0,duration:.5});
  tl.to('#mainCard', {opacity:1,y:0,duration:.5}, '-=0.2');
  tl.from('.field', {opacity:0,y:12,duration:.35,stagger:.06}, '-=0.3');
  tl.from('.submit-wrap', {opacity:0,y:12,duration:.3}, '-=0.1');
}

function animBtnShine() {
  gsap.fromTo('#btnShine', {x:'-100%'}, {x:'200%',duration:.6,ease:'power2.inOut'});
}

function animSuccess() {
  var el = document.getElementById('result');
  el.style.display = 'flex';
  gsap.to(el, {y:0,duration:.35,ease:'back.out(1.7)'});
  gsap.delayedCall(3.5, function() {
    gsap.to(el, {y:'-100%',duration:.25,ease:'power2.in',onComplete:function(){
      el.style.display = 'none'; el.className = ''; el.innerHTML = '';
    }});
  });
}

function animError() {
  var el = document.getElementById('result');
  el.style.display = 'flex';
  gsap.to(el, {y:0,duration:.35,ease:'power3.out'});
}

function startVoiceWaves() {
  var bars = document.querySelectorAll('.voice-meter span');
  if (!bars.length) return;
  stopVoiceWaves();
  var phase = 0;

  function setBase() {
    for (var i = 0; i < bars.length; i++) {
      bars[i].style.height = (4 + i * 2) + 'px';
      bars[i].style.opacity = '0.5';
    }
  }

  setBase();
  voiceWaveTimer = setInterval(function() {
    if (!isListening) return;
    phase += 0.45;
    for (var i = 0; i < bars.length; i++) {
      var wave = Math.abs(Math.sin(phase + i * 0.9));
      bars[i].style.height = (4 + Math.round(wave * 14)) + 'px';
      bars[i].style.opacity = (0.45 + wave * 0.55).toFixed(2);
    }
  }, 80);
}

function stopVoiceWaves() {
  if (voiceWaveTimer) {
    clearInterval(voiceWaveTimer);
    voiceWaveTimer = null;
  }
  var bars = document.querySelectorAll('.voice-meter span');
  for (var i = 0; i < bars.length; i++) {
    bars[i].style.height = (4 + i * 2) + 'px';
    bars[i].style.opacity = '0.5';
  }
}

function initVoiceInput() {
  var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  var btn = document.getElementById('voiceBtn');
  var label = document.getElementById('voiceLabel');
  var content = document.getElementById('content');
  var result = document.getElementById('result');
  var status = document.getElementById('voiceStatus');

  function setStatus(message, isError) {
    if (!status) return;
    status.textContent = message || '';
    status.className = isError ? 'voice-status error' : 'voice-status';
  }

  if (!btn || !content) return;
  if (window.isSecureContext === false) {
    setStatus('Voice input needs HTTPS or localhost to access the browser mic.', true);
  }

  if (!SpeechRecognition) {
    btn.disabled = true;
    if (label) label.textContent = 'Unavailable';
    setStatus('This browser does not support the Web Speech API.', true);
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = navigator.language || 'en-US';

  function formatVoiceTranscript(text) {
    var clean = text.trim().replace(/\s+/g, ' ');
    var sentences = clean.match(/[^.!?]+[.!?]+|[^.!?]+$/g);
    if (sentences && sentences.length > 1) {
      return sentences.map(function(sentence) { return sentence.trim(); }).join('\n\n');
    }
    return clean;
  }

  if (recognition) {
  recognition.onstart = function() {
    isListening = true;
    btn.classList.add('active');
    btn.setAttribute('aria-label', 'Stop voice input');
    if (label) label.textContent = 'Stop';
    startVoiceWaves();
    };

  recognition.onend = function() {
    isListening = false;
    btn.classList.remove('active');
    btn.setAttribute('aria-label', 'Start voice input');
    if (label) label.textContent = 'Speak';
    stopVoiceWaves();
    setStatus('');
  };

    recognition.onresult = function(event) {
      var transcript = '';
      for (var i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          transcript += event.results[i][0].transcript.trim() + ' ';
        }
      }
      if (transcript) {
        var formatted = formatVoiceTranscript(transcript);
        content.value = content.value ? content.value.trimEnd() + '\n\n' + formatted : formatted;
        content.dispatchEvent(new Event('input', { bubbles: true }));
      }
    };

  recognition.onerror = function(event) {
    if (event.error === 'aborted') {
      setStatus('');
      stopVoiceWaves();
      return;
    }
    isListening = false;
    btn.classList.remove('active');
    btn.setAttribute('aria-label', 'Start voice input');
    if (label) label.textContent = 'Speak';
    stopVoiceWaves();
    setStatus('Voice input error: ' + event.error, true);
    result.className = 'error';
    result.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> Voice input error: ' + event.error;
    animError();
  };
  }

  btn.addEventListener('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    if (isListening) {
      recognition.stop();
      return;
    }
    content.blur();
    try {
      setStatus('');
      recognition.start();
    } catch (err) {
      setStatus('Could not start voice input: ' + err.message, true);
      result.className = 'error';
      result.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> ' + err.message;
      animError();
    }
  });
}

function animTagIn(el) {
  gsap.fromTo(el, {scale:0,opacity:0}, {scale:1,opacity:1,duration:.25,ease:'back.out(2)'});
}

function animFolderModal(open) {
  if (open) {
    loadFolders().then(function(){ renderModalFolders(); });
    document.getElementById('modalOverlay').style.display = 'block';
    gsap.fromTo('#modalOverlay', {opacity:0}, {opacity:1,duration:.2});
    document.getElementById('folderModal').style.display = 'flex';
    gsap.fromTo('#folderModal', {y:'100%'}, {y:'0%',duration:.35,ease:'power3.out'});
  } else {
    gsap.to('#modalOverlay', {opacity:0,duration:.15});
    gsap.to('#folderModal', {y:'100%',duration:.25,ease:'power2.in',onComplete:function(){
      document.getElementById('modalOverlay').style.display = 'none';
      document.getElementById('folderModal').style.display = 'none';
    }});
  }
}

function animFolderSlide(el, open) {
  if (open) {
    el.style.display = 'block';
    gsap.fromTo(el, {maxHeight:0,opacity:0}, {maxHeight:el.scrollHeight,opacity:1,duration:.3,ease:'power2.out'});
  } else {
    gsap.to(el, {maxHeight:0,opacity:0,duration:.2,ease:'power2.in',onComplete:function(){
      el.style.display = '';
    }});
  }
}

// ---- Folder Tree ----
function buildTree(f) {
  var t = {name:'/',path:'/',children:{}};
  for (var i=0;i<f.length;i++) {
    if (f[i]==='/') continue;
    var parts = f[i].replace(/^\//,'').split('/');
    var n = t;
    for (var j=0;j<parts.length;j++) {
      if (!n.children[parts[j]]) n.children[parts[j]] = {name:parts[j],path:n.path+parts[j]+'/',children:{}};
      n = n.children[parts[j]];
    }
  }
  return t;
}

function renderModalFolders() {
  var list = document.getElementById('foldList');
  var rootHtml = '<div class="fold-item" onclick="pickFolder(\'/\')">' +
    '<span class="icon">/</span><span class="name">Root</span>' +
    '<span class="star-btn' + (favorites.indexOf('/')>=0?' active':'') + '" onclick="event.stopPropagation();toggleFav(\'/\')">&#9733;</span></div>';
  var html = '';
  for (var i=0;i<flatFolders.length;i++) {
    var f = flatFolders[i];
    if (f==='/') continue;
    var depth = f.split('/').filter(Boolean).length;
    var label = f.replace(/\/$/,'').split('/').pop();
    var sel = f===selectedFolder ? ' style="background:rgba(124,111,240,.1);border:1px solid rgba(124,111,240,.2)"' : '';
    var starCls = favorites.indexOf(f)>=0 ? ' active' : '';
    html += '<div class="fold-item" onclick="pickFolder(\''+f+'\')" data-path="'+f+'" style="padding-left:'+Math.min(16 + depth*12,64)+'px"' + sel + '>' +
      '<span class="icon">&#128193;</span>' +
      '<span class="name">'+label+'</span>' +
      '<span class="star-btn'+starCls+'" onclick="event.stopPropagation();toggleFav(\''+f+'\')">&#9733;</span></div>';
  }
  list.innerHTML = rootHtml + html;
}

function pickFolder(path) {
  selectedFolder = path;
  document.getElementById('folderInput').value = path;
  document.getElementById('folderLabel').textContent = path;
  closeFolderModal();
  gsap.fromTo('#folderLabel', {scale:1.05}, {scale:1,duration:.2});
  renderFavRow();
  loadTags();
}

function filterFolders(q) {
  var items = document.querySelectorAll('.fold-item');
  q = q.toLowerCase();
  for (var i=0;i<items.length;i++) {
    var name = items[i].querySelector('.name').textContent.toLowerCase();
    items[i].style.display = name.includes(q) ? '' : 'none';
  }
}

function closeFolderModal() { animFolderModal(false); }

// ---- Favorites ----
function renderFavRow() {
  var row = document.getElementById('favRow');
  if (!favorites.length) { row.innerHTML = ''; return; }
  var html = '';
  for (var i=0;i<favorites.length;i++) {
    var f = favorites[i];
    var act = f===selectedFolder ? ' active' : '';
    var label = f==='/' ? 'Root' : f.replace(/\/$/,'').split('/').pop();
    html += '<span class="fav-chip'+act+'" onclick="pickFolder(\''+f+'\')">'+label+'</span>';
  }
  row.innerHTML = html;
}

async function toggleFav(path) {
  var idx = favorites.indexOf(path);
  if (idx>=0) favorites.splice(idx,1); else favorites.push(path);
  await savePrefs();
  renderFavRow();
  renderModalFolders();
}

// ---- Tags ----
function tagsUrl() {
  return selectedFolder&&selectedFolder!=='/'?'/api/tags?folder='+encodeURIComponent(selectedFolder):'/api/tags';
}
function renderTagChips() {
  var c = document.getElementById('tagChips');
  c.innerHTML = '';
  for (var i=0;i<selectedTags.length;i++) {
    var t = selectedTags[i];
    var el = document.createElement('span');
    el.className = 'tag-chip';
    el.innerHTML = t + '<span class="remove" onclick="removeTag(\''+t+'\')">&#x2715;</span>';
    c.appendChild(el);
    animTagIn(el);
  }
  document.getElementById('tagsInput').value = selectedTags.join(', ');
}

function removeTag(t) {
  selectedTags = selectedTags.filter(function(x){return x!==t});
  renderTagChips();
  document.getElementById('tagInput').focus();
}

var tagEnterBlock = false;
async function addTag(t) {
  t = t.trim().replace(/^#/,'');
  if (!t || selectedTags.indexOf(t)>=0) return;
  selectedTags.push(t);
  renderTagChips();
  document.getElementById('tagInput').value = '';
  showTagSuggestions('');
  await saveTagsToServer(selectedTags);
  await loadTags();
}

function showTagSuggestions(query) {
  var sug = document.getElementById('tagSuggestions');
  if (!query) {
    sug.innerHTML = allTags.filter(function(t){return selectedTags.indexOf(t.name)<0}).slice(0,24).map(function(t){
      var del = t.count===0 ? '<span class="del" onclick="event.stopPropagation();deleteTagHistory(\''+t.name.replace(/'/g,"\\'")+'\')">✕</span>' : '';
      return '<span class="tag-suggestion" onclick="addTag(\''+t.name+'\')">#'+t.name+' <span class="cnt">('+t.count+')</span>'+del+'</span>';
    }).join('');
    return;
  }
  var q = query.toLowerCase();
  var matches = allTags.filter(function(t){return t.name.toLowerCase().includes(q)&&selectedTags.indexOf(t.name)<0});
  if (!matches.length) {
    sug.innerHTML = '<span class="tag-suggestion" onclick="addTag(\''+query.replace(/'/g,"\\'")+'\')">+ Create "'+query+'"</span>';
    return;
  }
  sug.innerHTML = matches.slice(0,15).map(function(t){
    var del = t.count===0 ? '<span class="del" onclick="event.stopPropagation();deleteTagHistory(\''+t.name.replace(/'/g,"\\'")+'\')">✕</span>' : '';
    return '<span class="tag-suggestion" onclick="addTag(\''+t.name+'\')">#'+t.name+' <span class="cnt">('+t.count+')</span>'+del+'</span>';
  }).join('');
}

async function saveTagsToServer(tags) {
  try{await fetch('/api/tags',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tags:tags})})}catch(e){}
}

async function deleteTagHistory(tag) {
  if(!confirm('Delete #'+tag+' from UI suggestions? This will not remove it from existing notes.')) return;
  try{
    await fetch('/api/tags/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tag:tag})});
    await loadTags();
    showTagSuggestions(document.getElementById('tagInput').value);
  }catch(e){}
}

// ---- Templates ----
async function loadTemplates() {
  try{var r=await fetch('/api/templates');var d=await r.json();builtinTemplates=d.builtin||[];customTemplates=d.custom||[];renderTemplateSelector();}catch(e){}
}
function getAllTemplates() {
  return builtinTemplates.concat(customTemplates);
}
function renderTemplateSelector() {
  var row=document.getElementById('tmplRow');var all=getAllTemplates();row.innerHTML='';
  for(var i=0;i<all.length;i++){
    var t=all[i];var act=t.id===selectedTemplate?' active':'';
    var el=document.createElement('span');el.className='tmpl-chip'+act;el.textContent=t.name;
    el.onclick=function(id){return function(){selectTemplate(id);}}(t.id);
    row.appendChild(el);
  }
}
function selectTemplate(id) {
  selectedTemplate=id;renderTemplateSelector();renderTemplateFields(id);
  gsap.fromTo('#templateFields',{opacity:0,y:8},{opacity:1,y:0,duration:.25,ease:'power2.out'});
}
function renderTemplateFields(id) {
  var container=document.getElementById('templateFields');
  var all=getAllTemplates();var tmpl=null;
  for(var i=0;i<all.length;i++){if(all[i].id===id){tmpl=all[i];break;}}
  if(!tmpl||!tmpl.fields||!tmpl.fields.length){container.innerHTML='';return;}
  var html='<div class="tmpl-fields">';
  for(var i=0;i<tmpl.fields.length;i++){
    var f=tmpl.fields[i];
    var val=templateFieldValues[f.key]||'';
    if(f.type==='textarea'){
      html+='<div class="field"><div class="field-label">'+f.label+'</div><textarea data-tkey="'+f.key+'" placeholder="'+(f.placeholder||'')+'" style="min-height:60px">'+val+'</textarea></div>';
    }else{
      html+='<div class="field"><div class="field-label">'+f.label+'</div><input type="text" data-tkey="'+f.key+'" placeholder="'+(f.placeholder||'')+'" value="'+val+'"></div>';
    }
  }
  html+='</div>';container.innerHTML=html;
}
function collectTemplateFields() {
  var container=document.getElementById('templateFields');
  var inputs=container.querySelectorAll('[data-tkey]');
  for(var i=0;i<inputs.length;i++){
    templateFieldValues[inputs[i].getAttribute('data-tkey')]=inputs[i].value;
  }
  var all=getAllTemplates();var tmpl=null;
  for(var i=0;i<all.length;i++){if(all[i].id===selectedTemplate){tmpl=all[i];break;}}
  var lines=[];
  if(tmpl&&tmpl.fields){
    for(var i=0;i<tmpl.fields.length;i++){
      var key=tmpl.fields[i].key;var label=tmpl.fields[i].label;
      var val=templateFieldValues[key];
      if(val&&val.trim())lines.push('**'+label+':** '+val.trim());
    }
  }
  var yt=document.getElementById('youtubeUrl').value.trim();
  if(yt)lines.push('**YouTube URL:** '+yt);
  return lines.length?'## Metadata\n\n'+lines.join('\n')+'\n\n---\n\n':'';
}

// ---- API Calls ----
async function loadFolders() {
  try{var r=await fetch('/api/folders?ts='+Date.now(),{cache:'no-store'});allFolders=await r.json();flatFolders=allFolders;folderTree=buildTree(allFolders);}catch(e){}
  // prune stale favorites and stale selected folder
  var changed=false;
  favorites=favorites.filter(function(f){var ok=allFolders.indexOf(f)>=0; if(!ok)changed=true; return ok;});
  if(allFolders.indexOf(selectedFolder)<0){selectedFolder='/';document.getElementById('folderInput').value='/';document.getElementById('folderLabel').textContent='/';changed=true;}
  if(changed){await savePrefs();renderFavRow();}
}
async function loadTags() {
  try{var r=await fetch(tagsUrl());allTags=await r.json();allTags.sort(function(a,b){return a.name.localeCompare(b.name);});showTagSuggestions(document.getElementById('tagInput').value);}catch(e){}
}
async function loadPrefs() {
  try{var r=await fetch('/api/preferences');var d=await r.json();if(d.favorites)favorites=d.favorites;if(d.lastFolder){selectedFolder=d.lastFolder;document.getElementById('folderInput').value=selectedFolder;document.getElementById('folderLabel').textContent=selectedFolder;}if(allFolders.length){var changed=false;favorites=favorites.filter(function(f){var ok=allFolders.indexOf(f)>=0; if(!ok)changed=true; return ok;});if(allFolders.indexOf(selectedFolder)<0){selectedFolder='/';document.getElementById('folderInput').value='/';document.getElementById('folderLabel').textContent='/';changed=true;}if(changed)await savePrefs();}renderFavRow();}catch(e){}
}
async function savePrefs() {
  try{await fetch('/api/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({favorites:favorites,lastFolder:selectedFolder})})}catch(e){}
}

// ---- New Folder ----
async function createNewFolder() {
  var input=document.getElementById('newFolderInput');var name=input.value.trim();if(!name)return;
  var path=(selectedFolder==='/'?'/':selectedFolder+'/')+name;
  if(!path.endsWith('/'))path+='/';
  try{
    var r=await fetch('/api/folders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:path.replace(/^\//,'').replace(/\/$/,'')})});
    if(!r.ok)throw new Error((await r.json()).detail||'Failed');
    input.value='';await loadFolders();flatFolders=allFolders;renderModalFolders();pickFolder(path);
  }catch(e){alert('Folder error: '+e.message);}
}

// ---- Create Note ----
async function createNote(e) {
  e.preventDefault();
  var btn=document.getElementById('submitBtn');var spinner=document.getElementById('spinner');var result=document.getElementById('result');
  result.style.display='none';btn.disabled=true;spinner.classList.add('show');animBtnShine();
  collectTemplateFields();
  var tmplContent=selectedTemplate!=='freeform'?collectTemplateFields():'';
  var origContent=document.getElementById('content').value;
  var finalContent=tmplContent+origContent;
  var form=new FormData(document.getElementById('noteForm'));
  form.set('content',finalContent);
  function resetAfterSuccess(){
    document.getElementById('title').value='';
    document.getElementById('content').value='';
    document.getElementById('youtubeUrl').value='';
    selectedTags=[];renderTagChips();
    templateFieldValues={};
    renderTemplateFields(selectedTemplate);
  }
  try{
    var r=await fetch('/api/create',{method:'POST',body:form});var data=await r.json();
    if(r.ok&&data.success){
      if(data.duplicate){
        result.className='error';result.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> Already processed — see <a href="#" style="color:var(--accent);text-decoration:underline" onclick="event.preventDefault();document.getElementById(\'folderInput\').value=\''+data.existing.replace(/\/[^\/]+\.md$/,'')+'\';document.getElementById(\'folderLabel\').textContent=\''+data.existing.replace(/\/[^\/]+\.md$/,'')+'\';selectedFolder=\''+data.existing.replace(/\/[^\/]+\.md$/,'')+'\'">'+data.existing+'</a>';
        animError();
      }else if(data.playlist){
        var msg='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> Playlist processed — ';
        if(data.created&&data.created.length)msg+=data.created.length+' created';
        if(data.created&&data.created.length&&data.skipped&&data.skipped.length)msg+=', ';
        if(data.skipped&&data.skipped.length)msg+=data.skipped.length+' skipped (already exist)';
        result.className='success';result.innerHTML=msg;
        resetAfterSuccess();await savePrefs();animSuccess();
      }else{
        result.className='success';result.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> Note created';
        resetAfterSuccess();await savePrefs();animSuccess();
      }
    }else if(data.duplicate){
      result.className='error';result.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> Already processed — '+(data.existing||data.video_id||'');animError();
    }else{
      result.className='error';result.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> '+(data.detail||'Error');animError();
    }
  }catch(e){result.className='error';result.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> '+e.message;animError();}
  btn.disabled=false;spinner.classList.remove('show');
}

// ---- Events ----
document.addEventListener('DOMContentLoaded',function(){
  initAnim();
  loadFolders();loadTags();loadPrefs();loadTemplates();

  document.getElementById('folderBtn').addEventListener('click',function(){animFolderModal(true);});
  document.getElementById('tagInput').addEventListener('focus',function(){showTagSuggestions('');});
  document.getElementById('tagInput').addEventListener('input',function(){showTagSuggestions(this.value);});
  document.getElementById('tagInput').addEventListener('keydown',function(e){
    if(e.key==='Enter'){e.preventDefault();addTag(this.value);}
    if(e.key==='Backspace'&&!this.value&&selectedTags.length){selectedTags.pop();renderTagChips();}
  });
  document.getElementById('newFolderInput').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();createNewFolder();}});
  document.getElementById('title').addEventListener('keydown',function(e){if(e.key==='Enter'&&e.ctrlKey)document.getElementById('submitBtn').click();});
  initVoiceInput();
});
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(
        content=FORM_HTML,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/api/folders")
async def list_folders():
    return scan_folders()

@app.post("/api/folders")
async def create_folder(data: FolderCreate):
    path = data.path.strip().strip("/")
    if not path:
        raise HTTPException(400, "Path is required")
    full = os.path.join(VAULT_PATH, path)
    try:
        os.makedirs(full, exist_ok=True)
        return {"success": True, "path": path}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/tags")
async def list_tags(folder: str = ""):
    scanned = scan_tags(folder if folder else None)
    prefs = get_prefs()
    history = prefs.get("tagHistory", [])
    hidden = set(prefs.get("hiddenTags", []))
    seen = set()
    merged = []
    for t in scanned:
        if t["name"] in hidden:
            continue
        seen.add(t["name"])
        merged.append(t)
    for h in history:
        if h not in seen and h not in hidden:
            merged.append({"name": h, "count": 0})
    merged.sort(key=lambda x: x.get("name", ""))
    return merged

@app.post("/api/tags")
async def save_tags(request: Request):
    data = await request.json()
    tags = data.get("tags", [])
    prefs = get_prefs()
    history = prefs.setdefault("tagHistory", [])
    for t in tags:
        tag = str(t).strip().lower()
        if tag and tag not in history:
            history.append(tag)
    save_prefs(prefs)
    return {"success": True}

@app.post("/api/tags/delete")
async def delete_tag(data: TagDelete):
    prefs = get_prefs()
    history = prefs.get("tagHistory", [])
    tag = data.tag.strip().lower()
    prefs["tagHistory"] = [t for t in history if t != tag]
    hidden = set(prefs.get("hiddenTags", []))
    hidden.add(tag)
    prefs["hiddenTags"] = sorted(hidden)
    save_prefs(prefs)
    return {"success": True}

@app.get("/api/preferences")
async def get_preferences():
    return get_prefs()

@app.post("/api/preferences")
async def set_preferences(data: PrefsUpdate):
    prefs = get_prefs()
    if data.favorites is not None:
        prefs["favorites"] = data.favorites
    if data.lastFolder is not None:
        prefs["lastFolder"] = data.lastFolder
    save_prefs(prefs)
    return {"success": True}

@app.post("/api/create")
async def create_note(
    request: Request,
    folder: str = Form("/"),
    title: str = Form(...),
    content: str = Form(""),
    tags: str = Form(""),
    youtube_url: str = Form(""),
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    if youtube_url:
        is_playlist = "list=" in youtube_url and "watch?v=" not in youtube_url
        is_playlist = is_playlist or "/playlist?" in youtube_url

        if is_playlist:
            try:
                async with httpx.AsyncClient(timeout=120) as c:
                    r = await c.post(f"{YOUTUBE_PROXY}/api/process-playlist", json={"url": youtube_url})
                    if r.status_code != 200:
                        raise HTTPException(status_code=502, detail="Playlist processing failed")
                    playlist_data = r.json()
                    videos = playlist_data.get("videos", []) if isinstance(playlist_data, dict) else []
                    if not videos and isinstance(playlist_data, list):
                        videos = playlist_data
            except httpx.ConnectError:
                raise HTTPException(status_code=503, detail="YouTube proxy not available")
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="YouTube proxy timed out")

            created = []
            skipped = []
            for v in videos:
                vid = v.get("video_id", "")
                vid_url = v.get("url", "") or f"https://youtube.com/watch?v={vid}"
                vid_title = v.get("title", "") or vid
                vid_transcript = v.get("transcript", "") or ""

                # Dedup per video
                duplicate = False
                if vid:
                    for root, _, files in os.walk(VAULT_PATH):
                        if "/.obsidian" in root or "/.trash" in root:
                            continue
                        for f in files:
                            if not f.endswith(".md"):
                                continue
                            try:
                                with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                                    c = fh.read()
                                meta = parse_metadata(c)
                                yt = meta.get("YouTube URL", "")
                                if vid_url in yt or vid in yt:
                                    duplicate = True
                                    break
                            except: pass
                        if duplicate:
                            break

                if duplicate:
                    skipped.append({"video_id": vid, "title": vid_title})
                    continue

                # Compose note
                note_title = f"{title} - {vid_title}" if title else vid_title
                note_content = f"> Transcript of {vid_url}\n\n{vid_transcript}\n\n---\n\n{content}" if vid_transcript else content
                filename = slugify(note_title) + ".md"
                path = f"{folder}/{filename}".replace("//", "/")
                md = f"# {note_title}\n\n{note_content}\n"
                if tag_list:
                    md += "\n" + " ".join(f"#{t}" for t in tag_list) + "\n"
                r = await api_put(path, md)
                if r.status_code in (200, 201, 204):
                    created.append({"path": path, "video_id": vid, "title": vid_title})
                else:
                    skipped.append({"video_id": vid, "title": vid_title, "error": r.text[:100]})

            if tag_list:
                prefs = get_prefs()
                history = prefs.setdefault("tagHistory", [])
                for t in tag_list:
                    tag = t.strip().lower()
                    if tag and tag not in history:
                        history.append(tag)
                save_prefs(prefs)

            return {"success": True, "playlist": True, "created": created, "skipped": skipped}

        # Single video flow
        transcript = None
        video_id = ""
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.get(f"{YOUTUBE_PROXY}/api/transcript-from-url", params={"url": youtube_url})
                if r.status_code == 200:
                    data = r.json()
                    if data.get("success"):
                        transcript = data.get("transcript", "")
                        video_id = data.get("video_id", "")
                elif r.status_code == 502:
                    raise HTTPException(status_code=503, detail="YouTube proxy not available")
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="YouTube proxy not available")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="YouTube proxy timed out")

        if video_id:
            for root, _, files in os.walk(VAULT_PATH):
                if "/.obsidian" in root or "/.trash" in root:
                    continue
                for f in files:
                    if not f.endswith(".md"):
                        continue
                    try:
                        with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                            c = fh.read()
                        meta = parse_metadata(c)
                        yt = meta.get("YouTube URL", "")
                        if youtube_url in yt or video_id in yt:
                            rel = os.path.relpath(os.path.join(root, f), VAULT_PATH).replace("\\", "/")
                            return {"success": False, "duplicate": True, "existing": "/" + rel, "video_id": video_id}
                    except: pass

        if transcript:
            content = f"> Transcript of {youtube_url}\n\n{transcript}\n\n---\n\n" + content

    # Single note (non-playlist or no youtube_url)
    filename = slugify(title) + ".md"
    path = f"{folder}/{filename}".replace("//", "/")

    md = f"# {title}\n\n{content}\n"
    if tag_list:
        md += "\n" + " ".join(f"#{t}" for t in tag_list) + "\n"

    r = await api_put(path, md)

    if r.status_code in (200, 201, 204):
        if tag_list:
            prefs = get_prefs()
            history = prefs.setdefault("tagHistory", [])
            for t in tag_list:
                tag = t.strip().lower()
                if tag and tag not in history:
                    history.append(tag)
            save_prefs(prefs)
        return {"success": True, "path": path, "video_id": video_id if youtube_url else None}
    else:
        detail = r.text[:200]
        try:
            detail = r.json().get("message", detail)
        except: pass
        raise HTTPException(status_code=r.status_code, detail=detail)

@app.get("/api/templates")
async def get_templates():
    prefs = get_prefs()
    custom = prefs.get("customTemplates", [])
    return {"builtin": BUILTIN_TEMPLATES, "custom": custom}

@app.post("/api/templates")
async def save_templates(request: Request):
    data = await request.json()
    prefs = get_prefs()
    prefs["customTemplates"] = data.get("templates", [])
    save_prefs(prefs)
    return {"success": True}

@app.get("/api/metadata/search")
async def search_metadata(
    goal: str = "", purpose: str = "", intent: str = "",
    outcome: str = "", q: str = ""
):
    """Search all notes by metadata fields. Returns matching file paths with metadata.
    - q: search across all metadata field values (substring match)
    - goal, purpose, intent, outcome: filter by specific field value (substring match, case-insensitive)
    All params are AND'd together. Empty params are ignored."""
    filters = {}
    if goal: filters["Goal"] = goal.lower()
    if purpose: filters["Purpose"] = purpose.lower()
    if intent: filters["User Intent"] = intent.lower()
    if outcome: filters["Expected Outcome"] = outcome.lower()

    results = []
    if not os.path.isdir(VAULT_PATH):
        return {"count": 0, "results": results}

    for root, _, files in os.walk(VAULT_PATH):
        if "/.obsidian" in root.replace("\\", "/") or "/.git" in root.replace("\\", "/") or "/.trash" in root.replace("\\", "/"):
            continue
        for f in files:
            if not f.endswith(".md"):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                meta = parse_metadata(content)
                if not meta:
                    continue
                # Apply filters
                match = True
                for key, val in filters.items():
                    if meta.get(key, "").lower().find(val) < 0:
                        match = False
                        break
                if q:
                    if not any(q.lower() in v.lower() for v in meta.values()):
                        match = False
                if match:
                    rel = os.path.relpath(fp, VAULT_PATH).replace("\\", "/")
                    results.append({"path": "/" + rel, "metadata": meta})
            except:
                pass
    return {"count": len(results), "results": results}

@app.get("/api/metadata/{path:path}")
async def get_note_metadata(path: str):
    """Get parsed metadata for a single note by its vault path."""
    clean = path.lstrip("/")
    fp = os.path.join(VAULT_PATH, clean)
    if not os.path.isfile(fp):
        raise HTTPException(status_code=404, detail="Note not found")
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    meta = parse_metadata(content)
    return {"path": "/" + clean, "metadata": meta}

@app.get("/api/notes")
async def list_notes():
    """List all markdown notes in the vault with their paths."""
    notes = []
    if not os.path.isdir(VAULT_PATH):
        return {"count": 0, "notes": notes}
    for root, _, files in os.walk(VAULT_PATH):
        if "/.obsidian" in root.replace("\\", "/") or "/.git" in root.replace("\\", "/") or "/.trash" in root.replace("\\", "/"):
            continue
        for f in files:
            if not f.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(root, f), VAULT_PATH).replace("\\", "/")
            notes.append("/" + rel)
    return {"count": len(notes), "notes": sorted(notes)}

@app.get("/api/notes/{path:path}")
async def read_note(path: str):
    """Read a note's raw markdown content by its vault path."""
    r = await api_get(path)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Note not found")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:200])
    return {"path": "/" + path.lstrip("/"), "content": r.text}

@app.put("/api/notes/{path:path}")
async def write_note(path: str, request: Request):
    """Write (create or overwrite) a note at the given path.
    Body should be raw markdown text with content-type text/plain or application/json with {"content": "..."}."""
    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        data = await request.json()
        content = data.get("content", "")
    else:
        content = await request.body()
        content = content.decode("utf-8")
    r = await api_put(path, content)
    if r.status_code not in (200, 201, 204):
        detail = r.text[:200]
        try:
            detail = r.json().get("message", detail)
        except: pass
        raise HTTPException(status_code=r.status_code, detail=detail)
    return {"success": True, "path": "/" + path.lstrip("/")}

@app.delete("/api/notes/{path:path}")
async def delete_note(path: str):
    """Delete a note by its vault path."""
    r = await api_delete(path)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Note not found")
    if r.status_code not in (200, 201, 204):
        raise HTTPException(status_code=r.status_code, detail=r.text[:200])
    return {"success": True, "path": "/" + path.lstrip("/")}

@app.get("/health")
async def health():
    return {"status": "ok"}
