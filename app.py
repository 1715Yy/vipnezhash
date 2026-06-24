"""
InkWell - Personal Journaling Platform
Version: 2.4.1

A lightweight, private diary and journaling web application
with session-based authentication, mood tracking,
tagging, and full CRUD operations for daily journal entries.

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
from urllib.parse import urlparse, parse_qs
import re
from io import StringIO
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

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
# Session Management
# ============================================================================

sessions = {}
login_attempts = {}

def generate_session_id():
    return secrets.token_urlsafe(32)

def validate_session(session_id):
    if session_id in sessions:
        session_data = sessions[session_id]
        if datetime.now() - session_data['created_at'] < SESSION_TIMEOUT:
            return True
        else:
            del sessions[session_id]
    return False

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
# Custom HTTP Request Handler
# ============================================================================

class JournalRequestHandler(BaseHTTPRequestHandler):
    
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        query_params = parse_qs(parsed_path.query)
        
        # Extract session ID from cookies
        session_id = None
        cookie_header = self.headers.get('Cookie')
        if cookie_header:
            cookies = {}
            for cookie in cookie_header.split(';'):
                if '=' in cookie:
                    key, value = cookie.strip().split('=', 1)
                    cookies[key] = value
            session_id = cookies.get('session_id')
        
        # Check authentication for protected routes
        requires_auth = path not in ['/', '/api/auth/login']
        if requires_auth and not validate_session(session_id):
            if path.startswith('/api/'):
                self.send_error_response(401, {"success": False, "message": "Auth required"})
                return
            else:
                self.handle_login_page()
                return
        
        if path == '/':
            self.handle_index()
        elif path == '/dashboard':
            self.handle_dashboard()
        elif path == '/api/entries':
            self.handle_get_entries()
        elif path == '/api/stats':
            self.handle_get_stats()
        else:
            self.send_error(404)
    
    def do_POST(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        # Extract session ID from cookies
        session_id = None
        cookie_header = self.headers.get('Cookie')
        if cookie_header:
            cookies = {}
            for cookie in cookie_header.split(';'):
                if '=' in cookie:
                    key, value = cookie.strip().split('=', 1)
                    cookies[key] = value
            session_id = cookies.get('session_id')
        
        # Check authentication for protected routes
        requires_auth = path not in ['/api/auth/login']
        if requires_auth and not validate_session(session_id):
            self.send_error_response(401, {"success": False, "message": "Auth required"})
            return
        
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        if path == '/api/auth/login':
            self.handle_login(post_data)
        elif path == '/api/auth/logout':
            self.handle_logout()
        elif path == '/api/entries':
            self.handle_create_entry(post_data)
        elif path.startswith('/api/entries/'):
            self.handle_entry_operations(path, post_data)
        else:
            self.send_error(404)
    
    def do_PUT(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        # Extract session ID from cookies
        session_id = None
        cookie_header = self.headers.get('Cookie')
        if cookie_header:
            cookies = {}
            for cookie in cookie_header.split(';'):
                if '=' in cookie:
                    key, value = cookie.strip().split('=', 1)
                    cookies[key] = value
            session_id = cookies.get('session_id')
        
        if not validate_session(session_id):
            self.send_error_response(401, {"success": False, "message": "Auth required"})
            return
        
        content_length = int(self.headers.get('Content-Length', 0))
        put_data = self.rfile.read(content_length).decode('utf-8')
        
        if path.startswith('/api/entries/'):
            self.handle_update_entry(path, put_data)
        else:
            self.send_error(404)
    
    def do_DELETE(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        # Extract session ID from cookies
        session_id = None
        cookie_header = self.headers.get('Cookie')
        if cookie_header:
            cookies = {}
            for cookie in cookie_header.split(';'):
                if '=' in cookie:
                    key, value = cookie.strip().split('=', 1)
                    cookies[key] = value
            session_id = cookies.get('session_id')
        
        if not validate_session(session_id):
            self.send_error_response(401, {"success": False, "message": "Auth required"})
            return
        
        if path.startswith('/api/entries/'):
            self.handle_delete_entry(path)
        else:
            self.send_error(404)
    
    def send_json_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def send_error_response(self, status_code, message):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(message).encode('utf-8'))
    
    def handle_login_page(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        ref_id = secrets.token_hex(8)
        html_content = f"""<!DOCTYPE html>
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
.login-card{{background:rgba(15,23,42,.85);backdrop-filter:blur(24px);border:1px solid rgba(255,255,255,.08);border-radius:16px;width:100%;max-width:420px;padding:32px;margin:20px}}
.login-title{{font-size:24px;font-weight:600;margin-bottom:24px;text-align:center}}
.login-form{{display:flex;flex-direction:column;gap:16px}}
.form-group{{display:flex;flex-direction:column;gap:6px}}
.form-label{{font-size:14px;font-weight:500;color:#e2e8f0}}
.form-input{{padding:12px 16px;border:1px solid rgba(255,255,255,.1);border-radius:8px;background:rgba(30,41,59,.5);color:#f8fafc;font-size:16px;outline:none;transition:border-color .2s}}
.form-input:focus{{border-color:#60a5fa}}
.form-input::placeholder{{color:#94a3b8}}
.btn{{padding:12px 16px;background:#3b82f6;color:white;border:none;border-radius:8px;font-size:16px;font-weight:500;cursor:pointer;transition:background-color .2s}}
.btn:hover{{background:#2563eb}}
.btn:disabled{{background:#4b5563;cursor:not-allowed}}
.alert{{padding:12px 16px;border-radius:8px;font-size:14px;text-align:center;display:none}}
.alert.error{{background:#fee2e2;color:#dc2626;border:1px solid #fecaca}}
.alert.success{{background:#d1fae5;color:#065f46;border:1px solid #a7f3d0}}
@media (max-width:768px){{.err-wrap{{margin-top:30px}}}}
</style>
</head><body>
<div class="err-wrap">
<div class="err-icon">
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 7V12L15 15M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="#ea4335" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path></svg>
</div>
<h1>503 Service Temporarily Unavailable</h1>
<p class="err-sub">The server is temporarily unable to service your request due to maintenance downtime or capacity problems. Please try again later.</p>
<div class="err-hr"></div>
<p class="err-detail">Reference: {ref_id}</p>
</div>

<div id="login-box">
<div class="login-card">
<div class="login-title">Access Dashboard</div>
<form class="login-form" id="loginForm">
<div class="form-group">
<label class="form-label">Password</label>
<input type="password" class="form-input" id="passwordInput" placeholder="Enter access password" autocomplete="off">
</div>
<button type="submit" class="btn" id="loginBtn">Sign In</button>
<div class="alert error" id="errorMsg"></div>
</form>
</div>
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {{
    document.getElementById('loginForm').addEventListener('submit', async function(e) {{
        e.preventDefault();
        const password = document.getElementById('passwordInput').value;
        const btn = document.getElementById('loginBtn');
        const errorMsg = document.getElementById('errorMsg');
        
        btn.disabled = true;
        btn.textContent = 'Signing in...';
        errorMsg.style.display = 'none';
        
        try {{
            const response = await fetch('/api/auth/login', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{password}})
            }});
            
            const result = await response.json();
            
            if (result.success) {{
                window.location.href = '/dashboard';
            }} else {{
                errorMsg.textContent = result.message || 'Login failed';
                errorMsg.style.display = 'block';
            }}
        }} catch (error) {{
            errorMsg.textContent = 'Network error. Please try again.';
            errorMsg.style.display = 'block';
        }} finally {{
            btn.disabled = false;
            btn.textContent = 'Sign In';
        }}
    }});
    
    // Show login box after a short delay
    setTimeout(() => {{
        document.getElementById('login-box').classList.add('show');
    }}, 100);
}});
</script>
</body></html>"""
        self.wfile.write(html_content.encode('utf-8'))
    
    def handle_index(self):
        self.send_response(302)
        self.send_header('Location', '/dashboard')
        self.end_headers()
    
    def handle_dashboard(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>InkWell - Personal Journal</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background-color: #f8fafc; color: #1e293b; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { display: flex; justify-content: space-between; align-items: center; padding: 20px 0; border-bottom: 1px solid #e2e8f0; margin-bottom: 30px; }
        .header-left { display: flex; align-items: center; gap: 15px; }
        .logo { font-size: 24px; font-weight: bold; color: #0f172a; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }
        .stat-card { background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .stat-value { font-size: 28px; font-weight: bold; color: #0f172a; }
        .stat-label { color: #64748b; margin-top: 5px; }
        .entries-section { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; }
        .entries-list { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }
        .entry-item { padding: 15px; border-bottom: 1px solid #e2e8f0; cursor: pointer; transition: background-color 0.2s; }
        .entry-item:last-child { border-bottom: none; }
        .entry-item:hover { background-color: #f1f5f9; }
        .entry-title { font-weight: 600; margin-bottom: 5px; }
        .entry-date { font-size: 12px; color: #64748b; }
        .entry-preview { font-size: 14px; color: #475569; margin-top: 5px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
        .entry-form { background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .form-group { margin-bottom: 20px; }
        .form-label { display: block; margin-bottom: 8px; font-weight: 500; }
        .form-input, .form-textarea, .form-select { width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 16px; }
        .form-textarea { height: 200px; resize: vertical; }
        .form-row { display: flex; gap: 15px; }
        .form-row .form-group { flex: 1; }
        .btn { background-color: #3b82f6; color: white; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; font-size: 16px; }
        .btn:hover { background-color: #2563eb; }
        .btn-secondary { background-color: #64748b; }
        .btn-secondary:hover { background-color: #475569; }
        .actions { display: flex; gap: 10px; margin-top: 20px; }
        .logout-btn { background-color: #ef4444; }
        .logout-btn:hover { background-color: #dc2626; }
        @media (max-width: 768px) {
            .entries-section { grid-template-columns: 1fr; }
            .form-row { flex-direction: column; gap: 0; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-left">
                <div class="logo">InkWell</div>
                <div>v""" + APP_VERSION + """</div>
            </div>
            <button class="btn logout-btn" onclick="handleLogout()">Logout</button>
        </header>
        
        <div class="stats" id="statsContainer">
            <div class="stat-card">
                <div class="stat-value" id="totalEntries">0</div>
                <div class="stat-label">Total Entries</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="totalWords">0</div>
                <div class="stat-label">Total Words</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="streak">0</div>
                <div class="stat-label">Day Streak</div>
            </div>
        </div>
        
        <div class="entries-section">
            <div class="entries-list" id="entriesList">
                <!-- Entries will be loaded here -->
            </div>
            
            <div class="entry-form">
                <h2 id="formTitle">New Entry</h2>
                <form id="entryForm">
                    <input type="hidden" id="entryId">
                    <div class="form-group">
                        <label class="form-label">Title</label>
                        <input type="text" class="form-input" id="entryTitle" placeholder="Entry title" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Content</label>
                        <textarea class="form-textarea" id="entryContent" placeholder="Write your thoughts here..." required></textarea>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Mood</label>
                            <select class="form-select" id="entryMood">
                                <option value="happy">😊 Happy</option>
                                <option value="sad">😢 Sad</option>
                                <option value="excited">🤩 Excited</option>
                                <option value="calm">😌 Calm</option>
                                <option value="anxious">😰 Anxious</option>
                                <option value="neutral" selected>😐 Neutral</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Tags (comma separated)</label>
                            <input type="text" class="form-input" id="entryTags" placeholder="work, personal, goals">
                        </div>
                    </div>
                    <div class="actions">
                        <button type="submit" class="btn">Save Entry</button>
                        <button type="button" class="btn btn-secondary" id="cancelEdit">Cancel</button>
                        <button type="button" class="btn logout-btn" id="deleteEntry" style="display: none;">Delete</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <script>
        let currentEntry = null;
        
        document.addEventListener('DOMContentLoaded', function() {
            loadStats();
            loadEntries();
            
            document.getElementById('entryForm').addEventListener('submit', handleSaveEntry);
            document.getElementById('cancelEdit').addEventListener('click', resetForm);
            document.getElementById('deleteEntry').addEventListener('click', handleDeleteEntry);
        });
        
        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('totalEntries').textContent = data.totalEntries;
                    document.getElementById('totalWords').textContent = data.totalWords.toLocaleString();
                    document.getElementById('streak').textContent = data.streak;
                }
            } catch (error) {
                console.error('Error loading stats:', error);
            }
        }
        
        async function loadEntries() {
            try {
                const response = await fetch('/api/entries');
                const data = await response.json();
                
                if (data.success) {
                    const container = document.getElementById('entriesList');
                    container.innerHTML = '';
                    
                    if (data.entries.length === 0) {
                        container.innerHTML = '<div class="entry-item">No entries yet. Create your first entry!</div>';
                        return;
                    }
                    
                    data.entries.forEach(entry => {
                        const div = document.createElement('div');
                        div.className = 'entry-item';
                        div.innerHTML = `
                            <div class="entry-title">${escapeHtml(entry.title)}</div>
                            <div class="entry-date">${new Date(entry.createdAt).toLocaleDateString()}</div>
                            <div class="entry-preview">${escapeHtml(entry.content.substring(0, 100))}${entry.content.length > 100 ? '...' : ''}</div>
                        `;
                        div.addEventListener('click', () => editEntry(entry));
                        container.appendChild(div);
                    });
                }
            } catch (error) {
                console.error('Error loading entries:', error);
            }
        }
        
        function editEntry(entry) {
            currentEntry = entry;
            document.getElementById('formTitle').textContent = 'Edit Entry';
            document.getElementById('entryId').value = entry.id;
            document.getElementById('entryTitle').value = entry.title;
            document.getElementById('entryContent').value = entry.content;
            document.getElementById('entryMood').value = entry.mood;
            document.getElementById('entryTags').value = entry.tags.join(', ');
            document.getElementById('deleteEntry').style.display = 'inline-block';
        }
        
        function resetForm() {
            document.getElementById('formTitle').textContent = 'New Entry';
            document.getElementById('entryForm').reset();
            document.getElementById('entryId').value = '';
            document.getElementById('deleteEntry').style.display = 'none';
            currentEntry = null;
        }
        
        async function handleSaveEntry(e) {
            e.preventDefault();
            
            const id = document.getElementById('entryId').value;
            const title = document.getElementById('entryTitle').value.trim();
            const content = document.getElementById('entryContent').value.trim();
            const mood = document.getElementById('entryMood').value;
            const tags = document.getElementById('entryTags').value
                .split(',')
                .map(tag => tag.trim())
                .filter(tag => tag !== '');
            
            if (!title || !content) {
                alert('Title and content are required');
                return;
            }
            
            const entryData = { title, content, mood, tags };
            
            try {
                let response;
                if (id) {
                    // Update existing entry
                    response = await fetch(`/api/entries/${id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(entryData)
                    });
                } else {
                    // Create new entry
                    response = await fetch('/api/entries', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(entryData)
                    });
                }
                
                const result = await response.json();
                
                if (result.success) {
                    resetForm();
                    loadEntries();
                    loadStats();
                } else {
                    alert(result.message || 'Error saving entry');
                }
            } catch (error) {
                console.error('Error saving entry:', error);
                alert('Network error. Please try again.');
            }
        }
        
        async function handleDeleteEntry() {
            if (!currentEntry) return;
            
            if (!confirm('Are you sure you want to delete this entry?')) {
                return;
            }
            
            try {
                const response = await fetch(`/api/entries/${currentEntry.id}`, {
                    method: 'DELETE'
                });
                
                const result = await response.json();
                
                if (result.success) {
                    resetForm();
                    loadEntries();
                    loadStats();
                } else {
                    alert(result.message || 'Error deleting entry');
                }
            } catch (error) {
                console.error('Error deleting entry:', error);
                alert('Network error. Please try again.');
            }
        }
        
        async function handleLogout() {
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
                window.location.href = '/';
            } catch (error) {
                window.location.href = '/';
            }
        }
        
        function escapeHtml(text) {
            const map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, m => map[m]);
        }
    </script>
</body>
</html>"""
        self.wfile.write(html_content.encode('utf-8'))
    
    def handle_login(self, post_data):
        try:
            data = json.loads(post_data)
            password = data.get('password', '')
            client_ip = self.client_address[0]
            now = datetime.now()
            
            attempts = login_attempts.get(client_ip, {"count": 0, "timestamp": now})
            
            if now - attempts["timestamp"] > LOCKOUT_DURATION:
                login_attempts.pop(client_ip, None)
                attempts = {"count": 0, "timestamp": now}
            elif attempts["count"] >= MAX_LOGIN_ATTEMPTS:
                remaining = int((LOCKOUT_DURATION - (now - attempts["timestamp"])).total_seconds() / 60) + 1
                self.send_error_response(429, {"success": False, "message": f"Too many attempts. Try again in {remaining} min."})
                return
                
            if password == PANEL_PASSWORD:
                session_id = generate_session_id()
                sessions[session_id] = {
                    'authenticated': True,
                    'created_at': datetime.now()
                }
                
                self.send_response(200)
                self.send_header('Set-Cookie', f'session_id={session_id}; Path=/; HttpOnly; SameSite=Strict')
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                
                login_attempts.pop(client_ip, None)
            else:
                attempts["count"] += 1
                attempts["timestamp"] = now
                login_attempts[client_ip] = attempts
                remaining_attempts = MAX_LOGIN_ATTEMPTS - attempts['count']
                self.send_error_response(401, {"success": False, "message": f"Invalid password. Attempts left: {remaining_attempts}"})
        except Exception as e:
            self.send_error_response(400, {"success": False, "message": "Invalid request"})
    
    def handle_logout(self):
        cookie_header = self.headers.get('Cookie')
        if cookie_header:
            cookies = {}
            for cookie in cookie_header.split(';'):
                if '=' in cookie:
                    key, value = cookie.strip().split('=', 1)
                    cookies[key] = value
            session_id = cookies.get('session_id')
            if session_id and session_id in sessions:
                del sessions[session_id]
        
        self.send_response(200)
        self.send_header('Set-Cookie', 'session_id=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT')
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
    
    def handle_get_entries(self):
        data = load_data()
        entries = sorted(data["entries"], key=lambda x: x["createdAt"], reverse=True)
        self.send_json_response(200, {"success": True, "entries": entries})
    
    def handle_create_entry(self, post_data):
        data = load_data()
        try:
            body = json.loads(post_data)
            title = (body.get("title") or "").strip()
            content = (body.get("content") or "").strip()
            mood = body.get("mood") or "neutral"
            tags = body.get("tags") or []
            
            if not title or not content:
                self.send_error_response(400, {"success": False, "message": "Title and content required"})
                return
                
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
            self.send_json_response(200, {"success": True, "entry": entry})
        except Exception as e:
            self.send_error_response(400, {"success": False, "message": "Invalid request"})
    
    def handle_update_entry(self, path, put_data):
        try:
            entry_id = int(path.split('/')[-1])
            data = load_data()
            entry = next((e for e in data["entries"] if e["id"] == entry_id), None)
            if not entry:
                self.send_error_response(404, {"success": False, "message": "Entry not found"})
                return
                
            body = json.loads(put_data)
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
            self.send_json_response(200, {"success": True, "entry": entry})
        except Exception as e:
            self.send_error_response(400, {"success": False, "message": "Invalid request"})
    
    def handle_delete_entry(self, path):
        try:
            entry_id = int(path.split('/')[-1])
            data = load_data()
            idx = next((i for i, e in enumerate(data["entries"]) if e["id"] == entry_id), -1)
            if idx == -1:
                self.send_error_response(404, {"success": False, "message": "Entry not found"})
                return
                
            data["entries"].pop(idx)
            save_data(data)
            self.send_json_response(200, {"success": True})
        except Exception as e:
            self.send_error_response(400, {"success": False, "message": "Invalid request"})
    
    def handle_entry_operations(self, path, post_data):
        # This handles cases where we need to simulate PUT/DELETE via POST
        method_override = self.headers.get('X-HTTP-Method-Override', '').upper()
        if method_override == 'PUT':
            self.handle_update_entry(path, post_data)
        elif method_override == 'DELETE':
            self.handle_delete_entry(path)
        else:
            self.send_error(404)
    
    def handle_get_stats(self):
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
                
        self.send_json_response(200, {
            "success": True,
            "totalEntries": len(entries),
            "totalWords": total_words,
            "streak": streak,
            "moodCounts": mood_counts,
            "tagCounts": tag_counts
        })

def run_server():
    server = HTTPServer(('0.0.0.0', PORT), JournalRequestHandler)
    print(f"InkWell Journal App started on port {PORT}")
    print(f"Access the app at: http://localhost:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    print("Starting InkWell Journal Application...")
    run_server()
