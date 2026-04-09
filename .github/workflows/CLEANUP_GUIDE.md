# 编译环境清理指南

## 📌 问题背景

由于缓存键配置不一致，导致不同设备的编译产物相互覆盖，造成编译环境混乱。

## ✅ 已完成的修复

### 1. 创建了清理工作流
- **文件**: `.github/workflows/cleanup_environment.yml`
- **功能**: 提供灵活的缓存、Release 和工作流记录清理功能

### 2. 修复了所有工作流的缓存隔离问题

#### 修复的文件列表：
- ✅ `.github/workflows/release_wrt_all.yml` - 批量构建工作流
- ✅ `.github/workflows/release_wrt.yml` - 单设备发布工作流
- ✅ `.github/workflows/build_wrt.yml` - 单设备构建工作流

#### 修复内容：
**修改前（❌ 错误）：**
```yaml
key: ${{ matrix.os }}-${{ hashFiles('**/repo_flag') }}-${{ env.BUILD_DATE }}
# 缺少设备标识，所有设备共享同一缓存
```

**修改后（✅ 正确）：**
```yaml
# release_wrt.yml 和 build_wrt.yml
key: ${{ matrix.os }}-${{ inputs.model }}-${{ hashFiles('**/repo_flag') }}-${{ env.BUILD_DATE }}

# release_wrt_all.yml
key: ${{ matrix.os }}-${{ matrix.model }}-${{ hashFiles('**/repo_flag') }}-${{ env.BUILD_DATE }}
# 包含设备唯一标识，每个设备独立缓存
```

---

## 🚀 清理步骤

### 第一步：执行完全清理

1. 进入 GitHub 仓库的 **Actions** 页面
2. 选择 **Cleanup Build Environment** 工作流
3. 点击 **Run workflow**
4. 配置参数：
   ```
   Cleanup Type: all
   Model Filter: (留空)
   ```
5. 点击 **Run workflow**

这将清理：
- ✅ 所有 GitHub Actions 缓存
- ✅ 所有 Release 发布
- ✅ 所有工作流运行记录
- ✅ 本地构建产物（如果存在）

### 第二步：验证清理结果

