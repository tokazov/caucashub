/**
 * Cloudflare Pages Worker — SEO language injection
 * Для ?lang=ge подставляет грузинский title/description в HTML до отдачи боту.
 */

const GE_TITLE       = 'CaucasHub.ge \u2014 \u10d9\u10d0\u10d5\u10d9\u10d0\u10e1\u10d8\u10d8\u10e1 \u10e1\u10d0\u10e2\u10d5\u10d8\u10e0\u10d7\u10dd \u10d1\u10d8\u10e0\u10df\u10d0';
const GE_DESC        = 'CaucasHub.ge \u2014 \u10d9\u10d0\u10d5\u10d9\u10d0\u10e1\u10d8\u10d8\u10e1 \u10de\u10d8\u10e0\u10d5\u10d4\u10da\u10d8 \u10e1\u10d0\u10e2\u10d5\u10d8\u10e0\u10d7\u10dd \u10d1\u10d8\u10e0\u10df\u10d0. \u10d8\u10de\u10dd\u10d5\u10d4\u10d7 \u10d2\u10d0\u10d3\u10d0\u10db\u10d6\u10d8\u10d3\u10d5\u10d4\u10da\u10d4\u10d1\u10d8 \u10d3\u10d0 \u10e2\u10d5\u10d8\u10e0\u10d7\u10d4\u10d1\u10d8 \u10e1\u10d0\u10e5\u10d0\u10e0\u10d7\u10d5\u10d4\u10da\u10dd\u10e8\u10d8, \u10e1\u10dd\u10db\u10ee\u10d4\u10d7\u10e1\u10d0, \u10d0\u10d6\u10d4\u10e0\u10d1\u10d0\u10d8\u10ef\u10d0\u10dc\u10e8\u10d8. 120+ \u10e5\u10d0\u10da\u10d0\u10e5\u10d8.';
const GE_KEYWORDS    = '\u10e1\u10d0\u10e2\u10d5\u10d8\u10e0\u10d7\u10dd \u10d1\u10d8\u10e0\u10df\u10d0 \u10e1\u10d0\u10e5\u10d0\u10e0\u10d7\u10d5\u10d4\u10da\u10dd, \u10d2\u10d0\u10d3\u10d0\u10db\u10d6\u10d8\u10d3\u10d5\u10d4\u10da\u10d4\u10d1\u10d8 \u10d7\u10d1\u10d8\u10da\u10d8\u10e1\u10d8, \u10e2\u10d5\u10d8\u10e0\u10d7\u10d4\u10d1\u10d8 \u10d9\u10d0\u10d5\u10d9\u10d0\u10e1\u10d8\u10d0, \u10da\u10dd\u10ef\u10d8\u10e1\u10e2\u10d8\u10d9\u10d0 \u10e1\u10d0\u10e5\u10d0\u10e0\u10d7\u10d5\u10d4\u10da\u10dd';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const lang = url.searchParams.get('lang');

    // Только GET к главной
    if (request.method !== 'GET' || (url.pathname !== '/' && url.pathname !== '')) {
      return env.ASSETS.fetch(request);
    }

    // Получаем оригинальный HTML из статических файлов
    const response = await env.ASSETS.fetch(request);

    // Если не GE — отдаём как есть
    if (lang !== 'ge') return response;

    // Для ?lang=ge подменяем SEO-теги
    let html = await response.text();

    html = html.replace(
      /<title[^>]*>[\s\S]*?<\/title>/,
      `<title>${GE_TITLE}</title>`
    );
    html = html.replace(
      /(<meta\s+name="description"\s+content=")[^"]*(")/,
      `$1${GE_DESC}$2`
    );
    html = html.replace(
      /(<meta\s+name="keywords"\s+content=")[^"]*(")/,
      `$1${GE_KEYWORDS}$2`
    );
    html = html.replace(
      /(<meta\s+property="og:title"\s+content=")[^"]*(")/,
      `$1${GE_TITLE}$2`
    );
    html = html.replace(
      /(<meta\s+property="og:description"\s+content=")[^"]*(")/,
      `$1${GE_DESC}$2`
    );
    html = html.replace(
      /(<link\s+rel="canonical"\s+href=")[^"]*(")/,
      `$1https://www.caucashub.ge/?lang=ge$2`
    );

    return new Response(html, {
      headers: {
        'content-type': 'text/html; charset=utf-8',
        'cache-control': 'public, max-age=300',
        'x-robots-tag': 'index, follow',
      },
      status: response.status,
    });
  },
};
