# VGGT + LaMP 建筑与相机轨迹可视化工具

`feat/render-cache`：本地 GLB 点云/网格浏览、圆形 splat 与 EDL、离线 LaMP 缓存、轨迹角度放置。运行前端只需 Python 3.9+ 和支持 WebGL2 的 Chrome/Edge；不需要 CDN、npm 或第三方 Python 包。

## 启动和图片顺序

```bash
python app/kml_spiral_editor.py --no-browser
```

打开 <http://127.0.0.1:7872/>，加载含点云/网格及相机锥体的 GLB。程序会计算 GLB 的 SHA-256，并为固定模型库自动切换真实输入图片：8 图 `building_1565` 模型使用前 8 张，50 图模型分别匹配 `building_1565`、`building_0839` 和 `building_1374`。文件改名不影响识别；未登记模型会明确提示并回退到默认图片，不会声称已经匹配。

如需绕过固定模型库，可传 `--image-dir /path/to/images`。图片按文件名中的数字元组排序，数字顺序重复或无数字时报错；支持 JPG/JPEG/PNG。自定义图片顺序必须与 GLB 相机输入顺序相同。

GLB 中顶点数 5–100 的 Mesh 按输入顺序视为相机，0-based 顶点 1 是光心；大于 100 顶点的 Mesh 是模型。场景模型和相机共享同一变换。自动贴地可手动调整或保存；此浏览器显示变换不修改 GLB。

## 显示与 PNG

- 背景：暖白学术画布（默认）、原深色、黑、纯白；主视图、轨迹预览和导出的 PNG 同步。界面采用暖白纸张、石墨文字和细灰分隔线，起点、实际终点、预测分别使用低饱和学术蓝、鼠尾草绿和赭金。
- 网格/参考平面、坐标轴、检测底面默认隐藏，各有复选框；检测底面位于高级校准内。
- 圆形 splat 默认开启，片元着色器丢弃圆外像素，保留深度写入。关闭可比较旧方点；`sizeAttenuation` 开启。点大小按场景包围盒初始化，滑块单位是归一化显示场景的世界单位，随模型缩放补偿，非物理米。
- 默认显示 100 万点，上限 300 万；跨所有 Points 分配总预算并等间隔取索引。原始数据不被裁剪，源点数不足预算时显示全部。
- EDL 默认开启：本项目自写的双通道渲染，读取 DepthTexture、恢复视空间深度，对八邻域对数深度差暗化；主视图和预览共享开关。关闭后直接渲染。
- 点云、网格模型、相机、轨迹分别控制。相机开关不会隐藏网格模型。
- 50 个普通相机以低透明度线框视锥显示；预测后高亮蓝色起始视锥、绿色实际终止视锥和橙色预测视锥，并从起点分别连接实际终点和预测位置。
- 预测完成后，在三只高亮视锥附近点击会优先吸附到对应视角，并精确更新黄色选择标记和航拍预览；吸附使用屏幕像素容差，不受场景缩放影响。
- 主视图底部提供50图时间轴：第一次点击选择蓝色起点，第二次点击选择绿色终点并自动预测，完成后显示橙色连续预测点；悬停时间轴可预览对应图片，第三次点击开始下一组选择。
- 拟合轨迹使用无发光的期刊蓝灰渐变管状几何；从 image-01 端较深较粗地开始，沿输入顺序平滑变细变浅到 image-50 端，不依赖浏览器通常无效的线宽设置。
- 单击轨迹打开模拟航拍预览；可选插值相机朝向或朝向建筑中心。选择 440×300、1280×720 或 1920×1080 后保存 PNG；导出像素不受 CSS 或屏幕 DPR 影响。

Three.js 及 GLTFLoader/BufferGeometryUtils 沿用仓库随附 r160（0.160.0，https://github.com/mrdoob/three.js/tree/r160）。本分支没有新增官方 examples 模块或外部依赖。`app/rendering.js`、`app/orbit_math.js` 是本项目代码。

## 离线预测缓存

选择已登记的 GLB 后，页面按模型内容指纹同时切换对应实拍图，并从 `prediction_caches/` 自动加载该模型的缓存 JSON。缓存键 `0->27` 表示图片数组中的第 0、27 项，与文件名数字不必相同。已登记模型只使用自己的缓存：缓存文件缺失或图片对未命中时明确提示，不会回退到另一建筑的远程服务。手动缓存文件选择器保留为调试覆盖入口。预测完成后自动打开预测视角的点云预览。

