# MuseEcho Android 演示包

该工程为 HarmonyOS 4.2/4.3 手机提供 Android APK 演示入口，并保留 `harmony/` 下独立的 HarmonyOS NEXT 原生工程。

## 兼容目标

- `minSdk 23`（Android 6.0），低于 HarmonyOS 4.2/4.3 的 Android 兼容环境；`targetSdk 35` 不抬高最低安装版本。
- 手机与平板均支持，允许横竖屏和可调整窗口。
- 只加载 `https://museecho.toolgate.cloud`，禁止 HTTP、混合内容和跨域主导航。
- 使用系统文件选择器上传单个音频文件，不申请存储权限。

## 最快构建方式

1. 安装 Android Studio，并保留默认 Android SDK、Platform Tools 和 Build Tools。
2. 用 Android Studio 打开本目录 `android/`。
3. 等待首次 Gradle 同步完成。
4. 选择 **Build > Build Bundle(s) / APK(s) > Build APK(s)**。
5. 安装 `app/build/outputs/apk/debug/app-debug.apk`。Debug APK 已由 Android 工具链自动签名，可直接侧载演示。

正式验收前应在一台 HarmonyOS 4.2 或 4.3 真机上完成安装、启动、登录、音频选择、分析和返回键测试。Android APK 与 HarmonyOS NEXT HAP 是两个独立交付物，不能互相替代。
