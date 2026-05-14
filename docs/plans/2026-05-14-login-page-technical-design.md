# 登录页技术方案

> 日期：2026-05-14
> 目标：以独立前端模块方式新增登录页和路由保护，尽量减少对既有业务页面的侵入。

## 1. 架构

```text
LoginPage
  -> auth/session
  -> localStorage
  -> ProtectedRoute
  -> MainLayout
```

MVP 采用前端本地会话，不接服务端账号系统。原因是当前项目是本地单用户量化工作台，用户明确只需要预设默认账号，不需要注册。

## 2. 文件设计

```text
frontend/src/auth/session.ts
frontend/src/auth/ProtectedRoute.tsx
frontend/src/pages/Login/LoginPage.tsx
frontend/src/pages/Login/LoginPage.css
frontend/tests/e2e/login.spec.ts
```

必要接入点：

- `App.tsx`：增加 `/login` 路由，并用 `ProtectedRoute` 包裹业务布局。
- `MainLayout.tsx`：系统设置区域增加“退出登录”动作。

## 3. 会话策略

localStorage key：

```text
newquant:auth
```

内容：

```json
{
  "username": "admin",
  "loginAt": "2026-05-14T00:00:00.000Z"
}
```

校验：

```text
username === "admin"
password === "admin123"
```

## 4. 路由策略

- 未登录访问 `/`、`/pools`、`/messages` 等业务路由：跳转 `/login`。
- 已登录访问 `/login`：跳转 `/`。
- 登录成功后：跳转来源页；无来源页则跳转 `/`。
- 退出登录后：清除 localStorage 并跳转 `/login`。

## 5. 测试

Playwright：

- 未登录访问 `/` 会跳转登录页。
- 错误密码出现错误提示。
- 正确账号密码进入仪表盘。
- 刷新后仍保持登录。

## 6. 风险说明

该方案不是安全认证，只是本地工作台入口保护。后续若需要部署到公网，应替换为服务端认证、密码哈希、HttpOnly Cookie 或 Token 方案。
