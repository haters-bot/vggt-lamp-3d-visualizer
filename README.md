# VGGT + LaMP 建筑与相机轨迹可视化工具

交付版本：2026-11-01

本工具加载 VGGT-Omega 导出的 GLB 建筑点云及相机，按相机输入顺序拟合三维拍摄轨迹，并调用 LaMP 两图相对定位服务，在轨迹上显示连续预测位置。

## 主要功能

- 加载 GLB 点云、相机网格与相机光心
- 使用向心 Catmull–Rom 样条拟合真实视觉相机轨迹
- 自动检测建筑底面、扶正并贴合参考平面
- 常用界面只保留模型方位角和尺寸；高级校准默认折叠
- 单击轨迹任意位置生成点云模拟航拍视角并保存 PNG
- 选择两张 UAV 图片，调用远程 LaMP 服务预测相对位置
- 蓝色、橙色、绿色实心点分别表示起点、连续预测位置和 VGGT 目标位置
- 连续预测位置不使用 MAP-hard 离散帧吸附；MAP-hard 只作为文字参考
- 10 万至 100 万点的显示预算及常用显示开关

## 交付目录

```text
VGGT_LaMP_3D_Tool_20261101/
├── README.md
├── MANIFEST.sha256
├── app/                       # Windows/Linux/macOS 本地三维网页工具
├── remote_tools/              # LaMP 单次推理与常驻 HTTP 服务
└── reconstruction_inputs/
    └── building_1565_images_01_50/   # 当前界面使用的 50 张图片
```

## 本地三维工具

环境：Python 3.9 或更高版本，以及支持 WebGL 的 Chrome/Edge。Three.js 已放在 `app/vendor/`，本地界面不需要安装第三方 Python 包，也不依赖外部 CDN。

Windows PowerShell：

```powershell
cd app
.\start_windows.ps1
```

或运行：

```powershell
python .\kml_spiral_editor.py
```

默认地址：<http://127.0.0.1:7872/>

启动后选择 VGGT-Omega 导出的 `.glb` 文件。模型、相机与轨迹共享同一场景变换；不再使用 KML 生成显示曲线。

## LaMP 远程推理服务

本地三维显示可以独立运行。若要使用“两图相对定位”，远程机器还需要：

1. `vggt-pairuav-main` 项目及其 Python 环境；
2. 可导入的 `vggt` 和 `pairuav` Python 包；
3. VGGT 权重 `model.pt`；
4. LaMP challenge bundle，含三个任务头、配置和 decoder 文件；
5. 与界面对应的 50 张 UAV 图片。

已验证的 VGGT 权重 SHA-256：

```text
d15bf50a8615c8225ed48b51ea5cac673d82442ec0309036df555a053253afe0
```

把 `remote_tools/infer_lamp_pair.py` 和 `remote_tools/lamp_pair_server.py` 放入 `vggt-pairuav-main` 根目录，然后在其 Python 环境中启动：

```bash
python3 lamp_pair_server.py \
  --image-dir /path/to/building_1565_images_01_50 \
  --vggt-weight /path/to/model.pt \
  --bundle /path/to/lamp_challenge_entry_822841_v1 \
  --host 127.0.0.1 \
  --port 8765
```

健康检查：

```bash
curl http://127.0.0.1:8765/health
```

若推理在另一台电脑上运行，在本地建立 SSH 隧道：

```bash
ssh -N -L 8765:127.0.0.1:8765 USER@REMOTE_HOST
```

本地网页默认把 `/api/lamp-infer` 转发到 `http://127.0.0.1:8765/infer`。也可用 `--lamp-api-url` 指定其他服务地址。

## 不随交付包提供的文件

- VGGT `model.pt`（约 4.7 GB）
- LaMP challenge 权重/配置 bundle
- 用户重建得到的 GLB 模型
- Python 虚拟环境、缓存和临时文件

这些文件体积较大或与具体部署环境相关，应由接收方单独放置。

## 程序入口

- `app/kml_spiral_editor.py`：本地 HTTP 服务和 LaMP 请求转发
- `app/three_editor.html`：三维界面、自动贴地、轨迹及标记逻辑
- `remote_tools/lamp_pair_server.py`：常驻 LaMP 推理服务
- `remote_tools/infer_lamp_pair.py`：命令行单次两图推理

## 使用注意

- 图片编号必须与 GLB 中的相机输入顺序一致。
- 自动贴地只能确定建筑底面方向，建筑的水平朝向仍可通过“模型方位角”调整。
- 橙色预测点使用连续距离输出计算，可位于两个 VGGT 相机点之间；不会吸附到离散图片编号。
- 若浏览器仍显示旧页面，请停止并重新启动本地 Python 服务，因为 HTML 会在服务启动时载入内存。
