🚀 TFS 企微智能路由网关 (TFS to WeCom Smart Router Gateway)
📑 项目总结
TFS 企微智能路由网关 是一个基于 Python 和 Flask 构建的轻量级、高性能中间件服务。它的核心使命是连接 TFS/Azure DevOps (ADO) 与 企业微信 (WeCom)，将枯燥复杂的底层研发事件转化为排版精美、重点突出的企业微信群通知，极大提升研发团队的协同效率。

✨ 核心特性
🧠 智能信息提取与排版

支持解析多种工作项类型（Bug、任务、需求、长篇故事等），并自动匹配专属 Emoji。

深度抓取富文本内容（支持提取 Bug 的重现步骤、任务的详细描述、需求的验收标准），并经过智能 HTML 清洗后呈现为清爽的 Markdown 引用格式。

自动处理富文本超长问题（300字截断保护），保障企微接口高可用。

⏱️ 消息防抖与智能合并

内置基于工作项 ID 隔离的线程安全防抖器（Debouncer）。

完美解决同一工作项在短时间内（如 30 秒内）被多次修改导致的消息轰炸问题，无损合并修改历史。

🔔 动态强提醒机制

自动解析 TFS 处理人与提及（@），并精准转化为企业微信的 <@UserID> 强提醒格式。

具备强大的容错机制，精准识别更新过程中的 Unassigned（未指派）状态。

🌐 零停机热更新配置中心

内置单页面（SPA）可视化 Web 管理后台。

支持基于 Token 鉴权的在线配置修改（增删改查项目群机器人映射、调整防抖时间等）。

修改后直接覆写磁盘并秒级热加载生效，完全无需重启后端服务。

💻 全平台兼容

动态路径解析机制，完美兼容 Windows 桌面环境与 Linux 服务器环境运行。

📖 使用说明
1. 环境准备
确保运行环境已安装 Python 3.7+。
打开终端或命令行，安装所需的依赖包：

Bash
pip install flask requests
2. 文件结构与部署
请将以下核心文件放置在同一目录下（例如 /opt/tfs-wecom/ 或 D:\tfs-wecom\）：

app_server.py：后端核心主程序。

index.html：前端可视化配置面板。

config.json：持久化配置文件（可由程序自动生成/修改）。

manage.sh：（仅 Linux）系统服务一键管理脚本。

3. 服务启动
➡️ Windows 环境
直接在目录中打开命令行，运行：

DOS
python app_server.py
➡️ Linux 环境 (生产推荐)
首次部署请使用管理脚本一键注册为 systemd 后台守护进程，实现开机自启和崩溃自动拉起：

赋予执行权限：sudo chmod +x manage.sh

修复换行符（可选）：sed -i 's/\r$//' manage.sh

一键部署：sudo ./manage.sh install

Linux 常用运维命令：

启动服务：sudo ./manage.sh start

停止服务：sudo ./manage.sh stop

重启服务：sudo ./manage.sh restart

查看运行日志：sudo ./manage.sh log

4. 访问可视化配置面板 (Web UI)
服务启动后，控制台会打印当前的局域网 IP。

在浏览器中访问：http://<服务器IP>:5000/

在顶部输入默认管理 Token：MySecretToken@2026（以 config.json 中的 ADMIN_TOKEN 为准）。

点击 加载配置，即可在线修改端口、防抖时间、新增或删除项目的企微机器人 URL。

修改完成后点击 保存并应用网关配置，更改会立即生效。

5. TFS/Azure DevOps 配置指南
前往 TFS / Azure DevOps 的项目设置 (Project Settings) -> Service Hooks：

点击 Create subscription (+)。

Service 选择 WebHooks，点击 Next。

Trigger 选择 Work item created 或 Work item updated。

Action 设置中，URL 填写：http://<服务器IP>:5000/webhook

点击 Test 进行测试，成功后点击 Finish 即可。