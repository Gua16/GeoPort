# GeoPort 简洁离线模式

默认入口是简洁模式；底部的“打开地图模式”保留原地图入口。简洁模式的 HTML、CSS、JavaScript 全部本地加载，页面初始化不请求互联网服务。设备扫描在界面加载后另行发起。

## 使用步骤

1. 输入纬度和经度，点击“保存基准”。保存配置可以在未连接设备时完成。
2. 半径默认为 300 米，修改并离开输入框后自动保存；允许 0–100,000 米。
3. 连接已配对并解锁的 iPhone；首次配对请使用 USB。开发者模式未开启时会提示，用户可主动启用，按设备提示完成后重新连接。
4. 点击“随机偏移”，向设备提交一次新坐标。每次均从已保存的基准计算，不使用上次随机结果，不启动定时移动。
5. “设置基准坐标”恢复到保存的坐标；“停止模拟”向设备清除模拟定位；“断开”先停止，再释放连接。

随机偏移使用球面正算，距离按 `radius * sqrt(random())` 采样，方向随机，支持跨日期变更线和极点。半径为零时使用基准坐标。

地图选点、手动输入、搜索和路线界面继续保留。地图的“保存为基准坐标”按钮是显式持久化入口；单纯移动地图标记或执行路线操作不会改变保存的基准。地图和简洁模式共用定位服务。在线地图、搜索、油价、版本与公告仍需要相应网络服务，油价和公告后台加载，不阻塞地图 HTML 返回。

## 配置与状态

配置文件为用户配置目录中的 `GeoPort/config.json`：

| 系统 | 默认位置 |
| --- | --- |
| Windows | `%APPDATA%\GeoPort\config.json` |
| macOS | `~/Library/Application Support/GeoPort/config.json` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/GeoPort/config.json` |

可设置 `GEOPORT_CONFIG_DIR` 指定完整配置目录；此时文件位于该目录的 `config.json`。云机启动说明使用 `/workspace/geoport-env/user-config`，避免只读用户目录。使用管理员身份运行时，确认配置目录仍指向你希望使用的同一位置。

```json
{
  "schema_version": 1,
  "base_location": null,
  "random_radius_m": 300,
  "ui_mode": "lite"
}
```

保存通过临时文件、刷新和原子替换完成。失败时保留此前文件及内存配置。配置损坏或版本不支持时，显示提示并使用默认值；原文件在用户再次显式保存前保持原样。

`base_location` 始终是用户保存的坐标。`current_location` 只在设备调用成功后更新，不持久化为有效定位。重启不自动连接设备或应用坐标。设备状态表示最近一次已确认操作，闲置时拔出设备不会立即被后台状态轮询证明；后续失败会取消连接状态并清除当前定位显示，需要重新连接。

定位会话只在首次设置或主动停止时建立，同一 DVT 会话复用于多次更新。停止和断开等待清除及上下文释放完成；刚重新连接但未设置坐标的设备，也会执行实际清除。一个设备同时只能执行一个定位或连接操作，重复请求返回 HTTP 409。

## 启动与测试

需要 Python 3.12。安装依赖使用仓库的带哈希锁定文件：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python src/main.py
```

Windows 对应命令：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.venv\Scripts\python.exe src/main.py
```

如果本机没有兼容的原生扩展 wheel，安装需要对应平台的编译工具。依赖版本与传输接口已在当前 Linux 云机验证；Windows、macOS 和实体设备尚需验收。旧设备可能需开发者镜像下载，首次配对、驱动、开发者模式或 iOS 隧道初始化并不保证离线可完成。

保留 `--no-browser`、`--port`、`--wifihost` 和 `--udid`。新增 `--ui-mode lite|map`，优先于保存的启动界面偏好。服务默认只监听 `127.0.0.1`，关闭 Debug 和自动重载。若指定端口被占用，会选择备用端口，查看终端输出。

自动化测试不需要 iPhone：

```sh
.venv/bin/python -m unittest discover -s tests -v
```

可选浏览器验收需要 Playwright 和已安装的 Chromium，设置 `GEOPORT_TEST_PYTHON` 指向应用虚拟环境、`GEOPORT_TEST_CHROMIUM` 指向浏览器，然后运行 `python tests/browser_smoke.py`。该测试只启动独立的模拟设备测试服务器，不能代替实机验证，也不能用 `tests/browser_server.py` 启动正式应用。

## 接口

| 方法与路径 | 用途 |
| --- | --- |
| `GET /health` | 本地就绪检查，无网络或设备扫描 |
| `GET /api/settings` | 配置和运行状态；`error` 可能是上次设备错误，不代表读取配置失败 |
| `PUT /api/settings` | 修改 `random_radius_m`、`ui_mode` |
| `PUT /api/base-location` | 显式保存 `{ "lat": 23.1291, "lng": 113.2644 }` |
| `POST /api/location/apply` | `{ "mode": "base" }` 或 `{ "mode": "random" }` |
| `POST /api/device/disconnect` | 停止模拟并释放设备与隧道 |
| `GET /api/online-status` | 仅地图使用，读取后台油价/公告状态 |

原有 `/list_devices`、`/connect_device`、`/set_location`、`/update_location`、`/stop_location` 等入口保留。`/set_location` 支持直接传坐标，地图使用此形式避免“先选点、再应用”两次请求之间的竞争。输入错误返回 400；忙碌或前置条件不满足返回 409；设备操作失败返回 502；本地文件写入失败返回 503。成功消息只在设备库调用成功返回后显示，实际 iOS 上的定位效果仍需观察确认。
