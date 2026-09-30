# MuseEcho 竞赛提交说明

## 交付物

- `source/MuseEcho-source.zip`：前端、后端、HarmonyOS NEXT 工程、测试与构建脚本。
- `app/*.hap`：HarmonyOS NEXT 应用包。文件名包含 `unsigned` 时仅用于本地模拟器验收。
- `videos/01_web_demo.mp4`：网页端演示。
- `videos/02_harmony_phone_demo.mp4`：HarmonyOS NEXT 手机端演示。
- `videos/03_harmony_tablet_demo.mp4`：HarmonyOS NEXT 平板端演示。
- `SOURCE_MANIFEST.json`：源码文件大小与 SHA-256 清单。
- `SHA256SUMS.txt`：提交包内交付文件校验值。

## 运行架构

`ArkUI 原生入口 → ArkWeb → React 工作台与同源 /api → FastAPI 音频分析服务`

HarmonyOS 客户端只申请网络权限。音频文件通过系统 DocumentViewPicker 单选，分析、解码与存储在 HTTPS 服务端完成。

## 已验证环境

- DevEco Studio 26.0.0.821
- HarmonyOS SDK 26.0.0.105
- target API 26，compatible API 20
- Node.js 22/24（各子项目以锁文件与 engines 为准）
- Python 3.12

## 核心构建命令

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
node --test harmony/tests/origin-policy.test.mjs
.\harmony\scripts\build.ps1
```

HarmonyOS 构建脚本会在 ASCII 临时路径创建隔离快照，避免中文仓库路径影响 Hvigor，然后把 HAP、日志和 SHA-256 复制到 `harmony/artifacts/`。

## 服务地址

提交构建使用受信任 HTTPS 服务：`https://museecho.toolgate.cloud`。

## 安装说明

未签名 Debug HAP 可安装到本项目已验证的 HarmonyOS 模拟器。真机安装需要使用提交者自己的 HarmonyOS 开发者签名材料重新签名；签名证书和私钥不包含在源码包中。

## 已知边界

- 应用采用 HarmonyOS NEXT 原生工程与 ArkWeb 混合架构，不声称所有工作台页面均由 ArkUI 重写。
- 不包含应用市场发布工作。
- 不包含服务器 Secret、用户数据、训练数据、依赖缓存或签名私钥。
