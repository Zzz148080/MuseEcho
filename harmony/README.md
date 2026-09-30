# MuseEcho HarmonyOS 开发工程

Stage 模型、ArkTS/ArkUI 原生入口、ArkWeb 工作台。2026-09-18 已使用真实 HarmonyOS SDK 编译得到 **未签名 debug HAP**，并在 API 20 手机模拟器安装启动成功；2026-09-30 已固定公网 HTTPS 服务地址并进入最终手机/平板验收。尚未完成真机运行、发布签名或上架。

## 架构与范围

`ArkUI → ArkWeb → 同源 HTTPS React 工作台及 /api → FastAPI 音频分析`

音乐分析仍在服务器运行，不把 Python/librosa/FFmpeg 移植进手机。现有前端源代码和 Cookie/CSRF 逻辑未改动。原生界面按项目 `DESIGN.md` 的雾蓝配色实现，保留真实空状态、错误、重试及可读字号。

- 编译 SDK：DevEco Studio 26.0.0.821 内置 SDK `26.0.0.105`。
- target API：26；最低兼容：HarmonyOS 6.0/API 20。最低版本只是配置，仍须设备验证。
- 设备类型：phone、tablet。
- 临时包名：`com.museecho.app`。发布前必须核对开发者账号中实际注册的包名。
- 图标为官方模板占位资产，发布前需替换为正式品牌图标。

## 构建与检查

在 PowerShell 7 中，从仓库根目录执行：

```powershell
node --test harmony/tests/origin-policy.test.mjs
./harmony/scripts/build.ps1
```

主机测试需要支持直接运行 TypeScript 的 Node.js（本机 Node 24 已验证）。构建脚本使用 IDE 配套的 Node、Java、OHPM、Hvigor，不依赖系统 Node 版本。

脚手架拒绝中文工程路径，因此脚本会创建唯一的英文临时目录，复制源码快照后构建，最后把日志、HAP 和 SHA-256 放入 `harmony/artifacts/MuseEchoHarmony-<唯一标识>/`。不会清空或覆盖原工程，也不删除旧构建目录。工具首次运行需要写入用户目录的依赖缓存并联网获取依赖。

也可在 IDE 中打开脚本打印的英文快照目录进行调试；正式修改应保存在仓库 `harmony/` 源码中，再重新构建，避免只修改临时副本。

临时公网联调可用 `./harmony/scripts/build.ps1 -TemporaryServiceOrigin 'https://<随机名>.trycloudflare.com'`，仅替换英文构建快照中的服务地址，不修改仓库的正式地址。该参数只接受 Cloudflare Quick Tunnel 的精确 HTTPS origin；生成的 HAP 内含会失效的测试地址，禁止作为分发包。

首次成功产物：

`artifacts/MuseEchoHarmony-70bb0d33729a42e1b18b947da845c440/entry-default-unsigned.hap`

SHA-256：`BC15C105A928A9864361731BB27E2B4D0AA359CBAF4F256002EDED61A1D3F1A7`，168,178 字节。

`No signingConfig found` 在当前阶段是预期警告；该未签名包已在本项目本地模拟器安装成功，但不代表可安装到真机或上架。构建脚本故意不复制签名密钥和本地签名材料。

## 服务地址与安全边界

`entry/src/main/ets/config/ServiceConfig.ets` 中的 `SERVICE_ORIGIN` 已固定为 `https://museecho.toolgate.cloud`，提交构建会直接加载该受信任 HTTPS 工作台。若开发者把它显式改回空字符串，应用才会显示临时连接页；输入的地址只在本次进程运行期间使用。Web 的常规 Cookie/缓存遵循 ArkWeb 行为，不能把地址不持久化理解为网页数据不落盘。

固定服务地址只支持 `https://域名` 和默认 443 端口，可接受末尾斜杠或显式 `:443`，不接受路径、账号、查询参数、本地地址或示例域名。域名校验不是 DNS 安全扫描；只能使用团队控制且信任的地址。

- 只申请 INTERNET 权限，不申请全盘文件、麦克风或相机权限。
- 文件选择使用系统 DocumentViewPicker，仅单选音频。取消、失败、页面导航和退出时结束待处理回调。
- 256 MiB/10 分钟与分片、容器/编码校验仍由现有前端及服务器负责；文件筛选器不替代内容验证。
- 主页面导航限定所选 origin；子资源仍按浏览器同源规则和服务器 CSP 管理，不宣称拦截所有跨域网络请求。
- 禁止混合内容与文件页面访问；证书错误调用 `handleCancel()`，不提供忽略证书按钮。
- 不注入原生 JavaScript 桥，也不记录音频内容、访问 Cookie 或服务凭据。
- 后台暂停媒体，返回前台不自动播放；系统返回优先回退网页历史。
- 窗口采用非全屏布局避开系统栏，仍须检查软键盘、横屏、大字号及底部工作台导航。
- 模板备份功能配置为不允许备份恢复。正式发布仍需完整隐私审核。

