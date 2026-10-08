from flask import Flask, request, render_template_string
import subprocess, os, requests, json, datetime, time, threading, re

app = Flask(__name__)
ZHIPU_KEY = os.environ.get("ZHIPU_API_KEY")
ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MEM_DIR = os.path.expanduser("~/agent_memory")
LONG_TERM = os.path.join(MEM_DIR, "long_term.json")
TASK_DIR = os.path.join(MEM_DIR, "task_logs")
SCHEDULE_FILE = os.path.join(MEM_DIR, "schedules.json")
os.makedirs(TASK_DIR, exist_ok=True)

class Memory:
    def __init__(self):
        self.short_term = []
        self.long_term = self.load()
    def load(self):
        try:
            with open(LONG_TERM, "r", encoding="utf-8") as f: return json.load(f)
        except: return {"preferences": {}, "history": []}
    def save(self):
        with open(LONG_TERM, "w", encoding="utf-8") as f: json.dump(self.long_term, f, ensure_ascii=False, indent=2)
    def add(self, role, content):
        self.short_term.append({"role": role, "content": content})
        if len(self.short_term) > 20: self.short_term = self.short_term[-20:]
    def log(self, user, result):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.long_term.setdefault("history", []).append({"time": ts, "task": user})
        self.long_term["history"] = self.long_term["history"][-50:]
        self.save()
    def get_context(self):
        return f"最近任务：{json.dumps(self.long_term.get('history', [])[-3:], ensure_ascii=False)}"

memory = Memory()

def load_schedules():
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_schedules(schedules):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f: json.dump(schedules, f, ensure_ascii=False, indent=2)

def scheduler_loop():
    while True:
        try:
            now = datetime.datetime.now(); today = now.strftime("%Y-%m-%d"); hm = now.strftime("%H:%M")
            schedules = load_schedules(); changed = False
            for s in schedules:
                if s.get("time") == hm and s.get("last_run") != today:
                    log_name = f"scheduled_{int(time.time())}.log"
                    log_path = os.path.join(TASK_DIR, log_name)
                    subprocess.Popen(f"source ~/.bashrc && {s['command']} > {log_path} 2>&1", shell=True, executable="/bin/bash")
                    s["last_run"] = today; changed = True
            if changed: save_schedules(schedules)
        except: pass
        time.sleep(30)

threading.Thread(target=scheduler_loop, daemon=True).start()

