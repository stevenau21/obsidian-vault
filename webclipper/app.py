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

os.makedirs(PREFS_PATH, exist_ok=True)

class FolderCreate(BaseModel):
    path: str

class PrefsUpdate(BaseModel):
    favorites: list[str] | None = None
    lastFolder: str | None = None

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

def scan_tags():
    tags = {}
    if not os.path.isdir(VAULT_PATH):
        return tags
    for root, _, files in os.walk(VAULT_PATH):
        if "/.obsidian" in root.replace("\\", "/") or "/.git" in root.replace("\\", "/"):
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

FORM_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Obsidian WebClipper</title>
<style>
  :root {
    --bg: #1a1a2e; --card: #16213e; --input: #0f172a;
    --text: #e0e0e0; --muted: #94a3b8; --border: #334155;
    --accent: #a78bfa; --accent-hover: #8b5cf6;
    --success: #34d399; --error: #f87171;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); min-height: 100vh;
    padding: 20px;
  }
  .container { max-width: 640px; margin: 0 auto; }
  h1 { text-align: center; margin: 16px 0 20px; font-size: 1.5rem; color: var(--accent); }
  .card {
    background: var(--card); border-radius: 12px; padding: 24px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  }
  .field { margin-bottom: 16px; }
  label { display: block; margin-bottom: 6px; font-size: 0.85rem; color: var(--muted); font-weight: 600; }
  input, textarea, select {
    width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px;
    background: var(--input); color: var(--text); font-size: 0.95rem;
    transition: border 0.2s;
  }
  input:focus, textarea:focus { outline: none; border-color: var(--accent); }
  textarea { min-height: 200px; resize: vertical; font-family: monospace; }
  button {
    width: 100%; padding: 12px; border: none; border-radius: 8px;
    background: var(--accent); color: #fff; font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: background 0.2s;
  }
  button:hover { background: var(--accent-hover); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  #result { margin-top: 16px; padding: 12px; border-radius: 8px; display: none; }
  #result.success { display: block; border: 1px solid var(--success); color: var(--success); }
  #result.error { display: block; border: 1px solid var(--error); color: var(--error); }
  .spinner { display: none; text-align: center; margin: 10px 0; }
  .spinner.active { display: block; }
  .spinner::after {
    content: ""; display: inline-block; width: 24px; height: 24px;
    border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Folder Tree */
  .folder-browser { border: 1px solid var(--border); border-radius: 8px; background: var(--input); max-height: 260px; overflow-y: auto; }
  .folder-browser:focus-within { border-color: var(--accent); }
  .folder-item {
    display: flex; align-items: center; padding: 4px 8px 4px 4px;
    cursor: pointer; border-radius: 4px; margin: 1px 4px;
    transition: background 0.15s;
  }
  .folder-item:hover { background: rgba(167,139,250,0.1); }
  .folder-item.selected { background: rgba(167,139,250,0.2); border: 1px solid rgba(167,139,250,0.3); }
  .folder-item .toggle {
    width: 20px; height: 20px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
    font-size: 10px; color: var(--muted); cursor: pointer; user-select: none;
  }
  .folder-item .name { flex: 1; font-size: 0.88rem; padding: 2px 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .folder-item .star {
    width: 20px; height: 20px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
    cursor: pointer; font-size: 14px; color: var(--muted); user-select: none;
  }
  .folder-item .star.active { color: #fbbf24; }
  .folder-item .fav-btn { color: var(--muted); }
  .folder-children { padding-left: 16px; }
  .folder-children.hidden { display: none; }
  .folder-breadcrumb {
    display: flex; align-items: center; gap: 4px; padding: 8px 12px;
    border-bottom: 1px solid var(--border); flex-wrap: wrap;
  }
  .folder-breadcrumb span { cursor: pointer; font-size: 0.82rem; color: var(--muted); }
  .folder-breadcrumb span:hover { color: var(--accent); }
  .folder-breadcrumb .sep { color: var(--border); cursor: default; }
  .folder-breadcrumb .current { color: var(--accent); cursor: default; font-weight: 600; }

  .new-folder-input {
    display: flex; gap: 8px; padding: 8px 12px; border-top: 1px solid var(--border);
  }
  .new-folder-input input { flex: 1; padding: 6px 10px; font-size: 0.85rem; }
  .new-folder-input button {
    width: auto; padding: 6px 14px; font-size: 0.85rem; white-space: nowrap;
  }

  /* Favorites bar */
  .fav-bar {
    display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 0;
  }
  .fav-bar .fav-chip {
    background: var(--input); border: 1px solid var(--border); border-radius: 16px;
    padding: 4px 14px; font-size: 0.8rem; cursor: pointer;
    transition: all 0.15s; color: var(--text);
  }
  .fav-bar .fav-chip:hover { border-color: var(--accent); color: var(--accent); }
  .fav-bar .fav-chip.active { border-color: var(--accent); background: rgba(167,139,250,0.15); color: var(--accent); }

  /* Tags */
  .tag-selector {
    border: 1px solid var(--border); border-radius: 8px; padding: 8px;
    background: var(--input); min-height: 44px; cursor: text;
  }
  .tag-selector:focus-within { border-color: var(--accent); }
  .tag-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 4px; }
  .tag-chip {
    display: inline-flex; align-items: center; gap: 4px;
    background: rgba(167,139,250,0.15); border: 1px solid rgba(167,139,250,0.3);
    border-radius: 12px; padding: 2px 10px; font-size: 0.8rem; cursor: default;
  }
  .tag-chip .remove {
    cursor: pointer; font-size: 14px; color: var(--muted); line-height: 1;
  }
  .tag-chip .remove:hover { color: var(--error); }
  .tag-input-wrap { display: flex; flex-wrap: wrap; gap: 4px; }
  .tag-input-wrap input {
    border: none; background: transparent; color: var(--text); padding: 4px 0;
    font-size: 0.88rem; min-width: 100px; flex: 1;
  }
  .tag-input-wrap input:focus { outline: none; }
  .tag-suggestions {
    display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; max-height: 100px; overflow-y: auto;
  }
  .tag-suggestion {
    cursor: pointer; font-size: 0.78rem; padding: 2px 8px;
    border: 1px solid var(--border); border-radius: 10px; color: var(--muted);
    transition: all 0.15s;
  }
  .tag-suggestion:hover { border-color: var(--accent); color: var(--accent); }
  .tag-suggestion .cnt { color: var(--border); font-size: 0.7rem; margin-left: 2px; }

  .selected-path {
    font-size: 0.82rem; color: var(--accent); margin: 6px 0 2px; padding: 4px 8px;
    background: rgba(167,139,250,0.08); border-radius: 6px; display: inline-block;
  }

  .scrollable { max-height: 260px; overflow-y: auto; }
  .hidden { display: none !important; }
</style>
</head>
<body>
<div class="container">
  <h1>&#x2B50; Obsidian Clipper</h1>
  <div class="card">
    <form id="noteForm" onsubmit="return createNote(event)">

      <div class="field">
        <label>Folder</label>
        <div class="fav-bar" id="favBar"></div>
        <div class="folder-browser" id="folderBrowser">
          <div class="folder-breadcrumb" id="breadcrumb">
            <span class="current">/</span>
          </div>
          <div class="scrollable" id="folderList"></div>
          <div class="new-folder-input" id="newFolderRow">
            <input type="text" id="newFolderInput" placeholder="New folder name...">
            <button type="button" id="newFolderBtn">Create</button>
          </div>
        </div>
        <div class="selected-path" id="selectedPath">/</div>
        <input type="hidden" name="folder" id="folderInput" value="/">
      </div>

      <div class="field">
        <label for="title">Note Title</label>
        <input type="text" id="title" name="title" placeholder="My note title" required autofocus>
      </div>

      <div class="field">
        <label for="content">Content (Markdown)</label>
        <textarea id="content" name="content" placeholder="Write your note content here..."></textarea>
      </div>

      <div class="field">
        <label>Tags</label>
        <div class="tag-selector" id="tagSelector" onclick="document.getElementById('tagInput').focus()">
          <div class="tag-chips" id="tagChips"></div>
          <div class="tag-input-wrap">
            <input type="text" id="tagInput" placeholder="Type to search or create..." autocomplete="off">
          </div>
          <div class="tag-suggestions" id="tagSuggestions"></div>
        </div>
        <input type="hidden" name="tags" id="tagsInput" value="">
      </div>

      <div class="spinner" id="spinner"></div>
      <button type="submit" id="submitBtn">Create Note</button>
    </form>
    <div id="result"></div>
  </div>
</div>

<script>
// ---- State ----
let allFolders = [];
let favorites = [];
let selectedFolder = "/";
let allTags = [];
let selectedTags = [];
let folderTree = {};

// ---- Folder Tree ----
function buildTree(folders) {
  const tree = { name: "/", path: "/", children: {}, isDir: true };
  for (const f of folders) {
    if (f === "/") continue;
    const parts = f.replace(/^\//, "").split("/");
    let node = tree;
    for (const p of parts) {
      if (!node.children[p]) {
        node.children[p] = { name: p, path: node.path + p + "/", children: {}, isDir: true };
      }
      node = node.children[p];
    }
  }
  return tree;
}

function renderFolderList(node, depth) {
  const keys = Object.keys(node.children);
  if (keys.length === 0) return '<div style="padding:12px;text-align:center;color:var(--muted);font-size:0.85rem">Empty folder</div>';
  let html = '<div class="folder-children">';
  for (const k of keys) {
    const child = node.children[k];
    const hasKids = Object.keys(child.children).length > 0;
    const isFav = favorites.includes(child.path);
    const isSel = child.path === selectedFolder;
    const selClass = isSel ? " selected" : "";
    html += '<div class="folder-item' + selClass + '" data-path="' + child.path + '">';
    if (hasKids) {
      html += '<span class="toggle" onclick="event.stopPropagation();toggleExpand(this)">&#x25BC;</span>';
    } else {
      html += '<span class="toggle" style="cursor:default">&#xB7;</span>';
    }
    html += '<span class="name" onclick="selectFolder(\'' + child.path + '\')">' + k + "</span>";
    html += '<span class="star' + (isFav ? " active" : "") + '" onclick="event.stopPropagation();toggleFav(\'' + child.path + '\')">&#9733;</span>';
    html += "</div>";
    if (hasKids) {
      html += '<div class="folder-children" id="children-' + encodeURIComponent(child.path) + '">';
      for (const gk of Object.keys(child.children)) {
        const grand = child.children[gk];
        const gSel = grand.path === selectedFolder;
        const gFav = favorites.includes(grand.path);
        html += '<div class="folder-item' + (gSel ? " selected" : "") + '" data-path="' + grand.path + '">';
        const gHas = Object.keys(grand.children).length > 0;
        if (gHas) {
          html += '<span class="toggle" onclick="event.stopPropagation();toggleExpand(this)">&#x25BC;</span>';
        } else {
          html += '<span class="toggle" style="cursor:default">&#xB7;</span>';
        }
        html += '<span class="name" onclick="selectFolder(\'' + grand.path + '\')">' + gk + "</span>";
        html += '<span class="star' + (gFav ? " active" : "") + '" onclick="event.stopPropagation();toggleFav(\'' + grand.path + '\')">&#9733;</span>';
        html += "</div>";
      }
      html += "</div>";
    }
  }
  html += "</div>";
  return html;
}

function renderBreadcrumb(path) {
  if (path === "/") return '<span class="current">/</span>';
  const parts = path.replace(/\/$/, "").split("/").filter(Boolean);
  let html = '<span class="crumb" data-path="/">/</span>';
  let cur = "";
  for (const p of parts) {
    cur += "/" + p;
    const isLast = cur + "/" === path || cur === path;
    html += '<span class="sep"> / </span>';
    if (isLast) {
      html += '<span class="current">' + escapeHtml(p) + "</span>";
    } else {
      html += '<span class="crumb" data-path="' + cur + '/">' + escapeHtml(p) + "</span>";
    }
  }
  return html;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function toggleExpand(el) {
  const item = el.closest(".folder-item");
  if (!item) return;
  const path = item.dataset.path;
  const childDiv = document.getElementById("children-" + encodeURIComponent(path));
  if (childDiv) {
    childDiv.classList.toggle("hidden");
    el.innerHTML = childDiv.classList.contains("hidden") ? "&#x25B6;" : "&#x25BC;";
  }
}

function selectFolder(path) {
  selectedFolder = path;
  document.getElementById("folderInput").value = path;
  document.getElementById("selectedPath").textContent = path;
  updateFolderUI();
}

function updateFolderUI() {
  document.getElementById("breadcrumb").innerHTML = renderBreadcrumb(selectedFolder);
  const parts = selectedFolder.replace(/\/$/, "").split("/").filter(Boolean);
  let node = folderTree;
  for (const p of parts) {
    if (node.children && node.children[p]) {
      node = node.children[p];
    } else {
      node = null;
      break;
    }
  }
  if (node) {
    document.getElementById("folderList").innerHTML = renderFolderList(node);
  }
  renderFavBar();
}

function renderFavBar() {
  const bar = document.getElementById("favBar");
  if (favorites.length === 0) {
    bar.innerHTML = "";
    return;
  }
  let html = "";
  for (const f of favorites) {
    const active = f === selectedFolder ? " active" : "";
    const label = f === "/" ? "/ (root)" : f.replace(/\/$/, "").split("/").pop();
    html += '<span class="fav-chip' + active + '" onclick="selectFolder(\'' + f + '\')">' + label + "</span>";
  }
  bar.innerHTML = html;
}

async function toggleFav(path) {
  const idx = favorites.indexOf(path);
  if (idx >= 0) favorites.splice(idx, 1);
  else favorites.push(path);
  await savePrefs();
  updateFolderUI();
}

// ---- Tags ----
function renderTagChips() {
  const container = document.getElementById("tagChips");
  container.innerHTML = selectedTags.map(t =>
    '<span class="tag-chip">' + t + '<span class="remove" onclick="removeTag(\'' + t + '\')">&#x2715;</span></span>'
  ).join("");
  document.getElementById("tagsInput").value = selectedTags.join(", ");
}

function removeTag(t) {
  selectedTags = selectedTags.filter(x => x !== t);
  renderTagChips();
  document.getElementById("tagInput").focus();
}

function addTag(t) {
  t = t.trim().replace(/^#/, "");
  if (!t || selectedTags.includes(t)) return;
  selectedTags.push(t);
  renderTagChips();
  document.getElementById("tagInput").value = "";
  document.getElementById("tagSuggestions").innerHTML = "";
}

function showTagSuggestions(query) {
  const sug = document.getElementById("tagSuggestions");
  if (!query) {
    sug.innerHTML = allTags
      .filter(t => !selectedTags.includes(t.name))
      .slice(0, 20)
      .map(t => '<span class="tag-suggestion" onclick="addTag(\'' + t.name + '\')">#' + t.name + ' <span class="cnt">(' + t.count + ")</span></span>")
      .join("");
    return;
  }
  const q = query.toLowerCase();
  const matches = allTags.filter(t => t.name.toLowerCase().includes(q) && !selectedTags.includes(t.name));
  if (matches.length === 0) {
    sug.innerHTML = '<span class="tag-suggestion" onclick="addTag(\'' + query.replace(/'/g, "\\'") + '\')">+ Create &quot;' + query + '&quot;</span>';
    return;
  }
  sug.innerHTML = matches.slice(0, 15).map(t =>
    '<span class="tag-suggestion" onclick="addTag(\'' + t.name + '\')">#' + t.name + ' <span class="cnt">(' + t.count + ")</span></span>"
  ).join("");
}

async function saveTagsToServer(tags) {
  try {
    await fetch("/api/tags", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ tags: tags })
    });
  } catch(e) { console.error("Save tags error:", e); }
}

async function addTag(t) {
  t = t.trim().replace(/^#/, "");
  if (!t || selectedTags.includes(t)) return;
  selectedTags.push(t);
  renderTagChips();
  document.getElementById("tagInput").value = "";
  showTagSuggestions("");
  await saveTagsToServer(selectedTags);
  await loadTags();
}

function removeTag(t) {
  selectedTags = selectedTags.filter(x => x !== t);
  renderTagChips();
  showTagSuggestions("");
}

// ---- Navigation ----
async function loadFolders() {
  try {
    const r = await fetch("/api/folders");
    allFolders = await r.json();
    folderTree = buildTree(allFolders);
    updateFolderUI();
  } catch(e) { console.error("Folders error:", e); }
}

async function loadTags() {
  try {
    const r = await fetch("/api/tags");
    allTags = await r.json();
  } catch(e) { console.error("Tags error:", e); }
}

async function loadPrefs() {
  try {
    const r = await fetch("/api/preferences");
    const data = await r.json();
    if (data.favorites) favorites = data.favorites;
    if (data.lastFolder) selectedFolder = data.lastFolder;
    document.getElementById("folderInput").value = selectedFolder;
    document.getElementById("selectedPath").textContent = selectedFolder;
    renderFavBar();
  } catch(e) { console.error("Prefs error:", e); }
}

async function savePrefs() {
  try {
    await fetch("/api/preferences", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ favorites: favorites, lastFolder: selectedFolder })
    });
  } catch(e) { console.error("Save prefs error:", e); }
}

function updateSelectedPath() {
  document.getElementById("selectedPath").textContent = selectedFolder;
  document.getElementById("folderInput").value = selectedFolder;
}

// ---- New Folder ----
async function createNewFolder() {
  const input = document.getElementById("newFolderInput");
  const name = input.value.trim();
  if (!name) return;
  const path = (selectedFolder === "/" ? "/" : selectedFolder) + name;
  try {
    const r = await fetch("/api/folders", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ path: path })
    });
    if (!r.ok) throw new Error((await r.json()).detail || "Failed");
    input.value = "";
    await loadFolders();
    selectFolder(path + "/");
  } catch(e) {
    alert("Error creating folder: " + e.message);
  }
}

