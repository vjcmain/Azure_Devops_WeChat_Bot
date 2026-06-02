#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import logging
import hashlib
import hmac
import re
import html
import copy
import urllib.parse
import threading
import socket
from datetime import datetime, timedelta
import requests
from flask import Flask, request, jsonify, render_template_string

# ==========================================
# 📂 动态路径定位（自动适配 Windows / Linux）
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
LOG_FILE = os.path.join(BASE_DIR, 'webhook.log')
HTML_FILE = os.path.join(BASE_DIR, 'index.html')

# ==========================================
# 🛑 配置日志
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"读取 {CONFIG_FILE} 失败: {e}")
            sys.exit(1)
    else:
        logging.error(f"未找到配置文件 {CONFIG_FILE}，请先创建！")
        sys.exit(1)

ACTIVE_CONFIG = load_config()
PORT = ACTIVE_CONFIG.get("PORT", 5000)

try:
    DEBOUNCE_WAIT_TIME = float(ACTIVE_CONFIG.get("DEBOUNCE_WAIT_TIME", 30))
except ValueError:
    DEBOUNCE_WAIT_TIME = 30.0

# ==========================================
# ⏳ 带无损数据合并功能的防抖器 (💡 已修复)
# ==========================================
class EventDebouncer:
    def __init__(self, wait_time=60):
        self.wait_time = wait_time  
        self.timers = {}
        self.payloads = {}  
        self.lock = threading.Lock()

    def debounce(self, key, payload_data, func, *args, **kwargs):
        with self.lock:
            if key in self.timers:
                self.timers[key].cancel()
                logging.info(f"🔄 捕获到连续操作，已使用最新数据覆盖并重置倒计时: {key}")
            
            # 💡 核心修复：TFS/ADO 的最新请求已包含完整快照，
            # 抛弃原有的复杂拼接逻辑，直接覆盖存储最新一份完整 Payload。
            self.payloads[key] = copy.deepcopy(payload_data)

            timer = threading.Timer(self.wait_time, self._run_func, args=(key, func, args, kwargs))
            self.timers[key] = timer
            timer.start()

    def _run_func(self, key, func, args, kwargs):
        try:
            with self.lock:
                payload_to_send = self.payloads.pop(key, None)
                if key in self.timers:
                    del self.timers[key]
            
            if payload_to_send:
                logging.info(f"⌛ 倒计时结束，触发实际发送逻辑: {key}")
                func(payload_to_send, *args, **kwargs)
        except Exception as e:
            logging.error(f"❌ 防抖发送线程发生严重错误: {e}", exc_info=True)

debouncer = EventDebouncer(wait_time=DEBOUNCE_WAIT_TIME)

