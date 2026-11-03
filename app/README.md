# 本地三维界面

完整说明见 [仓库 README](../README.md)。

```bash
python kml_spiral_editor.py --image-dir /path/to/images --no-browser
```

打开 <http://127.0.0.1:7872/>：

1. 加载 GLB。相机锥体必须按输入顺序，顶点 1 为光心。
2. 在“显示”选择背景、点预算、点大小及 EDL；网格、坐标轴和检测底面默认隐藏。
3. 加载 `lamp_cache.json`，选择两张图后点击预测，检查结果来源。默认 angle；range 真实图输出尚未验证。
4. 单击轨迹打开预览，选择分辨率并保存 PNG。主视图和导出背景一致。
5. 网格 GLB 的模型与相机有独立图层开关；点云 GLB 可用圆形 splat 开关比较方点。

`vendor/` 沿用 Three.js r160；本分支不增加 CDN/npm 依赖。`rendering.js` 是本地 splat/EDL 实现，`orbit_math.js` 是本地轨道几何及缓存校验。服务启动时载入 HTML，修改后重启服务。
