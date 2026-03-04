# Clash 代理 × Claude Code × 小红书自动发布 — 网络踩坑全记录

> 场景：使用 Claude Code + tylo-rednote-skill 在 Docker 容器中自动发布小红书笔记，同时需要 Clash 代理访问 Claude API。

---

## 问题背景

使用 `xiaohongshu-mcp` Docker 容器自动发布小红书时，遭遇连续网络错误：

```
navigation failed: net::ERR_CONNECTION_CLOSED
```

原因是 `creator.xiaohongshu.com`（创作者发布平台）**仅允许大陆 IP 访问**，而 Clash 代理将流量路由至海外节点，被小红书服务器直接拒绝。

---

## 踩坑记录

### 坑 1：Git Bash 路径自动转换

**现象**：传入 `/app/images/xxx.png`，容器实际收到 `C:/Program Files/Git/app/images/xxx.png`

**解决**：调用脚本时加 `MSYS_NO_PATHCONV=1`
```bash
MSYS_NO_PATHCONV=1 python publish_to_xiaohongshu.py --images /app/images/xxx.png
```

---

### 坑 2：Windows 中文输出编码错误

**现象**：`UnicodeEncodeError: 'charmap' codec can't encode characters`

**解决**：加 `PYTHONIOENCODING=utf-8`
```bash
PYTHONIOENCODING=utf-8 python publish_to_xiaohongshu.py
```

---

### 坑 3：`creator.xiaohongshu.com` 连接被拒

**现象**：Chrome (Rod) 报 `net::ERR_CONNECTION_CLOSED`

**根本原因**：
- Docker 容器 DNS 被 Clash TUN 接管，返回 fake IP（`198.18.x.x`）
- Docker bridge 网络无法路由到 Clash 的虚拟 TUN 地址
- 或代理出口 IP 为海外，`creator.xiaohongshu.com` 拒绝访问

---

### 坑 4：Clash 代理模式冲突（核心问题）

| 模式 | Claude Code | 小红书发布 | 说明 |
|------|-------------|-----------|------|
| Global（全局） | ✅ | ❌ | 规则全失效，全走代理 |
| Direct（直连） | ❌ | ✅ | 无代理，Claude 断连 |
| Rule（规则）+ DIRECT 规则 | ✅ | ✅ | **正确方案** |

**踩的坑**：在 Global 模式下加 DIRECT 规则 → 完全无效，因为 **Global 模式会无视所有规则**。

---

## 最终解决方案

### 第一步：Clash 切换到 Rule 模式

打开 Clash → 代理模式 → 选择 **「规则 (Rule)」**

> ⚠️ 不是 Global，不是 Direct！

### 第二步：规则列表顶部加入

```yaml
rules:
  - DOMAIN-SUFFIX,xiaohongshu.com,DIRECT
  - DOMAIN-SUFFIX,xhslink.com,DIRECT
  # ... 其他原有规则
```

> ⚠️ 必须放在所有规则**最顶部**，否则会被其他规则先匹配。

### 第三步：Reload Config（重载配置）

改完立即生效。

---

## 完整发布命令

```bash
MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8 \
python .claude/skills/tylo-rednote-skill/scripts/publish_to_xiaohongshu.py \
  --title "笔记标题" \
  --content "正文内容 #话题标签" \
  --images /app/images/figure-1.png /app/images/figure-2.png /app/images/figure-3.png
```

---

## 原理说明

| 知识点 | 说明 |
|--------|------|
| Global 模式 | 强制所有流量走选定节点，规则列表完全失效 |
| Rule 模式 | 按规则列表从上到下匹配，支持 DIRECT/PROXY/指定节点 |
| Clash TUN | 网络层（Layer 3）拦截，Docker 容器流量也会被截获 |
| Fake IP | Clash DNS 返回虚拟地址，Docker bridge 无法路由到此 |
| 规则优先级 | Clash 从上到下匹配，第一条命中即生效 |
