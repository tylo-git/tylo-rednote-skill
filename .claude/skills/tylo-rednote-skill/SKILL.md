---
name: tylo-rednote-skill
description: 根据用户输入的文本素材，自动生成小红书风格文案、使用 Gemini 生成配图（含水印），并通过 xiaohongshu-mcp 自动发布笔记。
dependencies: python>=3.8, requests, Pillow
---

# Tylo Rednote Skill — 小红书自动发布工作流

当用户要求生成并发布小红书笔记时，按以下三个阶段顺序执行。

---

## Stage 1：文案生成

### 触发条件
用户提供了文本素材（在 `.claude/skills/tylo-rednote-skill/assets/` 文件夹中，或直接在对话中给出文字）。

### 执行步骤
1. 读取用户提供的文本素材
2. 对文本进行**扩展、深度搜索与润色**，生成小红书风格内容
3. 输出 **Rednote Content**，包含以下字段：

### 输出格式（Rednote Content）

```markdown
## 标题
（≤ 15 字的小红书标题）

## 正文
（100–400 字，小红书风格正文，带适量 emoji，口语化表达）

## 核心要点
1. 要点一
2. 要点二
3. ...（3–7 条）

## 图片 Prompt
（Stage 2 生成后回填）
```

### 文案生成提示词

请使用以下提示词生成文案：

```
你是一位小红书爆款内容创作专家。请根据以下素材，生成一篇小红书笔记。

【素材内容】
{用户输入的文本}

【输出要求——必须严格遵守，否则视为失败】
1. 标题：⚠️ 严格限制在 15 个汉字以内（含标点和 emoji 各算1字）。生成后必须逐字计数确认，超出必须重写直到 ≤ 15 字。
2. 正文：严格 200-400 字（不含话题标签）。生成后必须计数确认字数在此范围内，不足 200 字需扩展，超过 400 字需精简。口语化、有温度、有干货感，适当使用 emoji（不超过 6 个）。
3. 核心要点：提炼 3-7 条关键信息，每条简明扼要
4. 正文结尾加上相关话题标签（#话题#格式，3-5个）

【风格参考】
- 开头用 hook 吸引注意力（提问/惊叹/数字）
- 段落短小，多用换行增强可读性
- 结尾引导互动（点赞/收藏/评论）

【⚠️ 自检清单——输出前必须逐项检查】
- [ ] 标题字数 ≤ 15？逐字数过一遍，不符合则重写
- [ ] 正文字数在 200-400 之间？不含标签，不符合则调整
- [ ] 核心要点 3-7 条？
```

### 约束（Claude 必须在输出文案后自动执行以下检查）
- 标题严格 ≤ 15 字。**生成后必须逐字计数**，如果超出则立即重写一个更短的标题，直到满足为止
- 正文严格 200–400 字（不含话题标签）。**生成后必须计数**，不足则扩展，超出则精简
- 核心要点 3–7 条

---

## Stage 2：图片生成

### 触发条件
Stage 1 的 Rednote Content 已生成，核心要点就绪。

### 执行步骤
1. 根据核心要点，为每张图片生成一个**图片生成 prompt**
2. 每个 prompt 必须包含以下**水印指令**：
   - 右下角显示文字水印：`AI博士生`（小尺寸，不遮挡主体内容）
   - 右上角显示文字水印：`叶秋` 并附带一个小叶子矢量图标（占用空间小）
3. 将生成的 prompt 保存到 Rednote Content 的「图片 Prompt」部分
4. 读取 `.claude/skills/tylo-rednote-skill/references/` 文件夹中的参考图片作为风格参考
5. 调用 `.claude/skills/tylo-rednote-skill/scripts/gemini_image_gen.py` 脚本生成图片

### Prompt 生成提示词

为每张图片生成 prompt 时，请使用以下模板：

```
根据以下要点生成一张适合小红书笔记的配图。

【要点内容】
{对应的核心要点}

【图片要求】
- 风格：参考 .claude/skills/tylo-rednote-skill/references/ 文件夹中的参考图，保持一致的视觉风格
- 布局清晰，信息图/知识卡片风格，适合手机竖屏浏览
- 配色和谐，文字可读
- 水印（必须包含）：
  - 右下角：「AI博士生」（小字，半透明，不遮挡主体）
  - 右上角：「叶秋」+ 小叶子图标（占用空间小）

请只输出英文 prompt，供 Gemini 生图模型使用。
```

### 图片生成脚本调用

