"""
InkWell - Personal Journaling Platform
Version: 2.4.1

A lightweight, private diary and journaling web application
with session-based authentication, mood tracking, tagging,
and full CRUD operations for daily journal entries.

Usage:
  python app.py

Environment Variables:
  SERVER_PORT    - Pterodactyl assigned port (highest priority)
  PORT           - Web panel listening port (auto-assigned if not set)
  PANEL_PASSWORD - Access password for the web panel

License: MIT
"""

import os
import json
import secrets
import threading
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, redirect

# ============================================================================
# Configuration
# ============================================================================

PORT = int(os.environ.get("SERVER_PORT") or os.environ.get("PORT") or os.environ.get("PANEL_PORT") or 3000)
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "admin")
SESSION_SECRET = secrets.token_hex(32)
SESSION_TIMEOUT = timedelta(days=1)
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal.json")
APP_VERSION = "2.4.1"

# ============================================================================
# Data Store
# ============================================================================

data_lock = threading.Lock()

def load_data():
    with data_lock:
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"entries": [], "nextId": 1}

def save_data(data):
    with data_lock:
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

# ============================================================================
# Flask App Setup
# ============================================================================

app = Flask(__name__)
app.secret_key = SESSION_SECRET
app.permanent_session_lifetime = SESSION_TIMEOUT

login_attempts = {}

@app.before_request
def check_auth():
    # 放行公共路由和静态资源
    if request.path in ["/", "/api/auth/login", "/favicon.ico"]:
        return
    
    # 检查 Session
    if not session.get("authenticated"):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "Auth required"}), 401
        return redirect("/")

def esc_html(s):
    if not s: return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

# ============================================================================
# Auth Routes
# ============================================================================

