---
name: "hexun-live-login"
description: "和讯财道直播平台登录与页面初始化基础技能。当需要访问和讯财道(zhibo.homeway.com.cn)任意VIP直播课时调用：打开直播页→检测登录态→处理弹窗→执行手机号+验证码登录→验证消息容器就绪。返回已登录的浏览器viewId供后续操作使用。可被盯盘、消息提取、历史复盘、个股查询等上层agent复用。登录手机号仅用于本平台登录，严禁泄露。"
user-invocable: true
---

# 和讯财道直播登录技能

## 〇、技能定位

本技能是一个**基础能力组件**，专门解决「打开和讯财道VIP直播页并完成登录」这一动作。其他 agent（盯盘监控、历史消息提取、今日股票查询、复盘整理等）需要访问直播页时，应先调用本技能获得一个**已登录、页面就绪、消息容器可用**的浏览器 view，再开展自己的业务逻辑。

**本技能不负责**：消息轮询、内容推送、交易判断、盯盘节奏——这些由上层业务 agent 负责。

**本技能负责**：
1. 读取配置（直播室URL、登录手机号）
2. 打开页面、检测登录状态
3. 处理所有弹窗/广告/退出确认等干扰项
4. 如需登录，完成手机号+验证码流程（等待用户提供验证码）
5. 验证消息容器可用
6. 返回 `{viewId, status, latestMessageTime}` 给调用方

---

## 一、启动前准备

### 1.1 读取配置（必做）
读取 `{skill_dir}/memory.md`（平台信息、DOM 速查）与项目根 `.env` 的 `FUPANGE_HEXUN_LOGIN_PHONE`（登录手机号；优先级：环境变量 > `.env` > memory.md 明文，勿在 memory.md 存明文）：
- DOM选择器（弹窗关闭按钮、消息容器、登录表单等）
- 已知坑位清单

### 1.2 隐私安全（强制执行）
- 手机号**仅限在和讯财道登录表单中输入**，不得写入推送消息、脚本、其他网站
- 验证码仅在登录框输入，不记录、不外传
- 登录后的 Cookie/Token **严禁提取到外部脚本或发送到其他地方**
- 推送/输出内容中不得出现手机号、验证码、Cookie值

### 1.3 工具准备
使用 `integrated_browser` MCP 工具。严格遵守 MCP 协议：
1. `LS` 查看 `/data/user/mcps/.../integrated_browser/tools/` 目录
2. `Read` 读取要调用工具的 JSON descriptor
3. `run_mcp` 执行

**浏览器操作铁律**：先 `browser_lock`，操作结束必须 `browser_unlock`。即使出错退出，也要在 finally 语义中 unlock。

### 1.4 调用约定
本技能执行完毕后，向调用方（或用户）返回结构化结果：
```javascript
{
  "viewId": "浏览器视图ID",
  "status": "logged_in" | "already_logged_in" | "failed",
  "url": "当前页面URL",
  "roomTitle": "复盘哥专栏 VIP直播室",
  "messageCount": 123,        // 消息容器中的消息条数
  "latestMessageTime": "14:38", // 最新一条消息的时间
  "needCode": false           // true 表示等待用户给验证码（中断返回）
}
```

---

## 二、打开直播页

### 2.1 默认URL
默认房间为复盘哥VIP直播室（房间号11605）：
```
https://zhibo.homeway.com.cn/11605/vips.html
```
> 如果调用方指定了其他房间号（如 `roomId=xxx`），替换URL中的数字部分即可。

### 2.2 执行导航
```
browser_navigate: url = "<直播室URL>"
```
等待 3-5 秒让页面完全加载（`browser_wait_for` time=5）。

> ⚠️ `browser_wait_for` 的 `time` 参数不得超过 60 秒，长等待用 `RunCommand sleep`。

---

## 三、登录态检测

导航后**首先做一次快照**（`browser_snapshot`），根据页面特征判断当前状态：

### 3.1 状态判断表

| 页面特征 | 状态 | 下一步 |
|---------|------|--------|
| 出现标题"复盘哥专栏 VIP直播室"，消息区 `.pointBox.xxm-con` 有内容，无手机号输入框 | ✅ 已登录 | 跳到第五节「验证环境就绪」 |
| 出现手机号输入框（`input[type=tel]` 或 placeholder含"手机"）、"获取验证码"按钮 | 🔑 未登录-登录表单可见 | 连续 2 次确认后执行第四节「登录流程」 |
| 出现"登录"文字按钮/链接，但输入框不可见 | 🔑 未登录-需点击登录入口 | 先点击登录按钮，再执行第四节 |
| 弹出广告/活动弹窗（如"夏日勤学有好礼"）遮挡内容 | ⚠️ 弹窗干扰 | 先关闭所有弹窗（见3.2），再重新判断 |
| 弹出"确认退出"对话框 | ⚠️ 异常退出弹窗 | 处理退出弹窗（见3.3） |
| 页面白屏/加载失败/URL不对 | ❌ 加载异常 | 刷新重试（见第六节故障处理） |

