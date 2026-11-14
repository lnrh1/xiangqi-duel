# 部署

工具本身没有第三方依赖，一台 1C1G 的云主机就够用。

## 1. 直接运行（临时）

```bash
cd /root/projects/xiangqi-duel
python3 -m xiangqi_duel.cli serve --port 8765
```

默认只监听 `127.0.0.1`。用 SSH 隧道从本地访问：

```bash
ssh -L 8765:127.0.0.1:8765 root@<服务器>
# 然后浏览器打开 http://127.0.0.1:8765
```

## 2. systemd 常驻（推荐）

```bash
sudo mkdir -p /opt/xiangqi-duel
sudo cp -r /root/projects/xiangqi-duel/* /opt/xiangqi-duel/
sudo cp /opt/xiangqi-duel/deploy/xiangqi-duel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xiangqi-duel
sudo systemctl status xiangqi-duel
```

模型库默认在 `~/.xiangqi-duel/models.json`（0600），对局日志在
`~/.xiangqi-duel/games/`。升级时只替换代码目录、保留这个目录即可。

## 3. 对外提供服务

不要直接把 8765 暴露到公网：这个页面可以添加模型密钥，等于把你的 Key 交给任何访问者。

推荐 nginx + Basic Auth：

```nginx
server {
    listen 443 ssl;
    server_name xiangqi.example.com;

    auth_basic "xiangqi";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
}
```

`proxy_buffering off` 是必须的，否则 SSE 观战流会被 nginx 缓冲。

## 4. 安全提醒

- API Key 只存在服务器本机，接口与日志都不会回显；但网页本身没有登录体系，
  谁能打开页面谁就能管理模型库；
- 对局同一时间只保留一场，开始新对局会终止旧对局；
- 如果只想安静地跑一局，用 CLI：`xiangqi-duel play --red model:m-x --black model:m-y --out game.json`。
