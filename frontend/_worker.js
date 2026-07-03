/**
 * Cloudflare Pages Worker — SEO multilang injection
 *
 * Маршруты:
 *   GET /ka/          → грузинская версия (чистый URL, хорошо для SEO)
 *   GET /?lang=ge     → 301 редирект на /ka/ (старые ссылки не ломаются)
 *   GET /             → русская версия (без изменений)
 *   Все остальные     → статика из Pages
 */

const BASE = 'https://www.caucashub.ge';

const RU = {
  title:    'CaucasHub.ge \u2014 \u0411\u0438\u0440\u0436\u0430 \u0433\u0440\u0443\u0437\u043e\u0432 \u041a\u0430\u0432\u043a\u0430\u0437\u0430',
  desc:     'CaucasHub.ge \u2014 \u043f\u0435\u0440\u0432\u0430\u044f \u0431\u0438\u0440\u0436\u0430 \u0433\u0440\u0443\u0437\u043e\u0432 \u041a\u0430\u0432\u043a\u0430\u0437\u0430. \u041d\u0430\u0439\u0434\u0438\u0442\u0435 \u043f\u0435\u0440\u0435\u0432\u043e\u0437\u0447\u0438\u043a\u043e\u0432 \u0438 \u0433\u0440\u0443\u0437\u044b \u043f\u043e \u0413\u0440\u0443\u0437\u0438\u0438, \u0421\u041d\u0413, \u0422\u0443\u0440\u0446\u0438\u0438. 120+ \u0433\u043e\u0440\u043e\u0434\u043e\u0432.',
  canonical: BASE + '/',
};

const GE_NOSCRIPT = `<noscript>
<div style="max-width:900px;margin:0 auto;padding:20px;font-family:sans-serif">
  <h1>CaucasHub.ge — კავკასიის სატვირთო ბირჟა</h1>
  <p>კავკასიის პირველი ონლაინ სატვირთო ბირჟა. იპოვეთ გადამზიდველები და ტვირთები საქართველოში, რუსეთში, აზერბაიჯანში, სომხეთში და დსთ-ს ქვეყნებში. აქტუალური ტარიფები, სწრაფი გარიგებები. თბილისი, ბათუმი, ქუთაისი, რუსთავი და 120+ ქალაქი.</p>
  <h2>ტვირთგადაზიდვები საქართველოში</h2>
  <p>თბილისი — ბათუმი, თბილისი — ქუთაისი, თბილისი — ფოთი, თბილისი — ზუგდიდი. სასწრაფო და დაგეგმილი გადაზიდვები. ფურგონები, ფურები, რეფრიჯერატორები.</p>
  <h2>საერთაშორისო მარშრუტები</h2>
  <p>საქართველო — რუსეთი, საქართველო — აზერბაიჯანი, საქართველო — სომხეთი, საქართველო — თურქეთი. საბაჟო გაფორმება, კონსოლიდირებული ტვირთები, FTL/LTL.</p>
  <p><a href="https://www.caucashub.ge/ka/">caucashub.ge</a></p>
</div>
</noscript>`;

const GE = {
  title:    'CaucasHub.ge \u2014 \u10d9\u10d0\u10d5\u10d9\u10d0\u10e1\u10d8\u10d8\u10e1 \u10e1\u10d0\u10e2\u10d5\u10d8\u10e0\u10d7\u10dd \u10d1\u10d8\u10e0\u10df\u10d0',
  desc:     'CaucasHub.ge \u2014 \u10d9\u10d0\u10d5\u10d9\u10d0\u10e1\u10d8\u10d8\u10e1 \u10de\u10d8\u10e0\u10d5\u10d4\u10da\u10d8 \u10e1\u10d0\u10e2\u10d5\u10d8\u10e0\u10d7\u10dd \u10d1\u10d8\u10e0\u10df\u10d0. \u10d8\u10de\u10dd\u10d5\u10d4\u10d7 \u10d2\u10d0\u10d3\u10d0\u10db\u10d6\u10d8\u10d3\u10d5\u10d4\u10da\u10d4\u10d1\u10d8 \u10d3\u10d0 \u10e2\u10d5\u10d8\u10e0\u10d7\u10d4\u10d1\u10d8 \u10e1\u10d0\u10e5\u10d0\u10e0\u10d7\u10d5\u10d4\u10da\u10dd\u10e8\u10d8, \u10e1\u10dd\u10db\u10ee\u10d4\u10d7\u10e1\u10d0, \u10d0\u10d6\u10d4\u10e0\u10d1\u10d0\u10d8\u10ef\u10d0\u10dc\u10e8\u10d8. 120+ \u10e5\u10d0\u10da\u10d0\u10e5\u10d8.',
  keywords: '\u10e1\u10d0\u10e2\u10d5\u10d8\u10e0\u10d7\u10dd \u10d1\u10d8\u10e0\u10df\u10d0 \u10e1\u10d0\u10e5\u10d0\u10e0\u10d7\u10d5\u10d4\u10da\u10dd, \u10d2\u10d0\u10d3\u10d0\u10db\u10d6\u10d8\u10d3\u10d5\u10d4\u10da\u10d4\u10d1\u10d8 \u10d7\u10d1\u10d8\u10da\u10d8\u10e1\u10d8, \u10e2\u10d5\u10d8\u10e0\u10d7\u10d4\u10d1\u10d8 \u10d9\u10d0\u10d5\u10d9\u10d0\u10e1\u10d8\u10d0, \u10da\u10dd\u10ef\u10d8\u10e1\u10e2\u10d8\u10d9\u10d0 \u10e1\u10d0\u10e5\u10d0\u10e0\u10d7\u10d5\u10d4\u10da\u10dd',
  canonical: BASE + '/ka/',
  noscript: GE_NOSCRIPT,
};



