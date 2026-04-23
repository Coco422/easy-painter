<template>
  <footer class="site-footer" id="about">
    <div class="footer-intro">
      <p class="section-label">我们是一个公益项目</p>
      <h2>只保留安静、透明和长期可用的创作体验</h2>
      <p>
        这个首版只做一件事：让输入提示词和查看最近完成作品变得简单。你后续可以在同域前挂 CDN，而无需暴露任何上游生成服务地址。
      </p>
    </div>

    <div class="footer-points">
      <article>
        <strong>公开画廊</strong>
        <p>最近完成的作品会展示在首页，支持查看提示词。</p>
      </article>
      <article>
        <strong>异步任务</strong>
        <p>生成过程由 Celery 执行，前端轮询本站接口获取状态。</p>
      </article>
      <article>
        <strong>可接 CDN</strong>
        <p>所有图片统一走本站 `/media/...` 路径，便于缓存与扩展。</p>
      </article>
    </div>
  </footer>
</template>