# --- 辅助清洗函数 ---
def clean_html(raw_html):
    if not raw_html: return ""
    text = re.sub(r'</p>|</div>|<br\s*/?>', '\n', raw_html, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()

def get_host_ip():
    """获取本机实际的内网 IP 地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

# --- 核心处理逻辑 ---
class AzureDevOpsMessageProcessor:
    
    # 💡 正则动态扫描替换 @ 提醒
    def _replace_mentions(self, text):
        if not text: 
            return text
        return re.sub(r'[@＠]([a-zA-Z0-9\u4e00-\u9fa5]+)', r'<@\1>', text)

    def process_message(self, payload):
        try:
            if not isinstance(payload, dict): return None
            event_type = payload.get('eventType', '')
            
            if event_type.startswith('git.push'): return self._handle_git_push(payload)
            elif event_type.startswith('build.complete'): return self._handle_build_complete(payload)
            elif event_type.startswith('workitem.'): return self._handle_workitem(payload)
            elif event_type.startswith('ms.vss-code.git-pullrequest'): return self._handle_pull_request(payload)
            else: return self._handle_generic_event(payload)
        except Exception as e:
            logging.error(f"处理消息时发生错误: {str(e)}")
            return None

    def _handle_workitem(self, payload):
        resource = payload.get('resource', {})
        event_type = payload.get('eventType', '')
        
        project_name = 'Unknown'
        wi_type = 'Unknown'
        title = 'Unknown'
        state = 'Unknown'
        assigned_name = 'Unassigned'
        modifier_name = 'Unknown' 
        operator_title = "更新人"
        detail_msg = ""
        action = "更新"

        wi_id = resource.get('workItemId') or resource.get('id')

        op_time = datetime.now().strftime('%Y-%m-%d %H:%M')
        created_date_str = payload.get('createdDate')
        if created_date_str:
            try:
                utc_dt = datetime.strptime(created_date_str[:19], '%Y-%m-%dT%H:%M:%S')
                local_dt = utc_dt + timedelta(hours=8)
                op_time = local_dt.strftime('%Y-%m-%d %H:%M')
            except Exception:
                pass

        if event_type == 'workitem.created':
            action = "创建"
            operator_title = "创建人"
            fields = resource.get('fields', {})
            project_name = fields.get('System.TeamProject', 'Unknown')
            wi_type = fields.get('System.WorkItemType', 'Unknown')
            title = fields.get('System.Title', 'Unknown')
            state = fields.get('System.State', 'Unknown')
            
            assigned_raw = fields.get('System.AssignedTo')
            if isinstance(assigned_raw, dict): assigned_name = assigned_raw.get('displayName', 'Unassigned')
            elif isinstance(assigned_raw, str): assigned_name = assigned_raw
                
            modifier_raw = fields.get('System.CreatedBy')
            if isinstance(modifier_raw, dict): modifier_name = modifier_raw.get('displayName', 'Unknown')
            elif isinstance(modifier_raw, str): modifier_name = modifier_raw
            
            # 💡 提取详细描述
            desc_html = fields.get('Microsoft.VSTS.TCM.ReproSteps') or fields.get('System.Description')
            if desc_html:
                clean_desc = clean_html(desc_html)
                if clean_desc:
                    if len(clean_desc) > 300:
                        clean_desc = clean_desc[:300] + "..."
                    clean_desc = clean_desc.replace('\n', '\n> ')
                    desc_label = "问题描述" if wi_type == "Bug" else "详细描述"
                    detail_msg += f"> **{desc_label}**: \n> {clean_desc}\n\n"
            
            # 💡 提取验收标准
            ac_html = fields.get('Microsoft.VSTS.Common.AcceptanceCriteria')
            if ac_html:
                clean_ac = clean_html(ac_html)
                if clean_ac:
                    if len(clean_ac) > 300:
                        clean_ac = clean_ac[:300] + "..."
                    clean_ac = clean_ac.replace('\n', '\n> ')
                    detail_msg += f"> **验收标准**: \n> {clean_ac}\n\n"

            hist = fields.get('System.History')
            clean_comment = clean_html(hist)
            if clean_comment:
                clean_comment = clean_comment.replace('\n', '\n> ')
                clean_comment = self._replace_mentions(clean_comment)
                detail_msg += f"> **新增讨论**: {clean_comment}\n"
                
        else: 
            changes = resource.get('fields', {})
            revision_fields = resource.get('revision', {}).get('fields', {})
            project_name = revision_fields.get('System.TeamProject', 'Unknown')
            wi_type = revision_fields.get('System.WorkItemType', 'Unknown')
            title = revision_fields.get('System.Title', 'Unknown')
            state = revision_fields.get('System.State', 'Unknown')
            
            # 💡 增强型处理人捕获机制
            assigned_raw = revision_fields.get('System.AssignedTo')
            if not assigned_raw and 'System.AssignedTo' in changes:
                assigned_raw = changes['System.AssignedTo'].get('newValue')

            if isinstance(assigned_raw, dict): 
                assigned_name = assigned_raw.get('displayName', 'Unassigned')
            elif isinstance(assigned_raw, str): 
                assigned_name = assigned_raw
            else:
                assigned_name = 'Unassigned'
                
            modifier_raw = revision_fields.get('System.ChangedBy')
            if not modifier_raw: 
                modifier_raw = resource.get('revisedBy')
            if isinstance(modifier_raw, dict): modifier_name = modifier_raw.get('displayName', 'Unknown')
            elif isinstance(modifier_raw, str): modifier_name = modifier_raw
                
            if 'System.State' in changes:
                old_state = changes['System.State'].get('oldValue', '')
                new_state = changes['System.State'].get('newValue', '')
                detail_msg += f"> **状态流转**: {old_state} ➡️ <font color=\"warning\">{new_state}</font>\n"
                
            if 'System.History' in changes:
                hist = changes['System.History'].get('newValue', '')
                clean_comment = clean_html(hist)
                if clean_comment:
                    clean_comment = clean_comment.replace('\n', '\n> ')
                    clean_comment = self._replace_mentions(clean_comment)
                    detail_msg += f"> **新增讨论**: {clean_comment}\n"

        # 剥离 TFS 后缀保留纯净名字
        if '<' in assigned_name: assigned_name = assigned_name.split('<')[0].strip()
        if '<' in modifier_name: modifier_name = modifier_name.split('<')[0].strip()

        web_url = ""
        html_link = resource.get('_links', {}).get('html', {}).get('href', '')
        if html_link: web_url = html_link
        else:
            msg_md = payload.get('message', {}).get('markdown', '')
            match = re.search(r'\]\((https?://[^\)]+)\)', msg_md)
            if match: web_url = match.group(1)

        replace_domain = ACTIVE_CONFIG.get("TFS_DOMAIN_REPLACE", "").strip()
        if web_url and replace_domain:
            try:
                parsed_url = urllib.parse.urlparse(web_url)
                parsed_replace = urllib.parse.urlparse(replace_domain)
                web_url = parsed_url._replace(scheme=parsed_replace.scheme, netloc=parsed_replace.netloc).geturl()
            except Exception:
                pass

        if assigned_name != 'Unassigned':
            display_assignee = f"<@{assigned_name}>"
        else:
            display_assignee = assigned_name

        TYPE_EMOJIS = {
            "Bug": "🐞",
            "任务": "📋",
            "需求": "🎯",
            "特性": "✨",
            "问题": "⚠️",
            "用户情景": "👤",
            "长篇故事": "📚",
            "测试用例": "🧪"
        }
        emoji = TYPE_EMOJIS.get(wi_type, "📝")

        msg = f"{emoji} **{wi_type}{action}通知**\n\n"
        if project_name != 'Unknown': msg += f"**所属项目**: {project_name}\n"
        
        id_display = f"#{wi_id}" if wi_id else ""
        display_title = f"{wi_type} {id_display}: {title}"
        
        if web_url: msg += f"**工作项**: [{display_title}]({web_url})\n"
        else: msg += f"**工作项**: {display_title}\n"
        
        if modifier_name != 'Unknown':
            msg += f"**{operator_title}**: {modifier_name} @{op_time}\n"
            
        msg += f"**处理人**: {display_assignee}\n"
        msg += f"**当前状态**: {state}\n"
        if detail_msg: msg += f"\n{detail_msg}"

        return {"msgtype": "markdown", "markdown": {"content": msg}}, project_name

    def _handle_git_push(self, payload):
        return {"msgtype": "markdown", "markdown": {"content": "代码推送"}}, "Unknown"
    def _handle_build_complete(self, payload):
        return {"msgtype": "markdown", "markdown": {"content": "构建完成"}}, "Unknown"
    def _handle_pull_request(self, payload):
        return {"msgtype": "markdown", "markdown": {"content": "拉取请求"}}, "Unknown"
    def _handle_generic_event(self, payload):
        event_type = payload.get('eventType', 'Unknown')
        msg = f"🔔 **ADO 事件通知**\n\n**类型**: {event_type}\n**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return {"msgtype": "markdown", "markdown": {"content": msg}}, 'Unknown'

    def send_to_wechat(self, message, webhook_url):
        try:
            response = requests.post(webhook_url, json=message, headers={'Content-Type': 'application/json'}, timeout=10)
            if response.status_code == 200 and response.json().get('errcode') == 0:
                return True
            else:
                logging.error(f"企业微信返回错误: {response.text}")
                return False
        except Exception as e:
            logging.error(f"发送失败: {str(e)}")
            return False

processor = AzureDevOpsMessageProcessor()
app = Flask(__name__)

def verify_signature(payload_bytes, signature, secret):
    if not secret: return True
    try:
        exp_sig = hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
        if signature.startswith('sha256='): signature = signature[7:]
        return hmac.compare_digest(exp_sig, signature)
    except: return False

def process_and_send_payload(payload_data, webhook_url, event_type, project_name):
    result = processor.process_message(payload_data)
    if not result: return
    wechat_message, _ = result
    if processor.send_to_wechat(wechat_message, webhook_url):
        logging.info(f"✅ [{project_name}] 消息已成功分发至企微！")


# ==========================================
# 🖥️ 可视化前端页面分发路由 (💡 已改为动态定位)
# ==========================================
@app.route('/')
def index_page():
    try:
        with open(HTML_FILE, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return render_template_string(html_content)
    except FileNotFoundError:
        return f"<h3>❌ 错误：未找到前端主页文件！</h3><p>请确保 <b>index.html</b> 与 app_server.py 存放在同一目录下。<br/>当前检测路径: {HTML_FILE}</p>", 404


# ==========================================
# ⚙️ Web UI 配置管理核心接口 (支持热更新)
# ==========================================
 
@app.route('/api/config', methods=['GET', 'POST'])
def manage_config():
    # 💡 修复：将 global 声明置于函数最顶端，在任何读取操作之前
    global ACTIVE_CONFIG, PORT, DEBOUNCE_WAIT_TIME
    
    expected_token = ACTIVE_CONFIG.get('ADMIN_TOKEN', 'admin_fallback_123')
    auth_header = request.headers.get('Authorization', '')
    
    if auth_header != f"Bearer {expected_token}":
        logging.warning("⚠️ 拒绝了一次未授权的配置访问/修改请求")
        return jsonify({'error': '未授权访问，Token 错误或缺失'}), 401

    if request.method == 'GET':
        return jsonify(ACTIVE_CONFIG), 200

    if request.method == 'POST':
        try:
            new_config = request.get_json()
            if not new_config or not isinstance(new_config, dict):
                return jsonify({'error': '无效的 JSON 格式'}), 400
                
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(new_config, f, indent=4, ensure_ascii=False)
                
            ACTIVE_CONFIG = new_config
            PORT = ACTIVE_CONFIG.get("PORT", 5000)
            
            try:
                DEBOUNCE_WAIT_TIME = float(ACTIVE_CONFIG.get("DEBOUNCE_WAIT_TIME", 30))
                debouncer.wait_time = DEBOUNCE_WAIT_TIME  
            except ValueError:
                pass
                
            logging.info("✅ 配置文件已通过 Web API 成功完成覆写与无感知热更新！")
            return jsonify({'status': 'success', 'message': '配置更新成功并已即时生效'}), 200
            
        except Exception as e:
            logging.error(f"❌ Web更新配置时遇到内部严重错误: {str(e)}")
            return jsonify({'error': f'内部保存错误: {str(e)}'}), 500


# ==========================================
# 📩 TFS/Azure DevOps 核心 Webhook 入口
# ==========================================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        if not request.content_type.startswith('application/json'):
            return jsonify({'error': 'Content-Type必须是application/json'}), 400
            
        payload_bytes = request.get_data()
        signature = request.headers.get('X-Hub-Signature-256', '')
        secret = ACTIVE_CONFIG.get('AZURE_WEBHOOK_SECRET', '')
        
        if secret and not verify_signature(payload_bytes, signature, secret):
            logging.warning("⚠️ 签名验证失败，拒绝请求")
            return jsonify({'error': '签名验证失败'}), 401
            
        data = json.loads(payload_bytes.decode('utf-8'))
        event_type = data.get('eventType', 'Unknown')
        
        project_name = 'Unknown'
        wi_id = None
        if 'resource' in data:
            project_name = data['resource'].get('project', {}).get('name') or \
                           data['resource'].get('repository', {}).get('project', {}).get('name') or \
                           data['resource'].get('fields', {}).get('System.TeamProject') or \
                           data['resource'].get('revision', {}).get('fields', {}).get('System.TeamProject', 'Unknown')
            
            wi_id = data['resource'].get('workItemId') or data['resource'].get('id')

        projects_config = ACTIVE_CONFIG.get("PROJECTS", {})
        webhook_url = projects_config.get(project_name)
        
        if not webhook_url:
            webhook_url = projects_config.get("DEFAULT")
            if not webhook_url:
                logging.warning(f"🚫 未找到 [{project_name}] 的配置且没有 DEFAULT 兜底，放弃发送。")
                return jsonify({'status': 'ignored', 'message': f'未配置项目 {project_name}'}), 200

        if event_type in ['workitem.updated', 'workitem.created'] and wi_id:
            debounce_key = f"{project_name}_wi_{wi_id}"
            event_action = "更新" if event_type == "workitem.updated" else "创建"
            logging.info(f"⏳ 收到 [{project_name}] 的工作项 #{wi_id} {event_action}，进入防抖合并模式 ({DEBOUNCE_WAIT_TIME}秒)...")
            
            debouncer.debounce(debounce_key, data, process_and_send_payload, webhook_url, event_type, project_name)
            return jsonify({'status': 'debounced', 'message': '合并发送中'}), 200
        else:
            logging.info(f"📩 收到非工作项事件: [{event_type}]，归属项目: [{project_name}]，立即发送")
            process_and_send_payload(data, webhook_url, event_type, project_name)
            return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        logging.error(f"内部错误: {str(e)}")
        return jsonify({'error': '内部错误'}), 500

if __name__ == "__main__":
    if "PROJECTS" not in ACTIVE_CONFIG or not ACTIVE_CONFIG["PROJECTS"]:
        logging.error("❌ 错误：缺少 PROJECTS 节点配置，请检查 config.json！")
        sys.exit(1)
        
    server_ip = get_host_ip()
    logging.info(f"🚀 Linux/Windows 智能路由网关V20260521A已成功拉起！")
    logging.info(f"🔗 可视化后台面板请访问: http://{server_ip}:{PORT}/")
    logging.info(f"🎯 所有 TFS Webhook 请统一请求: http://{server_ip}:{PORT}/webhook")
    logging.info(f"⏱️  当前消息防抖合并机制已就绪。")
    
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    app.run(host='0.0.0.0', port=PORT)