### 3.1.1 失效确认规则（防止误判，spec FR-3）

页面加载初期元素可能未渲染完成，单次检测"未登录"信号可能是假阳性。**以下信号需连续 2 次检测（间隔约 10 秒）均出现，才确认登录态失效**：

- URL 跳转登录页或出现 `input[type=tel]`
- 消息容器 `.pointList.msglay` 为空且伴随登录表单
- 未登录/会话过期提示文案

2 次结果不一致时，以第 2 次检测为准再顺延一次（最多 3 次），仍不一致按异常处理（刷新页面后重判）。

### 3.1.2 无人值守模式的三级自愈入口

被 live-monitor 等上层 agent 以无人值守模式调用（环境变量 `MONITOR_RUNTIME_DIR` 存在）时，确认失效后不直接执行第四节，而是按 **live-monitor 技能 2.3 节的三级自愈决策树**执行：先辅助登录（含滑块自动识别），失败再降级 Cookie 续期 SOP。本技能第四节描述的登录流程为其中"人工对话模式"的标准流程。

### 3.2 关闭通用弹窗（高概率出现）
和讯页面常弹出活动广告、风险提示、奖学金打卡等弹窗。统一处理：

**方法A：通过 snapshot ref 点击关闭按钮**
如果 snapshot 里能看到 `button: 关闭` 之类的 ref，直接 `browser_click`。

**方法B：JS暴力关闭所有可见弹窗**
如果 snapshot 没给出明确 ref，用 evaluate 执行：
```javascript
(function() {
  // 1. 关闭所有带"关闭"文字的按钮
  document.querySelectorAll('button, a, .close, [class*="close"]').forEach(function(el) {
    var t = (el.innerText || el.textContent || '').trim();
    if (t === '关闭' || t === '×' || t === 'x' || t === '我知道了' || t === '确定' || t === '确认') {
      try { el.click(); } catch(e) {}
    }
  });
  // 2. 移除遮罩层
  document.querySelectorAll('.modal-mask, .mask, .overlay, [class*="mask"], [class*="dialog"]').forEach(function(el) {
    if (el.offsetParent !== null) { // 可见
      el.style.display = 'none';
      el.remove();
    }
  });
  return 'cleaned';
})();
```
关闭后再 snapshot 一次，确认弹窗已消失。

### 3.3 处理"确认退出"弹窗
这是页面重连时偶发的弹窗，普通 click 可能点不到，需要 JS 精准点击：
```javascript
(function() {
  // 查找包含"确认退出"/"确定退出"文本的对话框
  var all = document.querySelectorAll('button, a, div[role="button"]');
  for (var i = 0; i < all.length; i++) {
    var t = (all[i].innerText || all[i].textContent || '');
    if (t.indexOf('确认') >= 0 || t.indexOf('确定') >= 0) {
      try { all[i].click(); return 'clicked confirm: ' + t.trim().substring(0, 20); } catch(e) {}
    }
  }
  return 'no confirm dialog found';
})();
```
> 如果是"确认退出"弹窗，**点击"确认"会真的退出登录**。所以要先看弹窗内容：如果是"确认离开本页"或"确认退出"，应该点**取消/关闭**；如果是"登录已过期，请重新登录"，点确认后会跳登录。根据实际文本判断。保险做法：先 snapshot 看清弹窗内容再决定点哪个按钮。

---

## 四、登录流程（未登录时执行）

### 4.1 步骤总览
```
1. 点击"登录"入口（如果表单未直接显示）
2. 输入手机号 → 3. 点击"获取验证码" → 4. 等待用户提供验证码
5. 输入验证码 → 6. 点击"登录" → 7. 等待跳转 → 8. 确认登录成功
```

### 4.2 点击登录入口
- 如果 snapshot 里有明显的"登录"按钮/链接（ref可见），直接 `browser_click`
- 如果直接显示了手机号和验证码输入框，跳过此步
- 如果登录入口在 iframe 里（少见），需先进入 iframe：用 `browser_snapshot` 看是否有 iframe 元素，然后用 `contentDocument` 访问

