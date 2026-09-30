# MuseEcho 安装说明

## HarmonyOS 6.0 平板/手机

- 使用 `app/MuseEcho-HarmonyOS-NEXT-signed.hap`。
- 最低兼容版本为 HarmonyOS 6.0 / API 20；不能安装到 HarmonyOS 4.2/4.3。
- 当前 HAP 是 DevEco Studio 自动签名的调试包，已在 HUAWEI MatePad Air（HarmonyOS 6.0）真机完成安装、启动和网页加载验收，无需上架应用市场。
- 调试签名的 Provisioning Profile 与已登记测试设备关联；若安装到其他 HarmonyOS NEXT 设备，需要在同一开发者账号中登记该设备并重新生成签名包。

## HarmonyOS 4.2/4.3 手机

- 使用 `app/MuseEcho-Android-HarmonyOS4.2-4.3-demo.apk`。
- 这是 Android 兼容 APK：`minSdk 23`、`targetSdk 35`，采用 v1/v2 APK 签名，可侧载到仍支持 Android APK 的 HarmonyOS 4.2/4.3 手机。
- 在手机文件管理器中打开 APK，按系统提示允许本次来源安装。首次演示前请实机完成启动、登录、音频选择、分析、播放和返回键验收。

两个应用都连接 `https://museecho.toolgate.cloud`。`videos/` 目录留给网页端、手机端和平板端演示视频。