// hreflang теги — одинаковые для обеих версий
const HREFLANG = `
  <link rel="alternate" hreflang="ru" href="${BASE}/" />
  <link rel="alternate" hreflang="ka" href="${BASE}/ka/" />
  <link rel="alternate" hreflang="x-default" href="${BASE}/" />`;

function injectSEO(html, meta) {
  // title
  html = html.replace(/<title[^>]*>[\s\S]*?<\/title>/, `<title>${meta.title}</title>`);
  // description
  html = html.replace(/(<meta\s+name="description"\s+content=")[^"]*(")/i, `$1${meta.desc}$2`);
  // keywords
  if (meta.keywords) {
    html = html.replace(/(<meta\s+name="keywords"\s+content=")[^"]*(")/i, `$1${meta.keywords}$2`);
  }
  // og:title
  html = html.replace(/(<meta\s+property="og:title"\s+content=")[^"]*(")/i, `$1${meta.title}$2`);
  // og:description
  html = html.replace(/(<meta\s+property="og:description"\s+content=")[^"]*(")/i, `$1${meta.desc}$2`);
  // og:url
  html = html.replace(/(<meta\s+property="og:url"\s+content=")[^"]*(")/i, `$1${meta.canonical}$2`);
  // canonical
  html = html.replace(/(<link\s+rel="canonical"\s+href=")[^"]*(")/i, `$1${meta.canonical}$2`);
  // hreflang — заменяем существующий блок или вставляем после canonical
  html = html.replace(
    /(\s*<link\s+rel="alternate"\s+hreflang[^>]+>\s*)+/g,
    HREFLANG + '\n'
  );
  // twitter:description
  if (meta.desc) {
    html = html.replace(/(<meta\s+name="twitter:description"\s+content=")[^"]*(")/i, `$1${meta.desc}$2`);
    html = html.replace(/(<meta\s+name="twitter:title"\s+content=")[^"]*(")/i, `$1${meta.title}$2`);
  }
  // noscript (если передан)
  if (meta.noscript) {
    html = html.replace(/<noscript>[\s\S]*?<\/noscript>/, meta.noscript);
  }
  return html;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const { pathname, searchParams } = url;

    // ── 301: ?lang=ge → /ka/ (старые ссылки) ────────────────────────────────
    if (pathname === '/' && searchParams.get('lang') === 'ge') {
      return Response.redirect(BASE + '/ka/', 301);
    }

    // ── /ka/ — грузинская SEO-версия ─────────────────────────────────────────
    if (pathname === '/ka/' || pathname === '/ka') {
      // Берём index.html из корня (Pages отдаёт его как SPA fallback)
      const rootReq = new Request(new URL('/', url).toString(), request);
      const response = await env.ASSETS.fetch(rootReq);
      let html = await response.text();

      // Устанавливаем lang=ge для клиентского JS
      html = html.replace(
        'window._initLang = _lang;',
        "window._initLang = 'ge'; _lang = 'ge';"
      );
      // Форсируем localStorage при загрузке
      // Форсируем ge язык: пишем в localStorage И вызываем setLang после загрузки DOM
      html = html.replace(
        '</head>',
        `<script>
        try{localStorage.setItem('ch_lang','ge');}catch(e){}
        document.addEventListener('DOMContentLoaded',function(){
          if(typeof setLang==='function'){
            var _btn=document.querySelector('.lang-btn[onclick*=\"ge\"]');
            setLang('ge',_btn||null);
          }
        });
        </script></head>`
      );

      html = injectSEO(html, GE);

      return new Response(html, {
        headers: {
          'content-type': 'text/html; charset=utf-8',
          'cache-control': 'public, max-age=300',
        },
        status: 200,
      });
    }

    // ── Главная / — русская версия, обновляем hreflang ───────────────────────
    if (pathname === '/' && !searchParams.get('lang')) {
      const response = await env.ASSETS.fetch(request);
      let html = await response.text();
      html = injectSEO(html, RU);
      return new Response(html, {
        headers: {
          'content-type': 'text/html; charset=utf-8',
          'cache-control': 'public, max-age=300',
        },
        status: 200,
      });
    }

    // ── Всё остальное — статика ───────────────────────────────────────────────
    return env.ASSETS.fetch(request);
  },
};
