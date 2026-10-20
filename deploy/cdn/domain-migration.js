// GoEdge request-initialization script. Replace only these deployment values.
// API: https://goedge.cloud/docs/Computing/Script/Request.md
var migrationConfig = {
  oldHost: "legacy.example.invalid",
  newOrigin: "https://app.example.invalid"
};

(function (req, resp, config) {
  var host = String(req.host).toLowerCase().replace(/:\d+$/, "");
  if (host !== config.oldHost || !/^https:\/\/[a-z0-9.-]+(?::\d+)?$/i.test(config.newOrigin)) return;
  var path = String(req.path);
  // Keep the original origin's local-canvas export dependencies available.
  if (/^\/(api|assets|media|canvas)(\/|$)/.test(path)) return;
  if (req.method !== "GET" && req.method !== "HEAD") return;

  function escapeHtml(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  // Once the application supports a canvas return path, allow only that login.
  var uri = String(req.uri);
  if (path === "/login") {
    var match = /[?&]redirect=([^&]*)/.exec(uri);
    if (match) {
      try {
        var returnPath = decodeURIComponent(match[1]);
        if (/^\/canvas(?:\/[^?#]*)?(?:\?[^#]*)?(?:#.*)?$/.test(returnPath) && !/[\\\r\n]/.test(returnPath)) return;
      } catch (_) { /* Malformed return paths receive the migration notice. */ }
    }
  }
  var target = config.newOrigin + (uri.charAt(0) === "/" ? uri : "/");
  var safeTarget = escapeHtml(target);
  var safeOrigin = escapeHtml(config.newOrigin);
  var page = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"><title>旧站域名即将关停 · 涂涂</title>
<noscript><meta http-equiv="refresh" content="5;url=${safeTarget}"></noscript>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:#f8f5ee;color:#2c2518;font-family:"PingFang SC","Microsoft YaHei",sans-serif}
main{width:min(100%,560px);padding:44px;background:#fff;border:1px solid rgba(0,0,0,.08);border-radius:20px;box-shadow:0 8px 32px rgba(80,60,30,.1)}
.brand{margin:0 0 28px;color:#a87d28;font-size:14px;font-weight:600;letter-spacing:.15em}h1{margin:0 0 16px;font-family:"Noto Serif SC",Georgia,serif;font-size:30px;font-weight:600;line-height:1.5}
p{margin:0 0 18px;color:#6b5d4a;font-size:15px;line-height:1.8}.destination{display:block;overflow-wrap:anywhere;color:#a87d28;font-size:20px;font-weight:600;margin-top:8px}
.countdown{margin:28px 0 20px}strong{color:#2c2518;font-variant-numeric:tabular-nums}a{color:#a87d28;text-underline-offset:4px}.primary{display:block;padding:14px 20px;border-radius:10px;background:#c49536;color:#fff;text-align:center;text-decoration:none;font-weight:600}
.export{border-top:1px solid rgba(0,0,0,.08);margin-top:28px;padding-top:22px}.export p{font-size:13px;margin-bottom:10px}.export a{font-size:14px}a:focus-visible{outline:3px solid #2c2518;outline-offset:4px}
@media(max-width:520px){main{padding:28px 24px}h1{font-size:25px}.destination{font-size:17px}}
</style></head><body><main>
<p class="brand">涂涂 · 站点迁移通知</p><h1>旧站域名即将关停</h1>
<p>我们已迁移到新域名，请更新收藏夹。<span class="destination">${safeOrigin.replace(/^https:\/\//, "")}</span></p>
<p class="countdown"><strong id="seconds">5</strong> 秒后自动前往新站。</p>
<a id="destination" class="primary" href="${safeTarget}" rel="noreferrer">立即前往新站</a>
<section class="export"><p>旧浏览器中的本地画布不会随域名迁移。请先导出，再到新站导入。</p><a id="export" href="/canvas">暂不前往，导出旧站本地画布</a></section>
</main><script>
(function(){
  var target = new URL(${JSON.stringify(config.newOrigin)});
  target.pathname = window.location.pathname;
  target.search = window.location.search;
  target.hash = window.location.hash;
  document.getElementById('destination').href = target.href;
  var deadline = Date.now() + 5000;
  var timer = setTimeout(function(){ window.location.replace(target.href); }, 5000);
  var ticker = setInterval(function(){ document.getElementById('seconds').textContent = String(Math.max(0, Math.ceil((deadline - Date.now()) / 1000))); }, 200);
  document.getElementById('export').addEventListener('click', function(){ clearTimeout(timer); clearInterval(ticker); });
})();
</script></body></html>`;
  resp.setHeader("Content-Type", "text/html; charset=utf-8");
  resp.setHeader("Cache-Control", "no-store, max-age=0");
  resp.setHeader("Pragma", "no-cache");
  resp.setHeader("Referrer-Policy", "no-referrer");
  resp.setHeader("X-Content-Type-Options", "nosniff");
  resp.setHeader("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
  resp.send(200, page);
})(req, resp, migrationConfig);
