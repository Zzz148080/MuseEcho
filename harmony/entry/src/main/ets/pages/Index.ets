/*
 * Copyright (c) 2026 Huawei Device Co., Ltd.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { webview } from '@kit.ArkWeb';
import { picker } from '@kit.CoreFileKit';
import { SERVICE_ORIGIN } from '../config/ServiceConfig';
import { isAllowedNavigation, normalizeServiceOrigin } from '../security/OriginPolicy';

@Entry
@Component
struct Index {
  @State address: string = SERVICE_ORIGIN;
  @State origin: string = '';
  @State progress: number = 0;
  @State loading: boolean = true;
  @State failure: string = '';
  @State notice: string = '';
  @StorageLink('appForeground') @Watch('foregroundChanged') foreground: boolean = true;
  private controller: webview.WebviewController = new webview.WebviewController();
  private attached: boolean = false;
  private pendingPicker: FileSelectorResult | undefined = undefined;
  private timeoutId: number = -1;

  aboutToAppear(): void {
    if (SERVICE_ORIGIN !== '') {
      this.connect();
    }
  }

  aboutToDisappear(): void {
    this.clearLoadTimeout();
    this.completePicker([]);
    this.pauseMedia();
  }

  foregroundChanged(): void {
    if (!this.attached) {
      return;
    }
    try {
      if (this.foreground) {
        this.controller.onActive();
      } else {
        this.pauseMedia();
        this.controller.onInactive();
      }
    } catch (_) {
      // Controller can detach while the ability is being destroyed.
    }
  }

  onBackPress(): boolean {
    if (this.attached) {
      try {
        if (this.controller.accessBackward()) {
          this.controller.backward();
          return true;
        }
      } catch (_) {
        return false;
      }
    }
    this.pauseMedia();
    return false;
  }

  private pauseMedia(): void {
    if (this.attached) {
      try {
        this.controller.pauseAllMedia();
      } catch (_) {
        // Never automatically resume audio when returning to the foreground.
      }
    }
  }

  private clearLoadTimeout(): void {
    if (this.timeoutId !== -1) {
      clearTimeout(this.timeoutId);
      this.timeoutId = -1;
    }
  }

  private startLoadTimeout(): void {
    this.clearLoadTimeout();
    this.timeoutId = setTimeout(() => {
      if (this.loading) {
        this.fail('连接超时。请检查网络或服务状态，然后重试。');
      }
    }, 30000);
  }

  private fail(message: string): void {
    this.failure = message;
    this.loading = false;
    this.clearLoadTimeout();
    this.pauseMedia();
    this.completePicker([]);
  }

  private connect(): void {
    const normalized = normalizeServiceOrigin(this.address);
    if (normalized === '') {
      this.failure = '请输入有效的 HTTPS 域名，不含路径、账号或参数。仅支持标准 443 端口。';
      return;
    }
    this.failure = '';
    this.loading = true;
    this.progress = 0;
    this.origin = normalized;
    this.startLoadTimeout();
  }

  private retry(): void {
    this.failure = '';
    this.notice = '';
    this.loading = true;
    this.progress = 0;
    this.startLoadTimeout();
    try {
      this.controller.loadUrl(this.origin);
    } catch (_) {
      this.fail('网页组件尚未就绪，请关闭并重新打开应用。');
    }
  }

  private completePicker(files: string[]): void {
    const result = this.pendingPicker;
    this.pendingPicker = undefined;
    if (result !== undefined) {
      try {
        result.handleFileList(files);
      } catch (_) {
        // The page may have been destroyed while a system picker was open.
      }
    }
  }

  private changeService(): void {
    this.pauseMedia();
    this.clearLoadTimeout();
    this.completePicker([]);
    this.attached = false;
    this.origin = '';
    this.failure = '';
    this.notice = '';
    this.controller = new webview.WebviewController();
  }

  private async selectAudio(result: FileSelectorResult): Promise<void> {
    if (this.pendingPicker !== undefined) {
      result.handleFileList([]);
      return;
    }
    this.pendingPicker = result;
    const options = new picker.DocumentSelectOptions();
    options.maxSelectNumber = 1;
    options.fileSuffixFilters = ['音频|.wav,.mp3,.flac,.m4a,.aac,.ogg,.opus'];
    try {
      const context = this.getUIContext().getHostContext();
      if (context === undefined) {
        this.completePicker([]);
        return;
      }
      const files = await new picker.DocumentViewPicker(context).select(options);
      if (this.pendingPicker === result) {
        this.completePicker(files.slice(0, 1));
      }
    } catch (_) {
      if (this.pendingPicker === result) {
        this.completePicker([]);
        this.notice = '未选择文件。可以重新打开文件选择器。';
      }
    }
  }

  build() {
    Column() {
      Row() {
        Text('MuseEcho').fontSize(22).fontWeight(FontWeight.Bold).fontColor('#303b4b')
        Blank()
        Text('音乐分析工作台').fontSize(13).fontColor('#536174')
      }.width('100%').padding({ left: 20, right: 20, top: 12, bottom: 12 })

      if (this.origin === '') {
        Scroll() {
          Column({ space: 18 }) {
            Text('让音乐的结构，清晰可见。').fontSize(28).fontWeight(FontWeight.Bold).fontColor('#303b4b')
            Text('连接你的 MuseEcho 服务，开始上传、分析与聆听。音频分析在服务端完成。')
              .fontSize(16).fontColor('#536174').lineHeight(26)
            Text('服务地址').fontSize(15).fontColor('#303b4b').width('100%')
            TextInput({ text: this.address, placeholder: '输入已部署的 HTTPS 域名' })
              .height(52).fontSize(16).backgroundColor('#ffffff').borderRadius(10)
              .onChange((value: string) => { this.address = value; })
              .accessibilityText('MuseEcho HTTPS 服务地址')
            if (this.failure !== '') {
              Text(this.failure).fontSize(15).fontColor('#b33a3a').width('100%')
            }
            Button('连接工作台').width('100%').height(48).borderRadius(12)
              .backgroundColor('#526fa8').onClick(() => { this.connect(); })
            Text('开发连接模式：只连接你信任的服务。地址仅在本次运行使用；选择文件不会跳过网页的上传授权。')
              .fontSize(14).fontColor('#627086').lineHeight(23)
            Text('支持 WAV、MP3、FLAC、M4A、AAC、OGG、OPUS。上限 256 MiB、10 分钟；大文件会自动分片，实际编码由服务端验证。')
              .fontSize(14).fontColor('#627086').lineHeight(23)
          }.width('100%').constraintSize({ maxWidth: 560 }).padding(24).alignItems(HorizontalAlign.Start)
        }.layoutWeight(1).width('100%')
      } else {
        if (this.loading) {
          Progress({ value: this.progress, total: 100, type: ProgressType.Linear })
            .width('100%').color('#526fa8').accessibilityText('网页加载进度')
        }
        if (this.notice !== '') {
          Text(this.notice).fontSize(14).fontColor('#536174').padding(12).width('100%')
        }
        Stack() {
          Web({ src: this.origin, controller: this.controller })
            .width('100%').height('100%')
            .javaScriptAccess(true).domStorageAccess(true).fileAccess(false)
            .mixedMode(MixedMode.None).mediaPlayGestureAccess(true)
            .multiWindowAccess(false)
            .onControllerAttached(() => { this.attached = true; })
            .onProgressChange((event: OnProgressChangeEvent) => { this.progress = event.newProgress; })
            .onPageBegin(() => {
              this.completePicker([]);
              this.loading = true;
              this.startLoadTimeout();
            })
            .onPageEnd(() => { this.loading = false; this.clearLoadTimeout(); })
            .onLoadIntercept((event: OnLoadInterceptEvent) => {
              if (!event.data.isMainFrame()) {
                return false;
              }
              const allowed = isAllowedNavigation(event.data.getRequestUrl(), this.origin);
              if (!allowed) {
                this.notice = '已阻止跳转到其他网站。';
              }
              return !allowed;
            })
            .onSslErrorEventReceive((event: OnSslErrorEventReceiveEvent) => {
              event.handler.handleCancel();
              this.fail('服务证书无效，已停止连接。请配置受信任的 HTTPS 证书。');
            })
            .onErrorReceive((event: OnErrorReceiveEvent) => {
              if (event.request.isMainFrame()) {
                this.fail('暂时无法加载工作台。请检查网络和服务地址。');
              }
            })
            .onHttpErrorReceive((event: OnHttpErrorReceiveEvent) => {
              if (event.request.isMainFrame()) {
                this.fail('服务返回错误，请稍后重试。');
              }
            })
            .onRenderExited(() => { this.fail('网页进程已退出，请重新打开应用。'); })
            .onShowFileSelector((event: OnShowFileSelectorEvent) => {
              this.selectAudio(event.result);
              return true;
            })
          if (this.failure !== '') {
            Column({ space: 20 }) {
              Text('工作台暂不可用').fontSize(24).fontWeight(FontWeight.Bold).fontColor('#303b4b')
              Text(this.failure).fontSize(16).fontColor('#536174').lineHeight(26)
              Button('重新连接').height(48).padding({ left: 24, right: 24 })
                .backgroundColor('#526fa8').onClick(() => { this.retry(); })
              if (SERVICE_ORIGIN === '') {
                Button('修改服务地址').height(48).padding({ left: 24, right: 24 })
                  .backgroundColor('#e8effa').fontColor('#405b91').onClick(() => { this.changeService(); })
              }
            }.width('100%').height('100%').justifyContent(FlexAlign.Center)
              .padding(28).backgroundColor('#f5f7fa')
          }
        }.layoutWeight(1).width('100%')
      }
    }.width('100%').height('100%').backgroundColor('#f5f7fa')
  }
}