清理完成后，检查：
- [Actions Caches](https://github.com/ZqinKing/wrt_release/actions/caches) - 应该为空或很少
- [Releases](https://github.com/ZqinKing/wrt_release/releases) - 应该为空
- [Workflow Runs](https://github.com/ZqinKing/wrt_release/actions) - 只保留最近的清理记录

### 第三步：重新构建

现在可以安全地重新触发构建：
- 手动触发：**Build WRT** 或 **Release Wrt - All Models**
- 自动触发：推送代码到 master 分支

---

## 📖 清理工作流使用说明

### 清理类型说明

| 类型 | 说明 | 适用场景 |
|------|------|----------|
| `all` | 清理所有内容 | 环境严重混乱，需要完全重置 |
| `cache_only` | 仅清理缓存 | 怀疑缓存损坏或冲突 |
| `releases_only` | 仅清理 Release | 需要清理旧的发布版本 |
| `workflow_runs_only` | 仅清理工作流记录 | 减少工作流历史记录 |

### 模型过滤器说明

- **留空**: 清理所有设备的资源
- **指定设备名**: 仅清理特定设备（如 `jdcloud_ipq60xx_immwrt`）

### 示例场景

#### 场景 1: 单个设备出现问题
```
Cleanup Type: cache_only
Model Filter: jdcloud_ipq60xx_immwrt
```

#### 场景 2: 清理旧版本 Release
```
Cleanup Type: releases_only
Model Filter: (留空)
```

#### 场景 3: 完全重置环境
```
Cleanup Type: all
Model Filter: (留空)
```

---

## 🔍 缓存键设计原理

### 正确的缓存键格式

#### 单设备工作流（release_wrt.yml / build_wrt.yml）
```yaml
key: ${{ matrix.os }}-${{ inputs.model }}-${{ hashFiles('**/repo_flag') }}-${{ env.BUILD_DATE }}
```

#### 批量构建工作流（release_wrt_all.yml）
```yaml
key: ${{ matrix.os }}-${{ matrix.model }}-${{ hashFiles('**/repo_flag') }}-${{ env.BUILD_DATE }}
```

**组成部分**:
1. `${{ matrix.os }}` - 操作系统标识（ubuntu-24.04）
2. **`${{ inputs.model }}` 或 `${{ matrix.model }}`** - **设备唯一标识**（关键！）
3. `${{ hashFiles('**/repo_flag') }}` - 源码版本哈希
4. `${{ env.BUILD_DATE }}` - 构建时间戳

### 为什么需要设备标识？

| 设备 | 架构 | 工具链 | 是否兼容 |
|------|------|--------|----------|
| jdcloud_ipq60xx_* | ARM64 (IPQ60xx) | aarch64-openwrt-linux-* | ❌ |
| x64_immwrt | x86_64 | x86_64-openwrt-linux-* | ❌ |
| link_nn6000v2_* | ARM64 (MTK) | aarch64-openwrt-linux-* | ❌ |

**结论**: 不同设备的工具链完全不兼容，必须通过设备标识隔离缓存！

### 同时编译的问题演示

假设同时触发两个设备编译：

**时间线：**
```
T1: jdcloud_ipq60xx_immwrt 开始编译
    → 写入缓存: ubuntu-24.04-abc123-xxx
    
T2: x64_immwrt 开始编译（如果没有设备标识）
    → 覆盖同一缓存: ubuntu-24.04-abc123-xxx ❌
    
T3: jdcloud 读取缓存
    → 读到 x64 的工具链 💥
    
T4: 编译失败
    → error: cannot execute binary file: Exec format error
```

**修复后：**
```
T1: jdcloud_ipq60xx_immwrt 开始编译
    → 写入缓存: ubuntu-24.04-jdcloud_ipq60xx_immwrt-abc123-xxx ✅
    
T2: x64_immwrt 开始编译
    → 写入缓存: ubuntu-24.04-x64_immwrt-abc123-xxx ✅
    
T3: 两个设备各自读取自己的缓存
    → 互不干扰，编译成功 ✅
```

---

## ⚠️ 注意事项

1. **清理操作不可逆**: 删除的缓存和 Release 无法恢复
2. **首次构建会变慢**: 清理后首次构建需要重新下载所有依赖
3. **建议定期清理**: 
   - 每周清理一次旧 Release（保留最近 2-3 个版本）
   - 每月清理一次工作流记录
   - 缓存会自动管理，无需手动清理

4. **监控缓存命中率**: 
   - 在构建日志中查看 "Cache restored from key" 表示命中
   - 查看 "Cache not found for input key" 表示未命中（正常，首次构建）

5. **同时编译安全性**: 
   - ✅ 修复后可以安全地同时编译多个设备
   - ✅ 每个设备使用独立的缓存空间
   - ✅ 不会发生工具链冲突

---

## 🛠️ 故障排查

### 问题 1: 清理工作流权限不足
**症状**: `gh cache delete` 返回 403 错误  
**解决**: 确保工作流有 `actions: write` 权限（已配置）

### 问题 2: 缓存删除失败
**症状**: 显示 "✗ Failed"  
**解决**: 
- 检查 GitHub Token 权限
- 手动在 Actions → Caches 页面删除

### 问题 3: 编译仍然失败
**症状**: 清理后重新构建仍失败  
**解决**:
1. 确认所有工作流文件已正确修复（包含设备标识）
2. 检查 `.ini` 配置文件是否正确
3. 查看详细构建日志定位具体错误

### 问题 4: 同时编译时某个设备失败
**症状**: 单独编译成功，但同时编译时失败  
**解决**:
1. 检查缓存键是否包含设备标识
2. 运行清理工作流清除旧缓存
3. 重新触发构建

---

## 📊 最佳实践

1. **开发阶段**: 使用 `build_wrt.yml` 单设备测试
2. **发布阶段**: 使用 `release_wrt_all.yml` 批量构建
3. **维护阶段**: 定期运行 `cleanup_environment.yml` 保持环境整洁
4. **监控**: 关注缓存命中率和构建成功率
5. **并发控制**: 
   - 修复后可以安全地同时编译多个设备
   - 如需限制并发数，可在工作流中添加 `max-parallel` 设置

---

## 📝 修复历史

### 2026-04-09
- ✅ 创建清理工作流 `cleanup_environment.yml`
- ✅ 修复 `release_wrt_all.yml` 缓存键（添加 `matrix.model`）
- ✅ 修复 `release_wrt.yml` 缓存键（添加 `inputs.model`）
- ✅ 修复 `build_wrt.yml` 缓存键（添加 `inputs.model`）
- ✅ 同步更新所有缓存清理逻辑

---

**最后更新**: 2026-04-09  
**维护者**: ZqinKing