### 4.3 输入手机号
1. 从项目根 `.env` 的 `FUPANGE_HEXUN_LOGIN_PHONE` 读取手机号（环境变量优先）
2. `browser_snapshot` 找到手机号输入框的 ref（特征：`input`，`type=tel`，或 placeholder 含"手机号"/"手机"）
3. 先 `browser_click` 激活输入框，再 `browser_type` 输入手机号
4. **手机号只在这一步出现**，不写入任何日志/推送/脚本

### 4.4 获取验证码
1. snapshot 找到"获取验证码"按钮（文字为"获取验证码"或"发送验证码"）
2. `browser_click` 点击
3. **立即中断流程，向用户报告**：
   > "验证码已发送到手机，请提供收到的6位验证码（有效期5分钟）。"
4. 等待用户回复验证码。此时技能处于 `needCode: true` 状态，浏览器保持在登录页不要关闭。

> 如果用户超过5分钟才回复，验证码已过期，需要：重新点击"获取验证码"，告知用户"验证码已过期，已重新发送，请提供新的验证码"。

### 4.5 输入验证码并登录
收到用户提供的6位验证码后：
1. snapshot 找到验证码输入框（特征：`input`，placeholder 含"验证码"，或紧邻"获取验证码"按钮）
2. `browser_type` 输入6位验证码
3. snapshot 找到"登录"按钮，`browser_click` 点击
4. `browser_wait_for` time=5 等待页面跳转/加载

### 4.6 登录后处理
1. 检查URL是否为 `https://zhibo.homeway.com.cn/11605/vips.html`（或对应房间URL）
2. 如果不在直播室页面，重新 `browser_navigate` 到目标URL
3. 再次关闭可能出现的弹窗（重复3.2步骤）
4. 进入第五节「验证环境就绪」

---

## 五、验证环境就绪（登录成功后必做）

登录成功（或本就已登录）后，执行以下 JS 确认消息环境可用：

```javascript
(function() {
  var box = document.querySelector('.pointBox.xxm-con');
  if (!box) return JSON.stringify({ok: false, reason: '消息容器 .pointBox.xxm-con 未找到'});
  box.scrollTop = box.scrollHeight;
  var msgs = document.querySelectorAll('.pointList.msglay');
  if (msgs.length === 0) return JSON.stringify({ok: false, reason: '消息列表为空，可能未登录或页面未加载完成'});
  // 获取最新一条消息的时间
  var latest = msgs[msgs.length - 1];
  var text = (latest.innerText || latest.textContent || '').trim();
  var timeMatch = text.match(/\b(\d{1,2}:\d{2})\b/);
  var latestTime = timeMatch ? timeMatch[1] : 'unknown';
  // 获取标题
  var titleEl = document.querySelector('h2, .room-name, .title');
  var title = titleEl ? (titleEl.innerText || titleEl.textContent || '').trim() : '';
  return JSON.stringify({
    ok: true,
    messageCount: msgs.length,
    latestMessageTime: latestTime,
    roomTitle: title,
    url: location.href
  });
})();
```

**判断标准**：
- 返回 `ok: true` → 环境就绪，技能完成
- 返回 `ok: false` → 根据 reason 处理：
  - "消息容器未找到" → 可能是页面没加载完，wait 3秒再试；或被弹窗遮挡，重新关闭弹窗
  - "消息列表为空" → 可能在非直播时间（如深夜），但仍可视为已登录，记录 `messageCount: 0`

### 5.1 返回结果
向调用方报告（格式见1.4）：
- `status: "logged_in"`（刚完成登录）或 `"already_logged_in"`（打开即已登录）
- viewId 供后续操作
- messageCount、latestMessageTime、roomTitle

---

## 六、DOM选择器速查

| 元素 | 选择器/特征 | 用途 |
|------|------------|------|
| 直播室URL | `https://zhibo.homeway.com.cn/{roomId}/vips.html` | 默认roomId=11605 |
| 消息滚动容器 | `.pointBox.xxm-con` | scrollTop=scrollHeight 到最新 |
| 每条消息 | `.pointList.msglay` | 消息列表项 |
| 房间标题 | `h2` 层级（含"复盘哥专栏 VIP直播室"） | 判断是否在正确页面 |
| 手机号输入框 | `input[type=tel]` 或 placeholder含"手机" | 输入登录手机号 |
| 验证码输入框 | input 紧邻"获取验证码"按钮，或placeholder含"验证码" | 输入6位码 |
| 获取验证码按钮 | 文字为"获取验证码"/"发送验证码"的 button/a | 触发短信 |
| 登录按钮 | 文字为"登录"的 button | 提交登录 |
| 通用弹窗关闭 | button 文字为"关闭"/"×"/"我知道了"/"确定" | 关闭广告/提示 |
| 弹窗遮罩 | `.modal-mask, .mask, .overlay, [class*="mask"]` | 可强制移除 |
| 今日股票tab | 链接文字"今日股票" | 可选查看个股列表 |
| 老师消息标识 | 消息文本开头含"李朋"或"廖峥" + 换行 + 时间 | 识别老师发言 |
| 私密消息标记 | 消息含"私密"字样 | VIP可见，仍可读取 |
| 免责声明 | 文本含"以上内容仅供参考…风险自担" | 提取时过滤 |

