# 当前状态

## 完成
- 2026-10-12 Codex：完成 macOS USB 隧道源码修复，负责 `src/main.py`、`tests/test_tunnel.py`、`docs/MACOS_TEST.md`、`README.md`。基于测试包 commit `5d35a87e78f53e78bf92efe37c751f70330be18d`，本地分支 `fix/device-tunnel-errors`，未推送。

## 进行中
- 2026-10-12 Codex：用户授权替换本机应用并更新 GitHub。构建 0.1.1 (2)，验证打包程序、备份原应用、替换 `/Applications/GeoPort Lite.app`；负责 `packaging/macos/GeoPortLite.spec` 与发布验证文档。GitHub 使用修复分支和 PR，目标为当前 macOS 测试包分支。

## 已验证
- 2026-10-12 Codex：Mac 为 macOS 27.0.1 (26A434)，USB iPhone 为 iOS 27.0.1 (24A446)。安装包以普通用户运行；用户属于 admin 组。
- 2026-10-12 Codex：源码 TCP 线程捕获异常后返回 Flask 响应，连接请求无法收到线程返回值；TCP 路径没有恢复 remoted。
- 2026-10-12 Codex：未修复源码捕获真实 traceback：暂停 remoted 权限不足，约 3 ms 内失败，页面延迟 30 秒显示超时。修复后相同设备普通权限在 0.133 秒返回真实 AccessDeniedError。
- 2026-10-12 Codex：线程 Future 传递就绪或失败；所有隧道入口共享异常和恢复逻辑；保留 30 秒上限；取消启动不发布过期 RSD；USB TCP 复用 lockdown；清理失败不覆盖原异常。
- 2026-10-12 Codex：36 项 unittest 通过，git diff --check 通过。权限、原异常原因、握手失败、同步和异步服务创建失败、清理失败、成功恢复及取消启动有回归覆盖。
- 2026-10-12 Codex：用户在本机 Terminal 输入 sudo 密码后，USB 连接在 0.320 秒成功。基准设置、5 次随机偏移、基准恢复、停止模拟通过真实设备服务；断开后再次连接、设置和停止通过。最终设备已断开、模拟已停止、remoted 未暂停。

## 未验证
- 2026-10-12 Codex：手机地图画面与恢复后的真实 GPS 坐标未目视验证。Wi-Fi、旧 iOS QUIC 未做实机验证。
- 2026-10-12 Codex：未重建或替换 `/Applications/GeoPort Lite.app`；修复通过源码启动。

## 交付与接续
- 2026-10-12 Codex：启动脚本、补丁和验证说明保存在当前聊天的 `outputs/`。原始复现日志及设备命令结果保存在 `work/`，不包含密码或配对密钥。
- 下一步第一个动作：运行 `outputs/Start GeoPort Debug.command` 启动修复源码，或按 `packaging/` 脚本重建应用。默认使用隔离测试配置及端口 54322。
- sudo 密码只由用户在本机终端输入。不修改系统安全设置。2026-10-12 用户已授权本次替换应用和 GitHub 推送。`/stop_location` 返回文本；自动验证应读取随后 `/api/settings` 的状态，不把文本响应当成 JSON。
