# VGGT + LaMP 建筑与相机轨迹可视化工具

`feat/render-cache`：本地 GLB 点云/网格浏览、圆形 splat 与 EDL、离线 LaMP 缓存、轨迹角度放置。运行前端只需 Python 3.9+ 和支持 WebGL2 的 Chrome/Edge；不需要 CDN、npm 或第三方 Python 包。

## 启动和图片顺序

```bash
python app/kml_spiral_editor.py --image-dir /path/to/images --no-browser
```

打开 <http://127.0.0.1:7872/>，加载含点云/网格及相机锥体的 GLB。不传 `--image-dir` 时使用仓库原有的 50 张示例图片。图片按文件名中的数字元组排序，数字顺序重复或无数字时报错；支持 JPG/JPEG/PNG。图片顺序必须与 GLB 相机输入顺序相同。更换目录需重启 Python 服务。

GLB 中顶点数 5–100 的 Mesh 按输入顺序视为相机，0-based 顶点 1 是光心；大于 100 顶点的 Mesh 是模型。场景模型和相机共享同一变换。自动贴地可手动调整或保存；此浏览器显示变换不修改 GLB。

## 显示与 PNG

- 背景：原深色（默认）、黑、白；主视图、轨迹预览和导出的 PNG 同步。
- 网格/参考平面、坐标轴、检测底面默认隐藏，各有复选框；检测底面位于高级校准内。
- 圆形 splat 默认开启，片元着色器丢弃圆外像素，保留深度写入。关闭可比较旧方点；`sizeAttenuation` 开启。点大小按场景包围盒初始化，滑块单位是归一化显示场景的世界单位，随模型缩放补偿，非物理米。
- 默认显示 100 万点，上限 300 万；跨所有 Points 分配总预算并等间隔取索引。原始数据不被裁剪，源点数不足预算时显示全部。
- EDL 默认开启：本项目自写的双通道渲染，读取 DepthTexture、恢复视空间深度，对八邻域对数深度差暗化；主视图和预览共享开关。关闭后直接渲染。
- 点云、网格模型、相机、轨迹分别控制。相机开关不会隐藏网格模型。
- 单击轨迹打开模拟航拍预览；可选插值相机朝向或朝向建筑中心。选择 440×300、1280×720 或 1920×1080 后保存 PNG；导出像素不受 CSS 或屏幕 DPR 影响。

Three.js 及 GLTFLoader/BufferGeometryUtils 沿用仓库随附 r160（0.160.0，https://github.com/mrdoob/three.js/tree/r160）。本分支没有新增官方 examples 模块或外部依赖。`app/rendering.js`、`app/orbit_math.js` 是本项目代码。

## 离线预测缓存

选择“加载预测缓存 JSON”，然后选择起始图、目标图并点击预测。缓存键 `0->27` 表示图片数组中的第 0、27 项，与文件名数字不必相同。缓存命中完全不访问服务；未命中才 POST `/api/lamp-infer`。结果明确显示 `cache` / `server`；切换图片会清除旧标记。

默认 `angle on fitted orbit`：相机光心 PCA 拟合平面，在该平面最小二乘拟合圆心，沿向心 Catmull–Rom 轨迹搜索相对 source 的中心方位夹角等于 `rotation_angle_deg` 的首个连续位置。显示与目标帧方位夹角的有符号差值。

旋转测地角只有 [0°,180°]，没有转向和整圈信息。因此固定沿输入顺序选择首个交点，不借助目标帧位置选择分支；后半圈存在歧义。原轨迹是开放曲线，不自动跨首尾；前进范围无解时标记最接近的可达点并提示。角度方式假设近似等高、镜头朝向中心的绕飞，不能将任意相机旋转解释为轨道角。

`range` 保留旧规则：连续步差 = −2×range，按原拍摄步号插值，超出范围夹到端点。**range 输出未在真实图上验证**，SUES 默认使用 angle。MAP-hard 只作参考，不参与位置计算。

## 远端推理和批量缓存

在能导入 `pairuav`、`vggt` 的 PyTorch 环境中运行。推荐 PyTorch 2.7.1、CUDA、Pillow、NumPy；不要把脚本复制到只读第三方仓库，设置 `PYTHONPATH` 即可。

```bash
export PYTHONPATH=/path/to/vggt-pairuav:/path/to/vggt-pairuav/3rdparty/vggt
export CUDA_VISIBLE_DEVICES=1 PYTHONDONTWRITEBYTECODE=1 CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python remote_tools/precompute_lamp_pairs.py \
  --image-dir /path/to/images --expected-images 50 \
  --vggt-weight /path/to/model.pt --bundle /path/to/lamp_challenge_entry_822841_v1 \
  --pairs all --output-dir /path/to/NEW_run_directory
```

新目录内生成 `lamp_cache.json` 和 `progress.jsonl`。现有输出目录一律拒绝，失败后保留进度供诊断；另选新目录重跑，不自动续算或覆盖。支持 `--pairs all`（全部有序非自身对）、`--pairs ring0`（0→k）、`--pairs stride N`（i→i+N，不回绕）。50 张图片的 all 恰为 2450 对。模型和三个任务头各加载一次。

缓存包含图像顺序与 SHA256、bundle 路径、VGGT 权重 SHA256、时间、每对 heading/yaw/rotation/range、decoded 与耗时。`yaw_deg` 与原 heading 定义相同：`atan2(R[1,0], R[0,0])`；`rotation_angle_deg=degrees(acos(clip((trace(R)-1)/2,-1,1)))`。`decoded.label_index` 是 decoder 网格的 0-based 索引，不是目标帧。所有 JSON 用 `allow_nan=False` 写出。

VGGT 参数为 FP32，aggregator 在 BF16 autocast 下运行，池化特征经 FP16 再回 FP32，沿用论文特征缓存口径。固定 seed 2026 和确定性算法；同环境的预测字段可复现，`created`、`seconds` 等运行元数据自然随执行变化。默认 GPU 预算 25 GB，PyTorch allocator 限制为 24 GB，为 CUDA 上下文预留 1 GB。

```bash
python remote_tools/lamp_pair_server.py \
  --image-dir /path/to/images --vggt-weight /path/to/model.pt \
  --bundle /path/to/lamp_challenge_entry_822841_v1 --host 127.0.0.1 --port 8765
```

本地 HTTP 服务默认转发至 `http://127.0.0.1:8765/infer`，也可传 `--lamp-api-url`。远端部署时可用 `ssh -N -L 8765:127.0.0.1:8765 USER@REMOTE_HOST`。服务 API 的 `frame_a/frame_b` 为 1-based 输入序号；前端同时传图片名，服务检查顺序一致，避免回退时预测错误数据集。单对 CLI `remote_tools/infer_lamp_pair.py` 同样返回旋转测地角。

权重、虚拟环境、缓存、GLB 和测试截图不随 Git 仓库提交。Task_37 的真实数据验证、网格与截图位于其上级 Task 目录；没有 push。