缓存文件名与模型映射记录在 `MODEL_IMAGE_PROFILES`，当前期望 `building_1565_images_01_08.lamp_cache.json`、`building_1565_images_01_50.lamp_cache.json`、`building_0839_images_01_50.lamp_cache.json` 和 `building_1374_images_01_50.lamp_cache.json`。缓存生成后复制到 `prediction_caches/`，重启本地应用即可自动使用。

默认 `angle on fitted orbit`：相机光心 PCA 拟合平面，在该平面最小二乘拟合圆心，沿向心 Catmull–Rom 轨迹搜索相对 source 的中心方位夹角等于 `rotation_angle_deg` 的首个连续位置。显示与目标帧方位夹角的有符号差值。

旋转测地角只有 [0°,180°]，没有转向和整圈信息。因此固定沿输入顺序选择首个交点，不借助目标帧位置选择分支；后半圈存在歧义。原轨迹是开放曲线，不自动跨首尾；前进范围无解时标记最接近的可达点并提示。角度方式假设近似等高、镜头朝向中心的绕飞，不能将任意相机旋转解释为轨道角。

`range` 保留旧规则：连续步差 = −2×range，按原拍摄步号插值，超出范围夹到端点。**range 输出未在真实图上验证**，SUES 默认使用 angle。MAP-hard 只作参考，不参与位置计算。

## 远端推理和批量缓存

在能导入 `pairuav`、`vggt` 的 PyTorch 环境中运行。推荐 PyTorch 2.7.1、CUDA、Pillow、NumPy；不要把脚本复制到只读第三方仓库，设置 `PYTHONPATH` 即可。

```bash
export PYTHONPATH=/path/to/vggt-pairuav:/path/to/vggt-pairuav/3rdparty/vggt
export CUDA_VISIBLE_DEVICES=0 PYTHONDONTWRITEBYTECODE=1 CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python remote_tools/precompute_lamp_pairs.py \
  --image-dir /path/to/images --expected-images 50 \
  --vggt-weight /path/to/model.pt --bundle /path/to/lamp_challenge_entry_822841_v1 \
  --pairs all --output-dir /path/to/NEW_run_directory
```

新目录内生成 `lamp_cache.json` 和 `progress.jsonl`。现有输出目录一律拒绝，失败后保留进度供诊断；另选新目录重跑，不自动续算或覆盖。支持 `--pairs all`（全部有序非自身对）、`--pairs ring0`（0→k）、`--pairs stride N`（i→i+N，不回绕）。50 张图片的 all 恰为 2450 对。模型和三个任务头各加载一次。

缓存包含图像顺序与 SHA256、bundle 路径、VGGT 权重 SHA256、时间、每对 heading/yaw/rotation/range、decoded 与耗时。`yaw_deg` 与原 heading 定义相同：`atan2(R[1,0], R[0,0])`；`rotation_angle_deg=degrees(acos(clip((trace(R)-1)/2,-1,1)))`。`decoded.label_index` 是 decoder 网格的 0-based 索引，不是目标帧。所有 JSON 用 `allow_nan=False` 写出。

VGGT 参数为 FP32，aggregator 在 BF16 autocast 下运行，池化特征经 FP16 再回 FP32，沿用论文特征缓存口径。固定 seed 2026 和确定性算法；同环境的预测字段可复现，`created`、`seconds` 等运行元数据自然随执行变化。GPU 预算默认按检测到的显存减去 1 GB 自动设置，也可用 `--max-memory-gb` 指定，因此兼容当前 8 GB RTX 4060。

```bash
python remote_tools/lamp_pair_server.py \
  --image-dir /path/to/images --vggt-weight /path/to/model.pt \
  --bundle /path/to/lamp_challenge_entry_822841_v1 --host 127.0.0.1 --port 8765
```

本地 HTTP 服务默认转发至 `http://127.0.0.1:8765/infer`，也可传 `--lamp-api-url`。远端部署时可用 `ssh -N -L 8765:127.0.0.1:8765 USER@REMOTE_HOST`。服务 API 的 `frame_a/frame_b` 为 1-based 输入序号；前端同时传图片名，服务检查顺序一致，避免回退时预测错误数据集。单对 CLI `remote_tools/infer_lamp_pair.py` 同样返回旋转测地角。

权重、虚拟环境、GLB 和测试截图不随 Git 仓库提交。`prediction_caches/` 已包含固定模型库对应的四份真实离线预测缓存；重新生成时须沿用约定文件名，并通过图片顺序、数量与 SHA-256 校验后再替换。