---

## 七、常见故障与处理

| 故障现象 | 可能原因 | 处理方式 |
|---------|---------|---------|
| 页面白屏/一直加载 | 网络问题、页面崩溃 | `browser_navigate` 重新打开URL，wait 5秒；若仍白屏，wait 10秒再试一次 |
| 找不到手机号输入框 | 输入框在iframe/弹窗里未展开 | 1) snapshot 仔细看结构 2) 检查是否有未关闭的遮罩 3) 尝试点击"登录"按钮展开表单 |
| 点击"获取验证码"无反应 | 按钮被遮挡/事件未绑定 | 1) 关闭弹窗 2) 用JS click：`document.querySelectorAll('button').forEach(b=>{if(b.innerText.indexOf('验证码')>=0)b.click()})` |
| 验证码过期（>5分钟） | 用户回复太慢 | 重新点击"获取验证码"，提示用户新验证码已发送 |
| 点登录后无跳转/无反应 | 验证码错误、网络卡顿 | 检查是否有错误提示（如"验证码错误"），若有则请用户重发；若无提示，wait 5秒后snapshot看状态 |
| 登录后跳回首页 | 登录失败/Cookie丢失 | 重新执行登录流程；检查是否有"账号异常"提示 |
| 消息容器找不到 | 页面结构变化/未登录完全 | 1) wait 3秒再测 2) 检查是否在正确URL 3) 检查是否有弹窗遮挡 4) 重新navigate |
| 消息列表为空 | 深夜/非交易时段、新房间 | 非故障，记录 messageCount:0，返回ok:true |
| 弹出"确认退出"对话框 | 页面异常重连 | JS判断弹窗文字：退出类点"取消"，过期类点"确认"后重新登录 |
| MQTT连接断开（消息不更新） | WebSocket断连 | 刷新页面（navigate重新打开），重新验证容器；注意刷新后可能补出历史消息 |
| browser_wait_for报错time超60秒 | 传了大于60的time参数 | 改用 `RunCommand sleep N`（N秒）替代 |
| 浏览器被lock无法操作 | 上次未unlock | 先 `browser_unlock` 释放，再重新操作 |

---

## 八、实战经验（多次登录沉淀）

1. **广告弹窗几乎必现**：每次 navigate 后都要主动关闭弹窗，不要假设页面干净。常见有"夏日勤学有好礼奖学金赚不停 去打卡"横条、风险提示弹窗等。
2. **snapshot比evaluate可靠**：判断页面状态优先用 `browser_snapshot`（能看到交互元素和ref），复杂DOM操作/批量关闭才用 evaluate。
3. **登录后要重新navigate一次**：有时候登录后停在首页或中间页，显式 navigate 到目标 vips.html 最稳。
4. **验证码等待期不要关浏览器**：等用户给验证码时，保持浏览器view打开但unlock，让用户能看到输入状态。
5. **手机号不要写在脚本里**：手机号永远从 memory.md 读取，不要硬编码到JS或Python脚本中，防止泄露。
6. **返回viewId给上层**：登录完成后不要关闭浏览器，把viewId返回给调用agent，它会接着做自己的业务（轮询/提取等），最后由它决定何时关闭。
7. **登录态通常持久化**：Cookie有效期较长，同一天内多次启动通常不需要重新登录；但隔几天或环境重置后需要重新登录。

---

## 九、调用示例（供上层agent参考）

**场景A：盯盘agent调用本技能**
```
1. 调用 hexun-live-login 技能（传入 roomId=11605 或用默认）
2. 收到返回 {status: "logged_in", viewId: "xxx", messageCount: 150}
3. 使用返回的 viewId 开始自己的盯盘轮询循环
4. 盯盘结束后 browser_unlock 并关闭tab
```

**场景B：用户说"打开直播课"**
```
1. 调用 hexun-live-login 技能
2. 如果 needCode=true → 提示用户输入验证码，收到后继续登录
3. 登录成功后告知用户"直播页已打开，当前最新消息时间 HH:MM"
```

**场景C：其他agent只需快速检查登录态**
```
1. 直接 navigate 到直播页，wait 3秒
2. snapshot 判断是否已登录（无手机号输入框+有消息区）
3. 已登录 → 直接用；未登录 → 调用本技能完整登录
```