tools = [
    {"type": "function", "function": {"name": "run_async_task", "description": "后台启动耗时Termux命令。", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "list_logs", "description": "列出后台任务日志。", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_log", "description": "读取日志内容。", "parameters": {"type": "object", "properties": {"log_name": {"type": "string"}}, "required": ["log_name"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "读取文件前2000字符。", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "覆盖写入文件（需审批）。", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]}}},
    {"type": "function", "function": {"name": "schedule_task", "description": "创建每天定时任务。", "parameters": {"type": "object", "properties": {"time": {"type": "string"}, "command": {"type": "string"}, "name": {"type": "string"}}, "required": ["time", "command", "name"]}}},
    {"type": "function", "function": {"name": "list_scheduled", "description": "查看定时任务。", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "cancel_scheduled", "description": "取消定时任务。", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}}
]

def clean_log(content):
    lines = content.split("\n")
    clean_lines = []
    for l in lines:
        stripped = l.strip()
        if not stripped:
            continue
        if re.match(r'^[\d\s%\-:.]+$', stripped):
            continue
        if re.search(r'Total|Received|Xferd|Average Speed|Dload|Upload|Speed|Current|Left|Spent', l):
            continue
        if re.match(r'^\s*\d+\s+\d+', stripped):
            continue
        clean_lines.append(l)
    res = "\n".join(clean_lines).strip()
    return res if res else "（日志为空或仅含进度信息，任务可能还在执行或网络卡顿）"

def _web_search(query):
    import urllib.parse
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
        r = requests.get(url, timeout=15)
        data = r.json()
        results = []
        if data.get("AbstractText"): results.append(data["AbstractText"])
        for t in data.get("RelatedTopics", [])[:5]:
            if isinstance(t, dict) and t.get("Text"): results.append(t["Text"])
        return "\n".join(results) if results else "没找到相关结果。"
    except Exception as e: return f"搜索失败: {e}"

def _fetch_url(url):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        import re
        text = re.sub(r'<script.*?</script>', '', r.text, flags=re.DOTALL)
        text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:2000]
    except Exception as e: return f"抓取失败: {e}"

def _http_post(url, body_json):
    try:
        body = json.loads(body_json)
        r = requests.post(url, json=body, timeout=30)
        return r.text[:1500]
    except Exception as e: return f"请求失败: {e}"

def _download_file(url, save_path):
    try:
        save_path = save_path.replace("~", os.path.expanduser("~"))
        r = requests.get(url, timeout=60, stream=True)
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(8192): f.write(chunk)
        return f"已下载到 {save_path}（{os.path.getsize(save_path)} 字节）"
    except Exception as e: return f"下载失败: {e}"


import tempfile

def safe_execute_code(code_str):
    danger_patterns = ["rm -rf /", "mkfs", "dd if=", "shutdown", "reboot", ":(){ :|:& };:"]
    for p in danger_patterns:
        if p in code_str:
            return f"❌ 沙盒拦截：包含危险操作 [{p}]"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir=os.path.expanduser("~/agent_memory")) as f:
        f.write(code_str)
        tmp_path = f.name
    try:
        result = subprocess.run(["python3", tmp_path], capture_output=True, text=True, timeout=10, cwd=os.path.expanduser("~/agent_memory"))
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        return output[:1500] if output else "（执行完成，无输出）"
    except subprocess.TimeoutExpired:
        return "❌ 沙盒超时：执行超过10秒"
    except Exception as e:
        return f"❌ 沙盒异常：{str(e)}"
    finally:
        try: os.remove(tmp_path)
        except: pass

def run_tool(name, args):
    if name == "run_async_task":
        cmd = args.get("command", "")
        if "rm -rf /" in cmd or "mkfs" in cmd: return "禁止执行危险命令。"
        # 强制curl静默
        if "curl" in cmd and " -s" not in cmd and "-sS" not in cmd:
            cmd = cmd.replace("curl ", "curl -sS ")
        log_name = f"task_{int(time.time())}.log"
        log_path = os.path.join(TASK_DIR, log_name)
        subprocess.Popen(f"source ~/.bashrc && {cmd} > {log_path} 2>&1", shell=True, executable="/bin/bash")
        return f"任务已启动。日志：{log_name}。"
    elif name == "list_logs":
        logs = sorted([f for f in os.listdir(TASK_DIR) if f.endswith('.log')], key=lambda x: os.path.getmtime(os.path.join(TASK_DIR, x)), reverse=True)
        return "\n".join(logs) if logs else "暂无日志。"
    elif name == "read_log":
        log_path = os.path.join(TASK_DIR, args.get("log_name", ""))
        if not os.path.exists(log_path): return "找不到日志。"
        with open(log_path, "r", encoding="utf-8") as f: c = f.read()
        cleaned = clean_log(c)
        return cleaned[-1500:]
    elif name == "read_file":
        filepath = args.get("filepath", "").replace("~", os.path.expanduser("~"))
        if not os.path.exists(filepath): return "文件不存在。"
        with open(filepath, "r", encoding="utf-8") as f: return f.read()[:2000]
    elif name == "write_file":
        return f"[AUTH_REQUIRED] 准备写入文件 {args.get('filepath')}，需要用户批准。"
    elif name == "schedule_task":
        schedules = load_schedules()
        s = {"id": f"sched_{int(time.time())}", "name": args.get("name"), "time": args.get("time"), "command": args.get("command"), "last_run": None}
        schedules.append(s); save_schedules(schedules)
        return f"定时任务已创建：{s['name']}，每天 {s['time']} 执行。"
    elif name == "list_scheduled":
        schedules = load_schedules()
        if not schedules: return "暂无定时任务。"
        return "\n".join([f"- {s['name']} | 每天 {s['time']} | 上次执行：{s.get('last_run') or '未执行'}" for s in schedules])
    elif name == "cancel_scheduled":
        schedules = load_schedules(); new = [s for s in schedules if s["name"] != args.get("name")]
        save_schedules(new); return f"已取消 {len(schedules) - len(new)} 个任务。"
    elif name == "web_search": return _web_search(args.get("query", ""))
    elif name == "fetch_url": return _fetch_url(args.get("url", ""))
    elif name == "http_post": return _http_post(args.get("url", ""), args.get("body_json", "{}"))
    elif name == "download_file": return _download_file(args.get("url", ""), args.get("save_path", ""))
    return "未知工具"