```bash
python .claude/skills/tylo-rednote-skill/scripts/gemini_image_gen.py \
  --prompt "生成的英文prompt" \
  --reference .claude/skills/tylo-rednote-skill/references/参考图片文件名 \
  --output .claude/skills/tylo-rednote-skill/output/YYYY-MM-DD_HHMMSS/figure-N.png
```

### Gemini API 配置（用户自行填写）

> **⚠️ 请在使用前填写以下配置：**
>
> - API URL（中转地址）：`__YOUR_API_URL__`
> - API Key：`__YOUR_API_KEY__`
> - Model：`gemini-3-pro-image-preview`

### 输出约束
- 最多生成 **3 张**图片
- 文件命名：`YYYY-MM-DD-figure-1.png`、`YYYY-MM-DD-figure-2.png`、`YYYY-MM-DD-figure-3.png`
- 所有图片保存到 `.claude/skills/tylo-rednote-skill/output/YYYY-MM-DD_HHMMSS/` 文件夹

---

## Stage 3：自动发布

### 触发条件
Stage 1 文案和 Stage 2 图片均已生成。

### ⚠️ 关键：图片路径处理

xiaohongshu-mcp 运行在 Docker 容器中，**只能访问 Docker 映射的目录**。
当前 docker-compose.yml 将 `./images` 映射到容器内的 `/app/images`。

**因此，在发布前必须：**
1. 将 Stage 2 生成的图片**复制**到项目根目录的 `images/` 文件夹
2. 传给 `publish_content` 的图片路径必须是 **Docker 容器内路径**（`/app/images/xxx.png`），**绝对不能用 Windows 路径**

### 执行步骤
1. **复制图片到 Docker 映射目录**：
   ```bash
   # 将生成的图片复制到 images/ 文件夹（Docker 映射目录）
   cp .claude/skills/tylo-rednote-skill/output/YYYY-MM-DD_HHMMSS/*.png images/
   ```
2. 调用 xiaohongshu-mcp 的 `check_login_status` 检查登录状态
3. 如果未登录：提示用户先完成扫码登录，**停止发布流程**
4. 如果已登录：调用 `publish_content` 发布笔记

### 发布参数

```
工具：publish_content
参数：
  title: Stage 1 生成的标题（纯文本，不含 emoji 前缀标记）
  content: Stage 1 生成的正文（含话题标签）
  images: ["/app/images/YYYY-MM-DD-figure-1.png", "/app/images/YYYY-MM-DD-figure-2.png", "/app/images/YYYY-MM-DD-figure-3.png"]
```

> **⚠️ 绝对禁止传 Windows 路径（如 `E:\LLMproject\...`）给 images 参数！**
> Docker 容器无法访问 Windows 文件系统。必须使用 `/app/images/xxx.png` 格式。

### 发布提示词

```
请使用 xiaohongshu-mcp 工具发布小红书笔记：

1. 先将生成的图片复制到项目根目录的 images/ 文件夹
2. 调用 check_login_status 检查是否已登录小红书
3. 如果未登录，请提示我扫码登录
4. 如果已登录，调用 publish_content 发布，参数如下：
   - title: {生成的标题}
   - content: {生成的正文，含 #话题# 标签}
   - images: ["/app/images/文件名1.png", "/app/images/文件名2.png", ...]
   ⚠️ images 必须使用 Docker 容器路径 /app/images/，禁止使用 Windows 绝对路径！
5. 发布后输出结果（成功/失败及原因）
```

---

## 输出目录结构

每次运行会在 `.claude/skills/tylo-rednote-skill/output/` 下创建带时间戳的文件夹：

```
.claude/skills/tylo-rednote-skill/output/
└── YYYY-MM-DD_HHMMSS/
    ├── rednote_content.md      ← 标题/正文/要点/图片prompt
    ├── YYYY-MM-DD-figure-1.png ← 生成的配图
    ├── YYYY-MM-DD-figure-2.png
    └── YYYY-MM-DD-figure-3.png
```

---

## 文件夹说明

| 文件夹 | 用途 |
|--------|------|
| `.claude/skills/tylo-rednote-skill/assets/` | 用户输入的文本素材 |
| `.claude/skills/tylo-rednote-skill/scripts/` | 图片生成脚本（Gemini API 调用） |
| `.claude/skills/tylo-rednote-skill/references/` | 参考图片（用户手动放入，用于生图风格参考） |
| `.claude/skills/tylo-rednote-skill/output/` | 所有输出内容（每次运行一个带时间戳的子文件夹） |
