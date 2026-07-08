# 更新日志

## 0.1.11

### zh-CN

- 维护发布，整理安装包版本标记
- 未引入新的用户侧功能

### en-US

- Maintenance release for installer version metadata
- No new user-facing features

## 0.1.10

### zh-CN

- 维护发布，整理安装包版本标记
- 未引入新的用户侧功能

### en-US

- Maintenance release for installer version metadata
- No new user-facing features

## 0.1.9

### zh-CN

- 新增应用内中英文界面切换，主要页面文案已完成双语适配
- 将配置、额度缓存和指令模板索引迁移到 SQLite，减少本地状态文件不一致

### en-US

- Added in-app Chinese and English language switching across the main interface
- Migrated config, usage cache, and instruction template indexes to SQLite

## 0.1.8

### zh-CN

- 优化安装包体积，确保 Gitee Release 可直接上传
- 调整打包依赖，减少无关文件进入安装包

### en-US

- Reduced installer size and ensured Gitee Release can upload it directly
- Adjusted packaging dependencies to keep unrelated files out of the installer

## 0.1.7

### zh-CN

- 发版时同步上传 Gitee Release
- 设置页新增 Gitee 项目入口
- 优化发布说明生成逻辑

### en-US

- Added Gitee Release upload during publishing
- Added a Gitee project link on the Settings page
- Improved release note generation

## 0.1.6

### zh-CN

- 启动时的自动更新检查改为静默处理，已是最新版本时不再打扰用户
- 手动点击“检查更新”仍会给出明确结果，方便确认当前安装状态

### en-US

- Made startup update checks silent when the app is already up to date
- Kept manual update checks explicit so users can confirm the current install state

## 0.1.5

### zh-CN

- 完整接入应用内更新流程，发现新版本后可在弹窗中下载、查看进度并重启安装
- 设置页加入版本信息、手动检查更新和 GitHub 项目入口
- 更新弹窗开始读取发布日志中的真实更新内容，避免展示固定文案

### en-US

- Added the full in-app update flow with download, progress, and restart-to-install
- Added version info, manual update checks, and the GitHub project link to Settings
- Made the update dialog read real release notes instead of fixed placeholder text

## 0.1.4

### zh-CN

- 维护发布，整理安装包版本标记
- 未引入新的用户侧功能

### en-US

- Maintenance release for installer version metadata
- No new user-facing features

## 0.1.3

### zh-CN

- 维护发布，修正应用版本号
- 未引入新的用户侧功能

### en-US

- Maintenance release to correct the app version
- No new user-facing features

## 0.1.2

### zh-CN

- 接入 GitHub Release 更新源，为后续自动更新能力打基础
- 优化启动加载体验，减少进入应用时的等待感
- 改进账号额度缓存和刷新逻辑，额度状态展示更稳定

### en-US

- Added GitHub Release as the update source for future auto-update support
- Improved startup loading to reduce wait time before entering the app
- Improved account usage cache and refresh logic for more stable status display

## 0.1.1

### zh-CN

- 简化 Windows 安装包构建流程，移除不必要的 Cython 编译步骤
- 调整发布脚本，避免本地构建时误触发发布

### en-US

- Simplified the Windows installer build by removing the unnecessary Cython step
- Adjusted release scripts to avoid accidental publishing during local builds

## 0.1.0

### zh-CN

- 首个公开安装包版本，提供 Codex 多账号资料管理和一键启动能力
- 支持账号授权导入、配置文件管理、指令模板管理和额度状态查看
- 建立 Windows 安装包的自动构建与发布流程

### en-US

- First public installer release with Codex multi-account profile management and one-click launch
- Added account auth import, config management, instruction templates, and usage status display
- Established automated Windows installer build and release flow
