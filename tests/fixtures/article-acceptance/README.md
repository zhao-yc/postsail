# 多平台图文验收素材

此目录是可重复使用的测试稿，图片为程序生成的测试标记，不包含真实业务信息。三张正文图片按原稿位置排列；默认封面使用 `image-1.png`。原稿包含中文、标题、加粗、列表、引用、链接、表格和代码块。

仅在四个平台的测试账号已登录且账号 ID 明确后执行真实验收。预览可能在平台自动保存草稿；正式发布会提交真实文章。

```sh
sau article import --file tests/fixtures/article-acceptance/原稿.md \
  --title 'PostSail 图文发布测试，请忽略' \
  --cover tests/fixtures/article-acceptance/image-1.png --json
sau article accounts --json
```

使用返回的文章 ID、修订号和各平台测试账号 ID，按 [文章文档](../../../docs/articles.md) 分别执行预览和立即发布。文章定时不支持。不能把本地模拟验收结果当作四个平台真实验收通过。
