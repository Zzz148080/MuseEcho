# HarmonyOS 环境准备记录

核验日期：2026-09-18（Asia/Shanghai）。本记录不代表鸿蒙工程已编译、已安装或已部署。

## 安装包

- 文件：`C:\Users\P\Downloads\devecostudio-windows-26.0.0.821.zip`
- 文件大小：3,295,941,922 字节。
- ZIP SHA-256：`5F4AE0FDD091EA5BC4CCD9F577DD2885D3DF8FF8F6F64B54285AE4E5C2232A5B`
- 解压路径：`D:\人工智能创新赛\tmp\deveco-26.0.0.821-verification\devecostudio-windows-26.0.0.821\deveco-studio-26.0.0.821.exe`
- EXE 大小：3,296,046,208 字节。
- EXE SHA-256：`5186FAEC6F91FFE003E498201B9AA8F78B687B9E3B763CC2C29C2DA65DC523B7`
- 安装程序元数据：ProductVersion `26.0.0`，CompanyName `Huawei`。
- `Expand-Archive` 完整解压成功。
- `Get-AuthenticodeSignature` 返回 `Valid` / `Signature verified.`。
- 代码签名发布者：`Huawei Technologies Co., Ltd.`。
- 签名颁发机构：`GlobalSign GCC R45 CodeSigning CA 2020`。
- 时间戳签名者：`Sectigo Public Time Stamping Signer R37`。

上述两个 SHA-256 是本机计算结果，尚未与官网公布的哈希值比对。来源验证依据是 Windows 已验证有效的华为发布者签名，不把计算哈希本身当作官方比对通过。

## 工具准备

官网版本列表已确认 Windows 64 位 `26.0.0.821 Release`，发布日期 2026-08-29。

官方 `@deveco/deveco-cli@1.3.0-stable` 已安装到项目忽略目录 `tmp/deveco-cli-tools/`，使用 `--ignore-scripts`，未执行其后台初始化脚本，未注册系统级 CLI、插件或账号。它不能替代完整 IDE/SDK。

读取该包内 `docs.zip` 的 `开发指南/下载与安装DevEco_Studio/ide-software-install.md` 后确认：DevEco Studio 合一打包 HarmonyOS SDK、Node.js、Hvigor、OHPM 和模拟器平台。无需重复下载 Command Line Tools；具体模拟器设备镜像另行按需配置。

后续进展：用户确认安装后自行完成向导，并明确同意保留默认位置 `C:\Program Files\Huawei\DevEco Studio`。安装已验证，Build 为 `DS-261.23567.138.36.2600821`，内置 SDK `26.0.0.105`。未代替用户处理 UAC、安全设置、开发者实名认证或账号授权。

独立工程与首个未签名 HAP 已完成真实编译。详见仓库 `harmony/README.md`。原生视觉、模拟器和真机运行尚未验证。

## 已运行的前端基线验证

全部针对现有工作树运行，未修改现有前端源代码：

| 检查 | 结果 |
| --- | --- |
| `npm.cmd --prefix frontend run typecheck` | 通过 |
| `npm.cmd --prefix frontend run build` | 通过，108 个模块 |
| `npm.cmd --prefix frontend test` | 21 个测试文件、145 项测试全部通过 |

这些是 React/TypeScript 构建与单元测试，不是 ArkTS 编译、ArkWeb 模拟器或鸿蒙真机验证。

## 后续执行顺序

1. 完成官方安装向导，记录真实 IDE/SDK 路径与版本；不自行绕过 UAC。
2. 使用已安装工具的 Empty Ability 官方模板创建独立 `harmony/` 工程，记录目标 API 和最低兼容版本，不盲目把最低 API 设置为最新版本。
3. 实现 ArkUI/ArkWeb 壳层：同源 HTTPS、音频文档选择、加载失败与重试、返回、前后台与安全区。保留网页工作台和 Cookie/CSRF 安全机制。
4. 使用真实可访问的 HTTPS 部署地址；当前未提供服务器、域名及发布凭据，不伪造地址、不降低证书校验。
5. 进行 ArkTS 编译、模拟器及真实文件选择/播放测试，再安排签名与 HAP/APP 打包。
6. 明确区分源码完成、编译通过、设备验证通过、服务上线和参赛提交等状态。

## 官方资料

- [DevEco Studio 下载页](https://developer.huawei.com/consumer/cn/download/deveco-studio)
- [工具使用概述](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-tools-overview)
- [ArkWeb 加载页面](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/web-page-loading-with-web-components)
- [ArkWeb 文件上传](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/web-file-upload)

本轮未使用额度重置卡，未创建签名材料，未上传项目或提交参赛作品。