## 当前验证与未完成项

| 项目 | 状态 |
| --- | --- |
| 官方脚手架模板完整性检查 | 通过 |
| 原生 ArkTS/资源编译与 HAP 打包 | 通过，34 个构建任务 |
| OriginPolicy 主机测试 | 2 组通过，覆盖正常地址及恶意/畸形跳转 |
| 现有 React 类型检查、生产构建 | 通过 |
| 现有 React 单元测试 | 21 个文件、145 项通过（环境准备阶段） |
| API 20 手机模拟器安装及启动 | 通过，未关闭签名校验 |
| 手机原生入口及空地址校验 | 单一模拟器配置通过，已保存截图 |
| API 20 ArkWeb 加载真实临时 HTTPS 工作台 | 2026-09-28 通过，见联调记录；临时地址已关闭 |
| 系统文件选择器打开、取消、再次打开 | API 20 模拟器通过；文件库为空，未验证实际选择 |
| 公网 HTTPS API 合成音频上传、分析、Range 播放、CSRF 删除 | Docker 开发服务经短时隧道通过；不等同于设备内上传 |
| 平板、旋转、分屏及大字号视觉验证 | 未执行 |
| 设备内实际选中文件、上传、播放和前后台验证 | 未执行；模拟器文件库为空，仍需设备验收 |
| 调试/发布签名、APP 打包、上架 | 未执行 |

用户于 2026-09-18 明确确认华为模拟器许可与隐私协议后，已通过官方 CLI 下载 API 20 正式手机镜像，创建并启动 `MuseEcho_API20`。测试包在 `127.0.0.1:5555` 安装启动成功。输入操作触发模拟器中“小艺输入法”的独立隐私协议，涉及联网及通讯录、相机、麦克风、剪贴板等能力；未代替用户接受，输入交互测试暂停。完整证据见 `../docs/harmony/2026-09-18-emulator-smoke-test.md`。

2026-09-28 修复 Docker Desktop 后完成临时 HTTPS 联调和 ArkWeb 工作台/文件选择器冒烟；公网隧道、测试容器、测试数据卷与临时密钥已清理，模拟器恢复空地址 HAP。完整边界见 `../docs/harmony/2026-09-28-tunnel-smoke-test.md`。

构建工具自动安装的 `pnpm 10.28.2` 被 npm audit 标记为高危（1 个受影响包，含多条公告；报告范围至 `10.34.4`）。这是本机构建工具依赖，不是 HAP 运行时依赖；仍须在生产构建前通过兼容性验证升级或使用华为修复版本。本次未运行 `npm audit fix --force`，未替换全局工具链。不要用这个旧工具链构建不可信项目或锁文件。

## 设备验收清单

每次记录设备型号、系统/API、ArkWeb 版本、实际执行步骤与证据，不能用主机测试代替下列验收：

1. API 20 与 API 26 启动、旋转、平板/分屏、大字号、软键盘、安全区与返回行为。
2. 空地址、无效地址、HTTP、外域跳转、伪造同源前缀和证书错误均有正确反馈。
3. 正常 HTTPS 工作台加载、断网、30 秒超时、HTTP 错误、重试与修改服务地址。
4. 文件选择取消后能再次选择；导航/退出期间关闭待处理回调；重复触发不挂起网页。
5. 各支持格式、超限文件及伪造扩展名由前后端按既有规则验证，未经上传授权不得上传。
6. 完整分析、结果导航、音频播放、星系/钢琴试听、后台暂停及前台手动恢复。
7. Cookie 访问控制、CSRF 删除/问答、到期行为及隐私说明与已有服务一致。
8. Web 进程退出的恢复行为、无障碍焦点及错误提示可达性。

## 来源

基础工程来自华为 `@deveco/deveco-cli@1.3.0-stable` 的 Empty Ability 模板，保留生成文件中的许可证声明。新增实现不意味着赛事一定接受混合应用；需按所报名赛道的最新细则核对。

- [官方工具下载](https://developer.huawei.com/consumer/cn/download/deveco-studio)
- [ArkWeb 页面加载](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/web-page-loading-with-web-components)
- [ArkWeb 文件上传](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/web-file-upload)
- [鸿蒙高校创新赛](https://developer.huawei.com/consumer/cn/activity/incentive/C4)
