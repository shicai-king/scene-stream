# GitHub 准备与源码打包

当前项目暂不指定许可证；第三方许可说明见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。发布目标仓库由维护者选择，工具不会自动创建仓库、推送代码或发布镜像。

## 检查并导出

```bash
python3 scripts/check_repository.py --history
uv run pytest -q
npm run build
git status --short
# 完成需要上传的本地提交后：
python3 scripts/package_source.py
```

打包程序要求工作区干净，使用 `git archive HEAD` 导出已提交源码，生成 `releases/longlive-rooms-<commit>.zip`、`.tar.gz`、`.sha256` 和清单 JSON。不递归压缩整个工作目录，不包含 `.git`、本地权重、缓存、运行环境、日志、弹幕记录或私有配置。历史规划文档仍在 Git 中，但通过 `.gitattributes` 从源码包排除。

不要直接上传整个工作文件夹。仓库检查会拒绝常见私有/生成目录、大文件和部分凭据模式；它不是对所有敏感信息的穷尽识别，发布前仍应审阅实际差异。

## 上传到自己的仓库

在 GitHub 创建空仓库后，把示例地址换成自己的仓库地址，再从项目根目录执行：

```bash
git remote add origin git@github.com:YOUR_ACCOUNT/longlive-rooms.git
git push -u origin main
```

已有 `origin` 时先查看 `git remote -v`，避免覆盖其他仓库设置。也可以解压源码 ZIP 后上传源码文件；这种方式不保留现有 Git 历史。

## 自动检查

`.github/workflows/ci.yml` 使用固定提交的官方 Actions，执行仓库检查、23 项软件/部署测试、前端构建、无 GPU 的 hub 镜像构建和 Mock 流测试。工作流仅需要读取源码权限，不发布镜像，不把 Mock 结果替代真实模型验收。

## 本地记录

弹幕历史由服务端内存管理，浏览器只持久保存客户端 ID、昵称和所选房间。运行事件、浏览器截图和原始验证记录可能包含消息内容或消息元数据，均位于被忽略的 `logs/`、`artifacts/`。本次已按维护者要求删除本地弹幕记录及包含弹幕的截图，只保留不含消息内容的性能与校验数据。