@app.route("/api/auth/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    password = body.get("password")
    client_ip = request.remote_addr
    now = datetime.now()
    
    attempts = login_attempts.get(client_ip, {"count": 0, "timestamp": now})
    
    if now - attempts["timestamp"] > LOCKOUT_DURATION:
        login_attempts.pop(client_ip, None)
        attempts = {"count": 0, "timestamp": now}
    elif attempts["count"] >= MAX_LOGIN_ATTEMPTS:
        remaining = int((LOCKOUT_DURATION - (now - attempts["timestamp"])).total_seconds() / 60) + 1
        return jsonify({"success": False, "message": f"Too many attempts. Try again in {remaining} min."}), 429
        
    if password == PANEL_PASSWORD:
        session.permanent = True
        session["authenticated"] = True
        login_attempts.pop(client_ip, None)
        return jsonify({"success": True})
    else:
        attempts["count"] += 1
        attempts["timestamp"] = now
        login_attempts[client_ip] = attempts
        return jsonify({"success": False, "message": f"Invalid password. Attempts left: {MAX_LOGIN_ATTEMPTS - attempts['count']}"}), 401

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

# ============================================================================
# Entry CRUD
# ============================================================================

@app.route("/api/entries", methods=["GET"])
def get_entries():
    data = load_data()
    entries = sorted(data["entries"], key=lambda x: x["createdAt"], reverse=True)
    return jsonify({"success": True, "entries": entries})

@app.route("/api/entries", methods=["POST"])
def create_entry():
    data = load_data()
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    mood = body.get("mood") or "neutral"
    tags = body.get("tags") or []
    
    if not title or not content:
        return jsonify({"success": False, "message": "Title and content required"}), 400
        
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
        
    entry = {
        "id": data["nextId"],
        "title": title,
        "content": content,
        "mood": mood,
        "tags": tags,
        "wordCount": len(content.split()),
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat()
    }
    data["nextId"] += 1
    data["entries"].append(entry)
    save_data(data)
    return jsonify({"success": True, "entry": entry})

@app.route("/api/entries/<int:entry_id>", methods=["PUT"])
def update_entry(entry_id):
    data = load_data()
    entry = next((e for e in data["entries"] if e["id"] == entry_id), None)
    if not entry:
        return jsonify({"success": False, "message": "Entry not found"}), 404
        
    body = request.get_json(silent=True) or {}
    if "title" in body: entry["title"] = str(body["title"]).strip()
    if "content" in body:
        entry["content"] = str(body["content"]).strip()
        entry["wordCount"] = len(entry["content"].split())
    if "mood" in body: entry["mood"] = body["mood"]
    if "tags" in body:
        tags = body["tags"]
        entry["tags"] = tags if isinstance(tags, list) else [t.strip() for t in str(tags).split(",") if t.strip()]
        
    entry["updatedAt"] = datetime.now().isoformat()
    save_data(data)
    return jsonify({"success": True, "entry": entry})

@app.route("/api/entries/<int:entry_id>", methods=["DELETE"])
def delete_entry(entry_id):
    data = load_data()
    idx = next((i for i, e in enumerate(data["entries"]) if e["id"] == entry_id), -1)
    if idx == -1:
        return jsonify({"success": False, "message": "Entry not found"}), 404
        
    data["entries"].pop(idx)
    save_data(data)
    return jsonify({"success": True})

@app.route("/api/stats", methods=["GET"])
def get_stats():
    data = load_data()
    entries = data["entries"]
    total_words = sum(e.get("wordCount", 0) for e in entries)
    
    mood_counts = {}
    tag_counts = {}
    dates = []
    
    for e in entries:
        m = e.get("mood")
        mood_counts[m] = mood_counts.get(m, 0) + 1
        for t in e.get("tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
        dates.append(e["createdAt"][:10])
        
    dates.sort()
    streak = 0
    if dates:
        today = datetime.now().strftime("%Y-%m-%d")
        d = datetime.strptime(today, "%Y-%m-%d")
        while d.strftime("%Y-%m-%d") in dates:
            streak += 1
            d -= timedelta(days=1)
            
    return jsonify({
        "success": True,
        "totalEntries": len(entries),
        "totalWords": total_words,
        "streak": streak,
        "moodCounts": mood_counts,
        "tagCounts": tag_counts
    })

# ============================================================================
# Pages
# ============================================================================

@app.route("/")
def index_page():
    if session.get("authenticated"):
        return redirect("/dashboard")
    return get_login_page()

@app.route("/dashboard")
def dashboard_page():
    return get_dashboard_page()

# ============================================================================
# Login Page - Disguised as 503 Error
# ============================================================================

def get_login_page():
    ref_id = secrets.token_hex(8)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>503 Service Temporarily Unavailable</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#fff;color:#333;font-family:system-ui,-apple-system,sans-serif;font-size:14px}}
.err-wrap{{max-width:620px;margin:60px auto 0;padding:0 24px}}
.err-icon{{text-align:center;margin-bottom:20px}}
.err-icon svg{{width:56px;height:56px}}
h1{{font-size:22px;font-weight:400;color:#333;margin-bottom:6px}}
.err-sub{{color:#666;margin-bottom:24px;line-height:1.6}}
.err-sub span{{cursor:default}}
.err-hr{{border:none;border-top:1px solid #e0e0e0;margin:20px 0}}
.err-detail{{font-size:13px;color:#888;line-height:1.7}}
#login-box{{display:none;position:fixed;inset:0;z-index:999;background:linear-gradient(135deg,#020617,#0f172a);color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,sans-serif;align-items:center;justify-content:center;opacity:0;transition:opacity .4s}}
#login-box.show{{display:flex;opacity:1}}
.login-card{{background:rgba(15,23,42,.85);backdrop-filter:blur(24px);border:1px solid rgba(255,255,255,.08);border-radius:24px;padding:2.5rem;width:100%;max-width:400px;box-shadow:0 24px 80px rgba(0,0,0,.4)}}
.login-logo{{width:56px;height:56px;background:linear-gradient(135deg,#10b981,#06b6d4);border-radius:16px;display:flex;align-items:center;justify-content:center;margin:0 auto 1.2rem;font-size:24px}}
.login-title{{font-size:1.5rem;font-weight:800;text-align:center;background:linear-gradient(135deg,#34d399,#22d3ee);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:.3rem}}
.login-sub{{color:#94a3b8;font-size:.8rem;text-align:center;margin-bottom:1.8rem}}
.input-g{{margin-bottom:1rem}}
.input-g label{{display:block;color:#cbd5e1;font-size:.78rem;font-weight:500;margin-bottom:.3rem}}
.input-g input{{width:100%;padding:.8rem 1rem;background:rgba(30,41,59,.6);border:1px solid rgba(71,85,105,.5);border-radius:14px;color:#fff;font-size:.95rem;transition:border .2s}}
.input-g input:focus{{outline:none;border-color:#10b981;box-shadow:0 0 0 3px rgba(16,185,129,.15)}}
.sub-btn{{width:100%;padding:.9rem;background:linear-gradient(135deg,#10b981,#06b6d4);border:none;border-radius:14px;color:#fff;font-size:.95rem;font-weight:700;cursor:pointer;transition:transform .15s}}
.sub-btn:hover{{transform:translateY(-2px)}}
.sub-btn:active{{transform:scale(.97)}}
.err-msg{{color:#f87171;font-size:.82rem;text-align:center;min-height:1.1rem;margin-top:.5rem}}
</style></head><body>
<div class="err-wrap">
<div class="err-icon"><svg viewBox="0 0 56 56" fill="none"><circle cx="28" cy="28" r="26" stroke="#d93025" stroke-width="2.5"/><path d="M18 18L38 38M38 18L18 38" stroke="#d93025" stroke-width="2.5" stroke-linecap="round"/></svg></div>
<h1>503 Service Temporarily Unavailable</h1>
<p class="err-sub">The server is currently unable to handle this request. Please try again later<span onclick="revealLogin()">.</span></p>
<hr class="err-hr">
<div class="err-detail">
<p>nginx/1.24.0</p>
<p>Reference ID: {ref_id}</p>
</div></div>
<div id="login-box">
<div class="login-card">
<div class="login-logo">✎</div>
<h2 class="login-title">InkWell</h2>
<p class="login-sub">Personal Journaling Platform</p>
<form id="loginForm" onsubmit="return handleLogin(event)">
<div class="input-g"><label>Password</label><input type="password" id="pw" placeholder="Enter password" required autocomplete="off"></div>
<button type="submit" class="sub-btn">Unlock</button>
<div id="errMsg" class="err-msg"></div>
</form></div></div>
<script>
function revealLogin(){{var b=document.getElementById("login-box");b.classList.add("show");setTimeout(function(){{document.getElementById("pw").focus()}},300)}}
function handleLogin(e){{e.preventDefault();var p=document.getElementById("pw").value.trim();if(!p){{document.getElementById("errMsg").textContent="Password required";return false}}
fetch("/api/auth/login",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{password:p}})}}).then(function(r){{return r.json()}}).then(function(d){{if(d.success){{window.location.href="/dashboard"}}else{{document.getElementById("errMsg").textContent=d.message||"Failed";document.getElementById("pw").value=""}}}}).catch(function(){{document.getElementById("errMsg").textContent="Network error"}});return false}}
</script></body></html>"""

# ============================================================================
# Dashboard Page
# ============================================================================

def get_dashboard_page():
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>InkWell</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
body{{background:#020617;color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;min-height:100vh}}
.glass{{background:rgba(15,23,42,.7);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.05)}}
input,textarea,select{{background:#0f172a!important;border:1px solid #1e293b!important;color:#fff!important;outline:none!important}}
input:focus,textarea:focus{{border-color:#10b981!important;box-shadow:0 0 0 2px rgba(16,185,129,.15)!important}}
.btn{{transition:all .15s;cursor:pointer;user-select:none}}
.btn:hover{{transform:translateY(-1px);filter:brightness(1.1)}}
.btn:active{{transform:scale(.97)}}
::-webkit-scrollbar{{width:5px}}::-webkit-scrollbar-track{{background:rgba(0,0,0,.2)}}::-webkit-scrollbar-thumb{{background:rgba(255,255,255,.1);border-radius:4px}}
.entry-item{{transition:all .15s;cursor:pointer}}.entry-item:hover{{background:rgba(16,185,129,.08)}}
.entry-item.active{{background:rgba(16,185,129,.12);border-left:3px solid #10b981}}
.mood-happy{{color:#fbbf24}}.mood-neutral{{color:#94a3b8}}.mood-sad{{color:#60a5fa}}.mood-excited{{color:#f472b6}}.mood-grateful{{color:#a78bfa}}
.modal-bg{{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px)}}
.tag{{display:inline-block;font-size:10px;padding:2px 8px;border-radius:9999px;background:rgba(16,185,129,.1);color:#34d399;border:1px solid rgba(16,185,129,.2);margin:2px}}
</style></head><body class="flex flex-col h-screen overflow-hidden">

<header class="glass flex items-center justify-between px-5 py-3 border-b border-slate-800 shrink-0">
<div class="flex items-center gap-3">
<div class="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-cyan-500 flex items-center justify-center text-sm">✎</div>
<h1 class="text-lg font-black bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text" style="-webkit-text-fill-color:transparent">InkWell</h1>
<span class="text-[10px] text-slate-600">v{APP_VERSION}</span>
</div>
<div class="flex items-center gap-3">
<input id="searchInput" placeholder="Search entries..." class="rounded-xl px-3 py-1.5 text-sm w-48" oninput="searchEntries(this.value)">
<button onclick="openCompose()" class="btn bg-emerald-600 hover:bg-emerald-500 px-4 py-1.5 rounded-xl text-sm font-bold text-white"><i class="fas fa-plus mr-1"></i>New</button>
<button onclick="showStats()" class="btn bg-slate-800 hover:bg-slate-700 px-3 py-1.5 rounded-xl text-sm text-slate-300"><i class="fas fa-chart-bar"></i></button>
<button onclick="logout()" class="btn bg-red-600 hover:bg-red-500 px-3 py-1.5 rounded-xl text-sm font-bold text-white"><i class="fas fa-sign-out-alt"></i></button>
</div></header>

<div class="flex flex-1 overflow-hidden">
<div class="w-72 shrink-0 border-r border-slate-800 flex flex-col bg-slate-950/50">
<div id="entryList" class="flex-1 overflow-y-auto p-2 space-y-1"></div>
<div class="p-3 border-t border-slate-800">
<div id="tagFilter" class="flex flex-wrap gap-1"></div>
</div></div>

<div class="flex-1 overflow-y-auto p-6">
<div id="emptyView" class="flex flex-col items-center justify-center h-full text-slate-600">
<i class="fas fa-feather-pointed text-5xl mb-4 opacity-20"></i>
<p class="text-lg font-medium">Select an entry or create a new one</p>
</div>
<div id="entryView" class="hidden max-w-3xl mx-auto"></div>
</div></div>

<div id="composeModal" class="modal-bg hidden">
<div class="glass rounded-2xl p-6 w-full max-w-2xl mx-4 shadow-2xl">
<div class="flex justify-between items-center mb-4">
<h3 id="composeTitle" class="text-lg font-bold text-white"><i class="fas fa-pen-fancy text-emerald-400 mr-2"></i>New Entry</h3>
<button onclick="closeCompose()" class="text-slate-400 hover:text-white text-xl">&times;</button>
</div>
<input id="cTitle" type="text" placeholder="Entry title..." class="w-full rounded-xl px-4 py-2.5 text-sm mb-3">
<textarea id="cContent" rows="10" placeholder="Write your thoughts..." class="w-full rounded-xl px-4 py-3 text-sm mb-3 resize-none"></textarea>
<div class="flex gap-3 mb-3">
<div class="flex-1"><label class="block text-xs text-slate-400 mb-1">Mood</label>
<select id="cMood" class="w-full rounded-xl px-3 py-2 text-sm">
<option value="happy">☺ Happy</option><option value="neutral" selected>○ Neutral</option><option value="sad">☹ Sad</option><option value="excited">★ Excited</option><option value="grateful">❤ Grateful</option>
</select></div>
<div class="flex-1"><label class="block text-xs text-slate-400 mb-1">Tags (comma separated)</label>
<input id="cTags" type="text" placeholder="life, thoughts..." class="w-full rounded-xl px-3 py-2 text-sm">
</div></div>
<input id="cEditId" type="hidden" value="">
<button onclick="saveEntry()" class="btn w-full bg-emerald-600 hover:bg-emerald-500 py-2.5 rounded-xl text-sm font-bold text-white"><i class="fas fa-save mr-1"></i>Save</button>
</div></div>

<div id="statsModal" class="modal-bg hidden">
<div class="glass rounded-2xl p-6 w-full max-w-md mx-4 shadow-2xl">
<div class="flex justify-between items-center mb-4">
<h3 class="text-lg font-bold text-white"><i class="fas fa-chart-bar text-cyan-400 mr-2"></i>Journal Stats</h3>
<button onclick="document.getElementById('statsModal').classList.add('hidden')" class="text-slate-400 hover:text-white text-xl">&times;</button>
</div>
<div id="statsContent"></div>
</div></div>

<div class="fixed bottom-4 left-4 glass rounded-full px-5 py-3 flex items-center gap-5 z-50 shadow-2xl">
<div class="flex flex-col items-center"><span id="statEntries" class="text-sm font-black text-emerald-400">0</span><span class="text-[8px] font-bold text-slate-500 uppercase">Entries</span></div>
<div class="flex flex-col items-center"><span id="statWords" class="text-sm font-black text-cyan-400">0</span><span class="text-[8px] font-bold text-slate-500 uppercase">Words</span></div>
<div class="flex flex-col items-center"><span id="statStreak" class="text-sm font-black text-purple-400">0</span><span class="text-[8px] font-bold text-slate-500 uppercase">Streak</span></div>
</div>

<script>
var allEntries=[];var currentId=null;var activeTag=null;
function esc(s){{if(!s)return"";return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}}
function moodIcon(m){{var map={{happy:"☺",neutral:"○",sad:"☹",excited:"★",grateful:"❤"}};return map[m]||"○"}}
function moodCls(m){{return"mood-"+(m||"neutral")}}
function fmtDate(d){{if(!d)return"";var dt=new Date(d);var months=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];return months[dt.getMonth()]+" "+dt.getDate()+", "+dt.getFullYear()}}
function fmtTime(d){{if(!d)return"";var dt=new Date(d);var h=dt.getHours();var m=dt.getMinutes();var ampm=h>=12?"PM":"AM";h=h%12||12;return h+":"+(m<10?"0":"")+m+" "+ampm}}

async function api(method,url,body){{var opts={{method,headers:{{"Content-Type":"application/json"}}}};if(body)opts.body=JSON.stringify(body);try{{var r=await fetch(url,opts);return await r.json()}}catch(e){{return{{success:false,message:e.message}}}}}}

async function loadEntries(){{var d=await api("GET","/api/entries");if(!d.success)return;allEntries=d.entries||[];renderList();updateStats();}}

function renderList(filter){{var list=document.getElementById("entryList");var filtered=allEntries;if(activeTag){{filtered=filtered.filter(function(e){{return(e.tags||[]).indexOf(activeTag)!==-1}})}}if(filter){{var q=filter.toLowerCase();filtered=filtered.filter(function(e){{return e.title.toLowerCase().indexOf(q)!==-1||e.content.toLowerCase().indexOf(q)!==-1}})}}
var html="";if(filtered.length===0){{html='<div class="text-center text-slate-600 text-xs py-8">No entries found</div>'}}
filtered.forEach(function(e){{var cls="entry-item rounded-xl p-3"+(e.id===currentId?" active":"");
html+='<div class="'+cls+'" onclick="viewEntry('+e.id+')">';
html+='<div class="flex items-center gap-2 mb-1"><span class="text-sm '+moodCls(e.mood)+'">'+moodIcon(e.mood)+'</span><span class="text-sm font-bold text-white truncate">'+esc(e.title)+'</span></div>';
html+='<div class="text-[10px] text-slate-500">'+fmtDate(e.createdAt)+'</div>';
if(e.tags&&e.tags.length>0){{html+='<div class="mt-1">'+e.tags.slice(0,3).map(function(t){{return'<span class="tag">'+esc(t)+'</span>'}}).join("")+'</div>'}}
html+='</div>'}});
list.innerHTML=html;}}

function renderTags(){{var tags={{}};allEntries.forEach(function(e){{(e.tags||[]).forEach(function(t){{tags[t]=(tags[t]||0)+1}})}});var el=document.getElementById("tagFilter");var html="";Object.keys(tags).sort(function(a,b){{return tags[b]-tags[a]}}).slice(0,10).forEach(function(t){{var cls=activeTag===t?"bg-emerald-600 text-white":"bg-slate-800 text-slate-400 cursor-pointer hover:bg-slate-700";html+='<span class="tag '+cls+'" onclick="toggleTag(\\''+esc(t)+'\\')">'+esc(t)+' ('+tags[t]+')</span>'}});if(activeTag){{html+='<span class="tag bg-red-900 text-red-300 cursor-pointer" onclick="toggleTag(null)">Clear</span>'}}el.innerHTML=html;}}

function toggleTag(t){{activeTag=activeTag===t?null:t;renderList();renderTags();}}

async function viewEntry(id){{currentId=id;var d=await api("GET","/api/entries");if(!d.success)return;var e=(d.entries||[]).find(function(x){{return x.id===id}});if(!e)return;
document.getElementById("emptyView").classList.add("hidden");var v=document.getElementById("entryView");v.classList.remove("hidden");
var html='<div class="glass rounded-2xl p-6 shadow-2xl">';
html+='<div class="flex justify-between items-start mb-4">';
html+='<div><h2 class="text-xl font-black text-white">'+esc(e.title)+'</h2>';
html+='<div class="flex items-center gap-3 mt-1 text-xs text-slate-400">';
html+='<span>'+fmtDate(e.createdAt)+' at '+fmtTime(e.createdAt)+'</span>';
html+='<span class="'+moodCls(e.mood)+'">'+moodIcon(e.mood)+' '+esc(e.mood)+'</span>';
html+='<span>'+e.wordCount+' words</span></div></div>';
html+='<div class="flex gap-2">';
html+='<button onclick="editEntry('+e.id+')" class="btn bg-blue-600 hover:bg-blue-500 px-3 py-1.5 rounded-lg text-xs font-bold text-white"><i class="fas fa-edit mr-1"></i>Edit</button>';
html+='<button onclick="deleteEntry('+e.id+')" class="btn bg-red-600 hover:bg-red-500 px-3 py-1.5 rounded-lg text-xs font-bold text-white"><i class="fas fa-trash mr-1"></i>Delete</button>';
html+='</div></div>';
if(e.tags&&e.tags.length>0){{html+='<div class="mb-4">'+e.tags.map(function(t){{return'<span class="tag">'+esc(t)+'</span>'}}).join("")+'</div>'}}
html+='<div class="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">'+esc(e.content)+'</div>';
html+='</div>';
v.innerHTML=html;renderList();renderTags();}}

function openCompose(editId,title,content,mood,tags){{document.getElementById("composeModal").classList.remove("hidden");document.getElementById("cEditId").value=editId||"";document.getElementById("cTitle").value=title||"";document.getElementById("cContent").value=content||"";document.getElementById("cMood").value=mood||"neutral";document.getElementById("cTags").value=tags||"";document.getElementById("composeTitle").innerHTML=editId?'<i class="fas fa-edit text-blue-400 mr-2"></i>Edit Entry':'<i class="fas fa-pen-fancy text-emerald-400 mr-2"></i>New Entry';document.getElementById("cTitle").focus();}}
function closeCompose(){{document.getElementById("composeModal").classList.add("hidden")}}

async function editEntry(id){{var d=await api("GET","/api/entries");if(!d.success)return;var e=(d.entries||[]).find(function(x){{return x.id===id}});if(!e)return;openCompose(e.id,e.title,e.content,e.mood,(e.tags||[]).join(", "));}}

async function saveEntry(){{var editId=document.getElementById("cEditId").value;var title=document.getElementById("cTitle").value.trim();var content=document.getElementById("cContent").value.trim();var mood=document.getElementById("cMood").value;var tags=document.getElementById("cTags").value.split(",").map(function(t){{return t.trim()}}).filter(Boolean);if(!title||!content){{alert("Title and content are required");return}}
var d;if(editId){{d=await api("PUT","/api/entries/"+editId,{{title:title,content:content,mood:mood,tags:tags}})}}else{{d=await api("POST","/api/entries",{{title:title,content:content,mood:mood,tags:tags}})}}
if(d.success){{closeCompose();loadEntries();if(d.entry)viewEntry(d.entry.id)}}else{{alert(d.message||"Save failed")}}}}

async function deleteEntry(id){{if(!confirm("Delete this entry permanently?"))return;var d=await api("DELETE","/api/entries/"+id);if(d.success){{currentId=null;document.getElementById("entryView").classList.add("hidden");document.getElementById("emptyView").classList.remove("hidden");loadEntries()}}else{{alert(d.message)}}}}

function searchEntries(q){{renderList(q)}}

async function updateStats(){{var d=await api("GET","/api/stats");if(!d.success)return;document.getElementById("statEntries").textContent=d.totalEntries||0;document.getElementById("statWords").textContent=d.totalWords||0;document.getElementById("statStreak").textContent=d.streak||0;}}

async function showStats(){{var d=await api("GET","/api/stats");if(!d.success)return;var html="";html+='<div class="grid grid-cols-3 gap-3 mb-4">';html+='<div class="text-center p-3 bg-slate-900 rounded-xl"><div class="text-2xl font-black text-emerald-400">'+(d.totalEntries||0)+'</div><div class="text-[10px] text-slate-500 uppercase">Entries</div></div>';html+='<div class="text-center p-3 bg-slate-900 rounded-xl"><div class="text-2xl font-black text-cyan-400">'+(d.totalWords||0)+'</div><div class="text-[10px] text-slate-500 uppercase">Words</div></div>';html+='<div class="text-center p-3 bg-slate-900 rounded-xl"><div class="text-2xl font-black text-purple-400">'+(d.streak||0)+'</div><div class="text-[10px] text-slate-500 uppercase">Day Streak</div></div>';html+='</div>';
var mc=d.moodCounts||{{}};if(Object.keys(mc).length>0){{html+='<div class="mb-3"><div class="text-xs text-slate-400 mb-2 font-bold">Mood Distribution</div>';var maxMood=Math.max.apply(null,Object.values(mc));Object.keys(mc).forEach(function(m){{var pct=Math.round(mc[m]/maxMood*100);html+='<div class="flex items-center gap-2 mb-1"><span class="text-xs w-16 '+moodCls(m)+'">'+moodIcon(m)+' '+m+'</span><div class="flex-1 bg-slate-800 rounded-full h-2"><div class="bg-emerald-500 h-2 rounded-full" style="width:'+pct+'%"></div></div><span class="text-[10px] text-slate-500">'+mc[m]+'</span></div>'}});html+='</div>'}}
var tc=d.tagCounts||{{}};var topTags=Object.entries(tc).sort(function(a,b){{return b[1]-a[1]}}).slice(0,8);if(topTags.length>0){{html+='<div><div class="text-xs text-slate-400 mb-2 font-bold">Top Tags</div><div class="flex flex-wrap gap-1">';topTags.forEach(function(t){{html+='<span class="tag">'+esc(t[0])+' ('+t[1]+')</span>'}});html+='</div></div>'}}
document.getElementById("statsContent").innerHTML=html;document.getElementById("statsModal").classList.remove("hidden")}}

async function logout(){{var d=await api("POST","/api/auth/logout");if(d.success)window.location.href="/";}}

loadEntries();
</script></body></html>"""

# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    print(f"Starting InkWell v{APP_VERSION} on port {PORT}...")
    # 禁用 Flask 默认的请求日志以保持终端整洁（可选）
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    app.run(host="0.0.0.0", port=PORT, debug=False)
