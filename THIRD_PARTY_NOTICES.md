# Third-party notices

## basketikun/infinite-canvas

- 项目：https://github.com/basketikun/infinite-canvas
- 参考版本：`e856c878e0a34651bb828e28f0af20d71016a7d4`
- 许可证：MIT
- 参考范围：节点式创作交互、世界坐标与视口变换、鼠标位置锚定缩放、SVG 连线、生成节点与结果的关联，以及画布结构和媒体文件分离保存。
- 主要参考文件：`web/src/components/canvas/infinite-canvas.tsx`、`web/src/components/canvas/canvas-connections.tsx`、`web/src/types/canvas.ts`、`docs/content/docs/development/canvas-data-structure.zh-CN.mdx`。
- Easy Painter 对应实现：`frontend/src/lib/canvas/`、`frontend/src/components/canvas/`、`frontend/src/pages/CanvasPage.vue`。已适配 Vue 3、现有用户与生成接口，并新增本地保存冲突检查、VIP 云端权限及服务端素材管理。

以下保留上游许可全文：

```text
MIT License

Copyright (c) 2026 basketikun

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## @noble/hashes

- 项目：https://github.com/paulmillr/noble-hashes
- 依赖版本：`2.4.0`（MIT）
- 用途：浏览器缺少 Web Crypto `subtle` 时，在本地计算素材 SHA-256；不会上传素材来计算哈希。

```text
The MIT License (MIT)

Copyright (c) 2022 Paul Miller (https://paulmillr.com)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the “Software”), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```
