# HarmonyOS API 20 模拟器冒烟测试

日期：2026-09-18。仅代表以下实际执行项，不代表完整端到端、真机或发布验收。

## 环境与产物

- IDE：DevEco Studio 26.0.0.821，`C:\Program Files\Huawei\DevEco Studio`。
- 模拟器：`MuseEcho_API20`，phone，HarmonyOS 6.0.0(20)。
- 镜像：官方 Release `6.0.0.48`，下载大小 1,850,578,107 字节。
- 镜像目录：`C:\Users\P\AppData\Local\Huawei\Sdk\system-image\HarmonyOS-6.0.0\phone_all_x86`。
- 连接地址：`127.0.0.1:5555`；截图分辨率 1256 × 2760。
- 包名 / 入口：`com.museecho.app` / `EntryAbility`。
- 测试包：`harmony/artifacts/MuseEchoHarmony-70bb0d33729a42e1b18b947da845c440/entry-default-unsigned.hap`。
- SHA-256：`BC15C105A928A9864361731BB27E2B4D0AA359CBAF4F256002EDED61A1D3F1A7`。

## 结果

| 项目 | 实际结果 |
| --- | --- |
| 协议接受 | 用户明确确认后执行，CLI 返回 `Emulator license agreements accepted.` |
| 下载 | CLI 返回 `The image is downloaded successfully.` |
| 创建与启动 | `Device create success.`；`Emulator "MuseEcho_API20" started successfully.` |
| 安装 HAP | `hdc -t 127.0.0.1:5555 install <HAP>` 返回 `install bundle successfully.` |
| 启动入口 | `aa start -a EntryAbility -b com.museecho.app` 返回 `start ability successfully.` |
| 运行界面 | 原生品牌栏、连接说明、服务地址输入框、连接按钮均正常显示，非启动白屏 |
| 空地址提交 | 出现“请输入有效的 HTTPS 域名，不含路径、账号或参数。仅支持标准 443 端口。” |
| HTTP 地址输入 | 尝试输入 `http://localhost` 后出现独立输入法协议；没有确认输入值最终写入，不能计为 HTTP 拒绝测试通过 |

未修改模拟器签名校验、安全设置或权限来完成安装。此模拟器接受未签名调试包，不代表真机也接受。

## 视觉证据

![API 20 原生入口](evidence/api20-home.png)

![空地址校验](evidence/api20-empty-address.png)

`evidence/api20-launch.png` 记录的是首次启动过渡画面，不作为最终页面渲染通过的依据。

## 当前边界

1. 小艺输入法首次使用弹出独立隐私协议，涉及联网、通讯录、相机、麦克风、剪贴板及相应数据处理。未接受、未绕过。它不是 MuseEcho 申请的权限；MuseEcho 清单仍只有 INTERNET。
2. 尚无团队实际部署的可信 HTTPS 服务地址，未向示例域名或他人站点上传音频，也未验证 ArkWeb 内工作台、文件选择、分析、播放、删除或 CSRF。
3. 尚未进行横屏、平板、分屏、大字号、断网、证书错误和后台播放的设备验收。
4. 没有创建发布签名、上传源码、提交商店或参赛作品。没有使用重置卡。

下一步应先明确真实服务地址；若继续使用开发连接页，需要用户处理输入法协议。正式固定服务地址的构建可以不依赖手动地址输入，但仍需完整设备测试。