def ask_agent(user_input, approve_cmd=None):
    if not ZHIPU_KEY: return "缺少 ZHIPU_API_KEY"
    if approve_cmd:
        system = "你正在执行已批准的命令。请直接调用 run_async_task 执行它，并总结结果。"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": f"执行命令：{approve_cmd}"}]
    else:
        system = f"""你是红米手机的AI管家。
{memory.get_context()}

【工具使用规则】
1. 查询新闻、资料、最新信息、任何需要联网搜索的内容 → 用 web_search，不要绕道去跑脚本。
2. 用户给了具体网址，让你读网页内容 → 用 fetch_url。
3. 调用外部 API 接口（POST） → 用 http_post。
4. 下载文件到本地 → 用 download_file。
5. 跑小说摘要/质检等红米脚本 → 用 run_async_task。
6. 问后台任务进度 → 先 list_logs 再 read_log。
7. 危险操作（写文件、删除） → 输出 [AUTH_REQUIRED] 等用户批准。
8. "每天X点/定时" → schedule_task；"立刻打卡/帮我打卡" → 直接 run_async_task 执行 curl 打卡命令。

【绝对禁止】
- 禁止编造不存在的脚本路径。红米的 HOME 是 ~ 或 /data/data/com.termux/files/home，不是 /home/user。
- 如果想到用某个脚本，先用 run_async_task 执行 ls ~/ 确认它存在。
- 不要因为任务里有"新闻"、"抓取"等词就幻想有个现成脚本。

最多执行5步。"""
        messages = [{"role": "system", "content": system}] + memory.short_term + [{"role": "user", "content": user_input}]

    full_log = ""
    for i in range(5):
        headers = {"Authorization": f"Bearer {ZHIPU_KEY}", "Content-Type": "application/json"}
        data = {"model": "glm-4-flash", "messages": messages, "tools": tools}
        try:
            resp = requests.post(ZHIPU_URL, headers=headers, json=data, timeout=30)
            msg = resp.json()['choices'][0]['message']
            messages.append(msg)
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc["function"]["name"]
                    try: args = json.loads(tc["function"]["arguments"])
                    except: args = {}
                    full_log += f"\n🔧 调用工具：{fn}\n"
                    result = run_tool(fn, args)
                    full_log += f"📋 结果：{result[:300]}...\n"
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            else:
                final = msg.get("content", "")
                full_log += final
                memory.add("user", user_input); memory.add("assistant", final)
                memory.log(user_input, full_log)
                return full_log
        except Exception as e:
            return full_log + f"\n❌ 错误：{str(e)}"
    return full_log + "\n⚠️ 达到最大步数"

HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>红米 Agent</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,'PingFang SC',sans-serif;background:#0f0f1a;color:#e8e8f0;height:100vh;display:flex;flex-direction:column;overflow:hidden;}
.header{background:linear-gradient(135deg,#1e1e3a,#2a1e4a);padding:16px 20px;border-bottom:1px solid #333;display:flex;align-items:center;justify-content:space-between;}
.header h1{font-size:17px;font-weight:600;background:linear-gradient(90deg,#8b7ff5,#f57fb5);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.header .status{font-size:11px;color:#66ff99;display:flex;align-items:center;gap:5px;}
.dot{width:7px;height:7px;background:#66ff99;border-radius:50%;animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:0.4;}}
#chat{flex:1;overflow-y:auto;padding:16px;}
.msg{max-width:85%;padding:12px 16px;border-radius:16px;margin:8px 0;word-wrap:break-word;white-space:pre-wrap;font-size:14px;line-height:1.5;}
.user{background:linear-gradient(135deg,#3b5fdb,#5b6fdb);margin-left:auto;border-bottom-right-radius:4px;}
.agent{background:#1c1c2e;margin-right:auto;border-bottom-left-radius:4px;border:1px solid #2a2a44;}
.approve-btn{background:linear-gradient(135deg,#f57fb5,#db3b5f);color:white;border:none;padding:10px 20px;border-radius:12px;font-size:14px;font-weight:600;margin-top:8px;cursor:pointer;width:100%;}
.input-area{background:#16162a;padding:12px 16px;border-top:1px solid #333;display:flex;gap:8px;}
.input-area input{flex:1;background:#0f0f1a;border:1px solid #333;color:#e8e8f0;padding:12px 16px;border-radius:24px;font-size:14px;outline:none;}
.input-area button{background:linear-gradient(135deg,#8b7ff5,#f57fb5);color:white;border:none;padding:12px 20px;border-radius:24px;font-size:14px;font-weight:600;}
</style></head>
<body>
<div class="header"><h1>⚡ 红米 Agent</h1><div class="status"><span class="dot"></span>在线</div></div>
<div id="chat">
{% for m in history %}
    {% if m.role == 'user' %}
        <div class="msg user">{{ m.content }}</div>
    {% else %}
        <div class="msg agent">{{ m.content }}</div>
    {% endif %}
{% endfor %}
{% if pending_cmd %}
<div class="msg agent">
⚠️ 需要批准危险操作：<br><code>{{ pending_cmd }}</code>
<form method="POST"><input type="hidden" name="approve_cmd" value="{{ pending_cmd }}"><button class="approve-btn" type="submit">批准执行</button></form>
</div>
{% endif %}
</div>
<form class="input-area" method="POST">
<input name="cmd" placeholder="输入任务..." autofocus autocomplete="off"><button type="submit">发送</button>
</form>
<script>
document.querySelector('#chat').scrollTop=999999;
// 15秒自动刷新，但如果输入框有内容则不刷新
setTimeout(function(){ 
    if(document.activeElement.tagName !== 'INPUT' || document.activeElement.value.length === 0) location.reload();
}, 15000);
</script>
</body></html>"""

history_store = []
last_user_msg = ""

@app.route('/', methods=['GET', 'POST'])
def index():
    global history_store, last_user_msg
    pending_cmd = None
    if request.method == 'POST':
        if 'approve_cmd' in request.form:
            cmd = request.form['approve_cmd']
            history_store.append({"role": "user", "content": f"[已批准] {cmd}"})
            result = ask_agent("", approve_cmd=cmd)
            history_store.append({"role": "agent", "content": result})
        else:
            cmd = request.form.get('cmd', '').strip()
            # 去重：如果和上一条完全相同，忽略
            if cmd and cmd == last_user_msg:
                return render_template_string(HTML, history=history_store, pending_cmd=None)
            last_user_msg = cmd
            history_store.append({"role": "user", "content": cmd})
            result = ask_agent(cmd)
            history_store.append({"role": "agent", "content": result})
            if "[AUTH_REQUIRED]" in result:
                m = re.search(r'\[AUTH_REQUIRED\]\s*(.*)', result)
                if m: pending_cmd = m.group(1).strip()
        if len(history_store) > 20: history_store = history_store[-20:]
    return render_template_string(HTML, history=history_store, pending_cmd=pending_cmd)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
