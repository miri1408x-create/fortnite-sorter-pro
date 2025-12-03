import os
import re
from collections import defaultdict
import csv
from datetime import datetime
import zipfile
import tempfile
import streamlit as st
import json
import requests
import io
import shutil
import streamlit.components.v1 as components

# --- Configuration ---
DEFAULT_TG_TOKEN = "8320526788:AAECI8pPkEqUOEV3JaAz8VEVoLDKfnY2BCY"
DEFAULT_CHAT_ID = "-1003446261251"

# Set page config
st.set_page_config(
    page_title="Fortnite Sorter Pro",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- State Management ---
if 'processed_accounts' not in st.session_state:
    st.session_state.processed_accounts = None
if 'stats' not in st.session_state:
    st.session_state.stats = None

# --- Telegram Functions ---
def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

def send_telegram_document(token, chat_id, file_buffer, filename, caption=""):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    data = {"chat_id": chat_id, "caption": caption}
    # Reset buffer pointer to start
    file_buffer.seek(0)
    files = {"document": (filename, file_buffer, "text/plain")}
    try:
        response = requests.post(url, data=data, files=files, timeout=30)
        return response.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

# --- Parser Logic ---
class FortniteAccountParser:
    def __init__(self):
        self.accounts = defaultdict(dict)
        self.stats = {
            "total_accounts": 0, "total_vbucks": 0, "fa_yes": 0, "stw_yes": 0,
            "hit_accounts": 0, "total_skins": 0, "total_matches": 0
        }

    def normalize_bool(self, value):
        if isinstance(value, str):
            lower = value.lower()
            return 'Yes' if lower in ('yes', 'true', '1') else 'No'
        return 'Yes' if value else 'No'

    def parse_line(self, line):
        line = line.strip()
        if not line or line.startswith('#') or '====' in line: return None
        
        email_pass = re.search(r'([a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+\.[a-zA-Z0-9._-]+)[:|\s]+([^|\s]+)', line)
        if not email_pass: return None
        
        acc = {
            'email': email_pass.group(1).strip(),
            'password': email_pass.group(2).strip()
        }
        remaining = line.replace(f"{acc['email']}:{acc['password']}", "")
        
        # Extractors
        def get_val(pattern, default='No'):
            m = re.search(pattern, remaining, re.IGNORECASE)
            return self.normalize_bool(m.group(1)) if m else default

        def get_int(pattern):
            m = re.search(pattern, remaining, re.IGNORECASE)
            return int(m.group(1)) if m else 0

        def get_str(pattern):
            m = re.search(pattern, remaining, re.IGNORECASE)
            return m.group(1).strip() if m else 'Unknown'

        acc['fa'] = get_val(r'(?:FA|Full Access)[:\s]*([a-zA-Z0-9]+)')
        acc['stw'] = get_val(r'(?:STW|Save The World)[:\s]*([a-zA-Z0-9]+)')
        acc['vbucks'] = get_int(r'(?:Vbucks|V-Bucks)[:\s]*(\d+)')
        
        # Skins Logic
        skins_match = re.search(r'Skins[:\s]*\[(\d+)\]', remaining, re.IGNORECASE) or re.search(r'Skins[:\s]*(\d+)', remaining, re.IGNORECASE)
        acc['skins'] = int(skins_match.group(1)) if skins_match else 0
        
        acc['skin_names'] = []
        s_names = re.search(r'Skins:.*?\[\d*\]:?\s*(.+?)(?=\s*\||$)', remaining, re.IGNORECASE)
        if s_names:
            acc['skin_names'] = [s.strip() for s in s_names.group(1).split(',') if s.strip()]

        acc['last_played'] = get_str(r'Last Played[:\s]*([^|]+)')
        acc['level'] = get_int(r'Level[:\s]*(\d+)')
        acc['platform'] = get_str(r'Platform[:\s]*([^|]+)')
        
        # HIT Logic: FA + STW
        acc['is_hit'] = (acc['fa'] == 'Yes' and acc['stw'] == 'Yes')
        
        return acc

    def process_directory(self, root_dir):
        for root, _, files in os.walk(root_dir):
            for file in files:
                if file.endswith('.txt'):
                    try:
                        with open(os.path.join(root, file), 'r', encoding='utf-8', errors='replace') as f:
                            for line in f:
                                p = self.parse_line(line)
                                if p:
                                    # Merge logic: overwrite if new has more vbucks
                                    email = p['email']
                                    if email not in self.accounts or p['vbucks'] > self.accounts[email].get('vbucks', 0):
                                        self.accounts[email] = p
                    except: pass
        
        # Stats Calc
        vals = self.accounts.values()
        self.stats['total_accounts'] = len(vals)
        self.stats['total_vbucks'] = sum(a['vbucks'] for a in vals)
        self.stats['hit_accounts'] = sum(1 for a in vals if a['is_hit'])
        self.stats['fa_yes'] = sum(1 for a in vals if a['fa'] == 'Yes')
        
        return len(vals)

    def get_txt_string(self):
        output = io.StringIO()
        # Sort by Vbucks High -> Low
        sorted_accs = sorted(self.accounts.values(), key=lambda x: x['vbucks'], reverse=True)
        
        output.write(f"Generated by Fortnite Sorter Pro - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        output.write("==================================================\n\n")
        
        for acc in sorted_accs:
            line = f"{acc['email']}:{acc['password']} | V-Bucks: {acc['vbucks']} | Skins: {acc['skins']} | FA: {acc['fa']} | STW: {acc['stw']}"
            if acc['level'] > 0:
                line += f" | Level: {acc['level']}"
            if acc['last_played'] != 'Unknown':
                line += f" | Last Played: {acc['last_played']}"
            output.write(line + "\n")
            
        return output.getvalue()

# --- HTML/CSS View ---
def render_html_view(accounts_json):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
        :root {{
            --bg: #0e1117; --card-bg: #1e2530; --border: #2d3748; 
            --accent: #FF4B4B; --text: #e2e8f0; --muted: #94a3b8;
            --green: #10b981; --red: #ef4444; --gold: #f59e0b;
        }}
        body {{ background: transparent; color: var(--text); font-family: 'Inter', sans-serif; margin: 0; }}
        
        /* Filters */
        .controls {{ display: flex; gap: 8px; margin-bottom: 15px; flex-wrap: wrap; }}
        .btn {{
            background: var(--card-bg); border: 1px solid var(--border); color: var(--text);
            padding: 8px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85em; font-weight: 600;
            transition: all 0.2s; display: flex; align-items: center; gap: 6px;
        }}
        .btn:hover, .btn.active {{ border-color: var(--accent); color: var(--accent); background: rgba(255, 75, 75, 0.1); }}
        
        /* Grid */
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }}
        
        /* Card Design */
        .card {{
            background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
            padding: 12px; position: relative; transition: transform 0.1s;
        }}
        .card:hover {{ border-color: var(--muted); }}
        
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
        .vbucks {{ font-size: 1.1em; font-weight: 800; color: #38bdf8; display: flex; align-items: center; gap: 5px; }}
        
        .creds {{
            background: #00000040; padding: 6px 10px; border-radius: 4px; font-family: monospace;
            font-size: 0.85em; border: 1px solid #ffffff10; cursor: pointer; color: var(--text);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 8px;
        }}
        .creds:active {{ border-color: var(--accent); color: var(--accent); }}
        
        /* Stats Grid */
        .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; margin-bottom: 8px; }}
        .stat-box {{ 
            background: #ffffff05; padding: 4px; border-radius: 4px; text-align: center;
        }}
        .stat-val {{ font-size: 0.9em; font-weight: 700; }}
        .stat-lbl {{ font-size: 0.65em; color: var(--muted); text-transform: uppercase; }}
        
        .green {{ color: var(--green); }}
        .red {{ color: var(--red); }}
        
        .skins {{ font-size: 0.75em; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        
    </style>
    </head>
    <body>
        <div class="controls">
            <button class="btn active" onclick="filter('all', this)">ALL</button>
            <button class="btn" onclick="filter('hit', this)"><i class="fas fa-fire"></i> HITs (FA+STW)</button>
            <button class="btn" onclick="filter('fa', this)"><i class="fas fa-lock-open"></i> FA Only</button>
            <button class="btn" onclick="filter('stw', this)"><i class="fas fa-bolt"></i> STW Only</button>
            <button class="btn" onclick="filter('1k', this)">1k+ VBucks</button>
            <div style="flex-grow:1; text-align:right; font-size:0.8em; color: #666; align-self:center;" id="count"></div>
        </div>
        
        <div class="grid" id="grid"></div>

        <script>
            let data = {accounts_json};
            // Default sort: Vbucks High to Low
            data.sort((a, b) => b.vbucks - a.vbucks);
            
            const grid = document.getElementById('grid');
            const countLabel = document.getElementById('count');
            
            function render(items) {{
                grid.innerHTML = '';
                countLabel.innerText = items.length + ' Accounts';
                
                if(items.length === 0) {{
                    grid.innerHTML = '<div style="color:#666; padding:20px;">No accounts found.</div>';
                    return;
                }}
                
                items.forEach(acc => {{
                    // Determine Colors
                    const faClass = acc.fa === 'Yes' ? 'green' : 'red';
                    const faIcon = acc.fa === 'Yes' ? 'fa-check' : 'fa-times';
                    
                    const stwClass = acc.stw === 'Yes' ? 'green' : 'red';
                    const stwIcon = acc.stw === 'Yes' ? 'fa-bolt' : 'fa-ban';
                    
                    // Level logic
                    const levelDisplay = acc.level > 0 ? 
                        `<div class="stat-box"><div class="stat-val">${{acc.level}}</div><div class="stat-lbl">LVL</div></div>` : '';
                        
                    const skinsTxt = acc.skin_names.length > 0 ? acc.skin_names.slice(0,3).join(", ") + "..." : "No skin names";
                    
                    const card = document.createElement('div');
                    card.className = 'card';
                    card.innerHTML = `
                        <div class="header">
                            <div class="vbucks"><i class="fas fa-coins"></i> ${{acc.vbucks.toLocaleString()}}</div>
                            <div style="font-size:0.75em; color:#666;">${{acc.last_played}}</div>
                        </div>
                        
                        <div class="creds" onclick="navigator.clipboard.writeText('${{acc.email}}:${{acc.password}}')">
                            ${{acc.email}}
                        </div>
                        
                        <div class="stats" style="grid-template-columns: repeat(${{acc.level > 0 ? 4 : 3}}, 1fr);">
                            <div class="stat-box">
                                <div class="stat-val ${{faClass}}"><i class="fas ${{faIcon}}"></i></div>
                                <div class="stat-lbl">FA</div>
                            </div>
                            <div class="stat-box">
                                <div class="stat-val ${{stwClass}}"><i class="fas ${{stwIcon}}"></i></div>
                                <div class="stat-lbl">STW</div>
                            </div>
                            <div class="stat-box">
                                <div class="stat-val">${{acc.skins}}</div>
                                <div class="stat-lbl">SKINS</div>
                            </div>
                            ${{levelDisplay}}
                        </div>
                        
                        <div class="skins"><i class="fas fa-tshirt"></i> ${{skinsTxt}}</div>
                    `;
                    grid.appendChild(card);
                }});
            }}
            
            function filter(type, btn) {{
                document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                let res = data;
                if(type === 'hit') res = data.filter(a => a.fa === 'Yes' && a.stw === 'Yes');
                if(type === 'fa') res = data.filter(a => a.fa === 'Yes');
                if(type === 'stw') res = data.filter(a => a.stw === 'Yes');
                if(type === '1k') res = data.filter(a => a.vbucks >= 1000);
                
                render(res);
            }}
            
            render(data);
        </script>
    </body>
    </html>
    """
    return html

# --- Main App ---
def main():
    with st.sidebar:
        st.header("📲 Telegram Bot")
        tg_token = st.text_input("Bot Token", value=DEFAULT_TG_TOKEN, type="password")
        tg_chat_id = st.text_input("Chat ID", value=DEFAULT_CHAT_ID)
        if st.button("Reset App"):
            st.session_state.clear()
            st.rerun()

    st.title("⚡ Fortnite Sorter Pro v2")
    
    # Logic: Only show uploader if we haven't processed yet
    if st.session_state.processed_accounts is None:
        uploaded_file = st.file_uploader("📂 Upload ZIP file", type="zip")
        if uploaded_file and st.button("🚀 Process"):
            with st.spinner("Processing..."):
                temp_dir = tempfile.mkdtemp()
                with zipfile.ZipFile(uploaded_file, 'r') as z:
                    z.extractall(temp_dir)
                
                parser = FortniteAccountParser()
                parser.process_directory(temp_dir)
                
                # SAVE TO SESSION STATE
                st.session_state.processed_accounts = parser.accounts
                st.session_state.stats = parser.stats
                shutil.rmtree(temp_dir)
                st.rerun()
    
    else:
        # RESULTS VIEW (Persistent)
        accounts = st.session_state.processed_accounts
        stats = st.session_state.stats
        
        # --- Top Actions Bar ---
        c1, c2, c3 = st.columns([1, 2, 1])
        
        with c1:
            if st.button("🔙 Upload New"):
                st.session_state.clear()
                st.rerun()
        
        # Generate TXT
        parser = FortniteAccountParser()
        parser.accounts = accounts
        txt_data = parser.get_txt_string()
        
        with c2:
            st.download_button(
                "💾 Download Results (TXT)",
                data=txt_data,
                file_name=f"Fortnite_Results_{datetime.now().strftime('%H%M')}.txt",
                mime="text/plain",
                use_container_width=True
            )
            
        with c3:
            if st.button("✈️ Send to Telegram", use_container_width=True):
                with st.spinner("Sending..."):
                    if tg_token and tg_chat_id:
                        msg = (
                            f"📊 *Fortnite Results*\n"
                            f"👤 Accounts: `{stats['total_accounts']}`\n"
                            f"🔥 Hits (FA+STW): `{stats['hit_accounts']}`\n"
                            f"💰 Total V-Bucks: `{stats['total_vbucks']:,}`"
                        )
                        # Send Msg
                        send_telegram_message(tg_token, tg_chat_id, msg)
                        # Send File (BytesIO buffer)
                        buf = io.BytesIO(txt_data.encode('utf-8'))
                        res = send_telegram_document(tg_token, tg_chat_id, buf, "Results.txt")
                        
                        if res.get("ok"):
                            st.success("Sent!")
                        else:
                            st.error(f"Error: {res.get('description')}")
                    else:
                        st.error("Check Sidebar settings")

        # --- Metrics ---
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Accounts", stats['total_accounts'])
        m2.metric("Total V-Bucks", f"{stats['total_vbucks']:,}")
        m3.metric("HITs (FA+STW)", stats['hit_accounts'])
        m4.metric("FA Only", stats['fa_yes'])

        st.divider()
        
        # --- HTML View ---
        # Convert values to list for JSON
        acc_list = list(accounts.values())
        components.html(render_html_view(json.dumps(acc_list)), height=800, scrolling=True)

if __name__ == "__main__":
    main()