// ---- Create Note ----
async function createNote(e) {
  e.preventDefault();
  const btn = document.getElementById("submitBtn");
  const spinner = document.getElementById("spinner");
  const result = document.getElementById("result");
  result.style.display = "none";
  btn.disabled = true;
  spinner.classList.add("active");

  const form = new FormData(document.getElementById("noteForm"));
  try {
    const r = await fetch("/api/create", { method: "POST", body: form });
    const data = await r.json();
    if (r.ok) {
      result.className = "success";
      result.innerHTML = "<strong>Created!</strong> " + data.path;
      document.getElementById("title").value = "";
      document.getElementById("content").value = "";
      selectedTags = [];
      renderTagChips();
      await savePrefs();
    } else {
      result.className = "error";
      result.innerHTML = "<strong>Error:</strong> " + (data.detail || "Unknown error");
    }
  } catch(e) {
    result.className = "error";
    result.innerHTML = "<strong>Error:</strong> " + e.message;
  }
  result.style.display = "block";
  btn.disabled = false;
  spinner.classList.remove("active");
}

// ---- Event Handlers ----
document.addEventListener("DOMContentLoaded", function() {
  loadFolders();
  loadTags();
  loadPrefs();

  const urlParams = new URLSearchParams(window.location.search);
  const urlFolder = urlParams.get("folder");
  if (urlFolder) {
    selectedFolder = urlFolder;
    document.getElementById("folderInput").value = selectedFolder;
    document.getElementById("selectedPath").textContent = selectedFolder;
  }

  document.getElementById("breadcrumb").addEventListener("click", function(e) {
    const crumb = e.target.closest(".crumb");
    if (crumb) selectFolder(crumb.dataset.path);
  });

  document.getElementById("tagInput").addEventListener("focus", function() {
    showTagSuggestions("");
  });
  document.getElementById("tagInput").addEventListener("input", function() {
    showTagSuggestions(this.value);
  });
  document.getElementById("tagInput").addEventListener("keydown", function(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      addTag(this.value);
      this.value = "";
      document.getElementById("tagSuggestions").innerHTML = "";
    }
    if (e.key === "Backspace" && !this.value && selectedTags.length > 0) {
      selectedTags.pop();
      renderTagChips();
    }
  });

  document.getElementById("newFolderBtn").addEventListener("click", createNewFolder);
  document.getElementById("newFolderInput").addEventListener("keydown", function(e) {
    if (e.key === "Enter") { e.preventDefault(); createNewFolder(); }
  });

  document.getElementById("title").addEventListener("keydown", function(e) {
    if (e.key === "Enter" && e.ctrlKey) document.getElementById("submitBtn").click();
  });
});
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return FORM_HTML

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
async def list_tags():
    scanned = scan_tags()
    prefs = get_prefs()
    history = prefs.get("tagHistory", [])
    seen = set()
    merged = []
    for t in scanned:
        seen.add(t["name"])
        merged.append(t)
    for h in history:
        if h not in seen:
            merged.append({"name": h, "count": 0})
    return merged

@app.post("/api/tags")
async def save_tags(request: Request):
    data = await request.json()
    tags = data.get("tags", [])
    prefs = get_prefs()
    history = prefs.setdefault("tagHistory", [])
    for t in tags:
        if t not in history:
            history.append(t)
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
):
    filename = slugify(title) + ".md"
    path = f"{folder}/{filename}".replace("//", "/")

    md = f"# {title}\n\n{content}\n"
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        md += "\n" + " ".join(f"#{t}" for t in tag_list) + "\n"

    r = await api_put(path, md)

    if r.status_code in (200, 201, 204):
        if tags:
            prefs = get_prefs()
            history = prefs.setdefault("tagHistory", [])
            for t in tag_list:
                if t not in history:
                    history.append(t)
            save_prefs(prefs)
        return {"success": True, "path": path}
    else:
        detail = r.text[:200]
        try:
            detail = r.json().get("message", detail)
        except: pass
        raise HTTPException(status_code=r.status_code, detail=detail)

@app.get("/health")
async def health():
    return {"status": "ok"}
