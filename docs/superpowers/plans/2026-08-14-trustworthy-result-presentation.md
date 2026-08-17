# 可信结果页呈现实施计划

> **供自主执行者使用：** 必需子技能：使用 superpowers:executing-plans 逐项实施本计划。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 保留 MuseEcho 已确立的结果页和五轨时间轴布局，同时只显示有用且有依据的音乐事实与控件。

**架构：** 仅用于呈现的过滤逻辑位于 React 功能层。后端继续存储不可变的确定性输出；前端在渲染前过滤不面向用户的结构聚类标签和不可用的和弦事件。现有时间轴选区仍独立于和弦候选。

**技术栈：** React 19、TypeScript、Vitest、Testing Library、现有 CSS 令牌系统。

## 全局约束

- 不增加依赖或 API 字段，也不在浏览器中重新运行音频分析。
- 保留当前波形、能量、事件、播放头、指针拖动、键盘定位以及起止选区行为。
- 已完成工作区中不得渲染内部 A/B/C 结构聚类标签、`unknown` 和弦块、文本事件列表、问答面板、算法标识符、任务 ID 或生命周期文案。
- 所有面向用户的音乐结论必须来自现有持久化结果数据，并通过现有置信度阈值。

---

### 任务 1：过滤地图事件并提供简洁空状态

**文件：**
- 修改：`frontend/src/features/timeline/Timeline.tsx`
- 修改：`frontend/src/features/timeline/Timeline.test.tsx`

**接口：**
- 输入：`AnalysisResult.sections`、`AnalysisResult.chords`、`isUsableConfidence()`。
- 输出：保持相同的五轨元素和选区控件，只显示可用和弦事件，不输出结构聚类标签。

- [x] **步骤 1：编写失败的组件测试**

在丰富夹具中增加断言：标签 `A` 以及低置信度/`unknown` 和弦不会在地图或无障碍文本中渲染，而已知 `G` 候选仍为按钮。再断言旧文本事件列表及其摘要不存在。

- [x] **步骤 2：运行测试并确认 RED**

运行：`vitest run src/features/timeline/Timeline.test.tsx`

预期：FAIL，因为现有地图会渲染段落标签、unknown 和弦块、文本事件列表和偏实现说明的选区文案。

- [x] **步骤 3：实施最小过滤和文案变更**

使用局部过滤数组。保留所有 SVG 和轨道布局标记。当没有稳定的面向用户段落时，将段落事件条替换为空状态标签；只为可用且非 unknown 的事件渲染和弦按钮；移除 `<details className="timeline__event-list">`；保留选区控件，但使用简洁文案“选择片段以回听和比较”。

- [x] **步骤 4：运行聚焦 GREEN 测试**

运行：`vitest run src/features/timeline/Timeline.test.tsx`

预期：PASS，且现有定位/选区行为不变。

- [ ] **步骤 5：提交**

提交消息：`fix: show only usable music events on timeline`

### 任务 2：简化 Music DNA，只讲解必要的和弦记号

**文件：**
- 修改：`frontend/src/features/dna/MusicDNA.tsx`
- 修改：`frontend/src/features/dna/MusicDNA.test.tsx`
- 修改：`frontend/src/features/chords/ChordDetails.tsx`
- 修改：`frontend/src/features/chords/ChordDetails.test.tsx`

**接口：**
- 输入：`TrackResult`、`ChordResult`、现有乐理字段。
- 输出：简洁的当前事实和选中候选详情，不含实现说明文案。

- [x] **步骤 1：编写失败的组件测试**

断言 Music DNA 不再公开来源种类或结构/和弦事件数量，且不可用的调性标记为“暂未判定”。断言和弦详情提供精简记号指南，且不显示 `deterministic-triad-theory-v1`。

- [x] **步骤 2：运行测试并确认 RED**

运行：`vitest run src/features/dna/MusicDNA.test.tsx src/features/chords/ChordDetails.test.tsx`

预期：FAIL，因为现有组件公开了来源/摘要数量和算法标识符。

- [x] **步骤 3：实施最小组件变更**

保留时长、可用 BPM、调性状态、拍点数量和能量。移除来源以及结构/和弦数量事实。在和弦详情中，用一个简洁记号指南替换算法/限制文案，并只保留持久化音乐事实。

- [x] **步骤 4：运行聚焦 GREEN 测试**

运行：`vitest run src/features/dna/MusicDNA.test.tsx src/features/chords/ChordDetails.test.tsx`

预期：PASS。

- [ ] **步骤 5：提交**

提交消息：`feat: simplify music result facts`

### 任务 3：在已完成工作区中隐藏问答

**文件：**
- 修改：`frontend/src/features/workspace/AnalysisWorkspace.tsx`
- 修改：`frontend/src/features/workspace/AnalysisWorkspace.test.tsx`
- 修改：`frontend/src/styles/global.css`

**接口：**
- 输入：已加载结果和删除面板。
- 输出：仅包含播放器、DNA、时间轴、和弦详情和保留信息的已完成工作区。

- [x] **步骤 1：编写失败的工作区测试**

断言已加载的工作区不包含“片段问答”标题或问题文本区，同时保留信息/删除交互仍可用。

- [x] **步骤 2：运行测试并确认 RED**

运行：`vitest run src/features/workspace/AnalysisWorkspace.test.tsx`

预期：FAIL，因为 `QuestionPanel` 当前会渲染。

- [x] **步骤 3：只移除未启用的 UI 集成**

从 `AnalysisWorkspace` 中移除 `QuestionPanel`、解释传输接线和查询选区回调；保留 `useTimeline`，用于同步播放器与时间轴。只在支持网格 CSS 已无其他使用者时移除它；不要删除 QuestionPanel 功能/API 代码。

- [x] **步骤 4：运行聚焦 GREEN 测试**

运行：`vitest run src/features/workspace/AnalysisWorkspace.test.tsx`

预期：PASS。

- [ ] **步骤 5：提交**

提交消息：`feat: focus completed workspace on listening`

### 任务 4：验证视觉与实时行为

**文件：**
- 修改：`docs/superpowers/specs/2026-08-14-trustworthy-result-presentation-design.md`

- [x] **步骤 1：运行相关前端套件和构建**

仅使用现有锁文件依赖，运行四个功能测试文件、类型检查和生产构建。

- [x] **步骤 2：重新构建本地开发服务**

构建现有应用/网关配置，不改动锁文件，也不下载新工具。

- [ ] **步骤 3：在 Edge 中运行保留的真实结果**

确认截图基线布局保持不变：播放器/Music DNA 概览、原五轨地图、选区滑杆和可点击的 A# 候选。确认页面中没有 A/B/C 段落标签、unknown 和弦块、文本事件列表或问答面板。

控制器说明：2026-08-14，真实 Edge 页面已选择 `C:\Users\P\Downloads\《江南烟水》随性的木鱼-流行.mp3` 并接受两项同意控件，但其受控上传请求在到达网关前停止。同一文件随后通过同一本地 HTTPS 网关被接受为分析 `f12fa6ca-66a2-4e16-9b4c-2ed078759679`，并无错误地完成。分析后的视觉复核仍待具有可用上传通道的浏览器会话执行。

- [ ] **步骤 4：提交并推送**

提交消息：`feat: refine trustworthy music results`；验证后推送专用分支。
