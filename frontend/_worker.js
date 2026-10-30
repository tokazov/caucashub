/**
 * Cloudflare Pages Worker: locale HTML and root-resolved static assets.
 * Canonical SEO URLs stay on production; redirects preserve the request origin.
 */
const BASE = 'https://www.caucashub.ge';
const META = {
  ru: {
    title:'CaucasHub.ge — Биржа грузов Кавказа',
    desc:'Платформа для поиска грузов и перевозчиков в Грузии и на международных направлениях. Разместите заявку с маршрутом, датой и параметрами груза.',
    canonical:BASE+'/',
  },
  ge: {
    title:'CaucasHub.ge — კავკასიის სატვირთო ბირჟა',
    desc:'ტვირთებისა და გადამზიდველების საძიებო პლატფორმა საქართველოში და საერთაშორისო მიმართულებებზე. განათავსეთ განაცხადი მარშრუტით, თარიღითა და ტვირთის მონაცემებით.',
    canonical:BASE+'/ka/',
  },
};
const HREFLANG = [
  '<link rel="alternate" hreflang="ru" href="'+BASE+'/" />',
  '<link rel="alternate" hreflang="ka" href="'+BASE+'/ka/" />',
  '<link rel="alternate" hreflang="x-default" href="'+BASE+'/" />',
].join('\n');
const LEGACY_LOCALE_ASSETS = new Set([
  'styles.css','api.js','main.js','translations.js','ai-dispatcher.js','locations.js','route-distance.js','location-presentation.js','public-profile.js',
  'sw.js','manifest.json','dispatcher.jpg','mari-avatar-v2.webp',
  'icon-192.png','icon-512.png','og-image.jpg','robots.txt','sitemap.xml',
]);
function rewriteMeta(html, selector, value) {
  return html.replace(selector, (_whole, before, after)=>before+value+after);
}
export function injectSEO(html, locale) {
  const meta=META[locale];
  html=html.replace(/<html\b[^>]*>/i, '<html lang="'+(locale==='ge'?'ka':'ru')+'">');
  html=html.replace(/<title[^>]*>[\s\S]*?<\/title>/i, '<title>'+meta.title+'</title>');
  html=rewriteMeta(html, /(<meta\s+name="description"\s+content=")[^"]*(")/i, meta.desc);
  html=rewriteMeta(html, /(<meta\s+property="og:title"\s+content=")[^"]*(")/i, meta.title);
  html=rewriteMeta(html, /(<meta\s+property="og:description"\s+content=")[^"]*(")/i, meta.desc);
  html=rewriteMeta(html, /(<meta\s+property="og:url"\s+content=")[^"]*(")/i, meta.canonical);
  html=rewriteMeta(html, /(<meta\s+name="twitter:title"\s+content=")[^"]*(")/i, meta.title);
  html=rewriteMeta(html, /(<meta\s+name="twitter:description"\s+content=")[^"]*(")/i, meta.desc);
  html=rewriteMeta(html, /(<link\s+rel="canonical"\s+href=")[^"]*(")/i, meta.canonical);
  html=html.replace(/(\s*<link\s+rel="alternate"\s+hreflang[^>]+>\s*)+/g, '\n'+HREFLANG+'\n');
  // One base resolves stylesheet, scripts, images AND dynamically added avatar URLs.
  if (/<base\b/i.test(html)) html=html.replace(/<base\b[^>]*>/i, '<base href="/">');
  else html=html.replace(/<head[^>]*>/i, '$&\n<base href="/">');
  if(locale==='ge') {
    html=html.replace(/<noscript>[\s\S]*?<\/noscript>/g, (block)=>
      block.includes('<h1>') ? '<noscript><div style="max-width:900px;margin:auto;padding:20px;font-family:sans-serif"><h1>'+meta.title+'</h1><p>'+meta.desc+'</p><p><a href="'+meta.canonical+'">CaucasHub.ge</a></p></div></noscript>' : block);
  }
  return html;
}
export default {
  async fetch(request, env) {
    const url=new URL(request.url);
    const read=request.method==='GET'||request.method==='HEAD';
    if(!read) return env.ASSETS.fetch(request);
    if(url.pathname==='/'&&url.searchParams.get('lang')==='ge') {
      url.pathname='/ka/';
      url.searchParams.delete('lang');
      return Response.redirect(url.toString(),301);
    }
    if(url.pathname==='/ka') {
      url.pathname='/ka/';
      return Response.redirect(url.toString(),301);
    }
    // Compatibility for previous /ka HTML already held by a browser/cache.
    if(url.pathname.startsWith('/ka/')&&LEGACY_LOCALE_ASSETS.has(url.pathname.slice(4))) {
      url.pathname='/'+url.pathname.slice(4);
      return env.ASSETS.fetch(new Request(url.toString(),request));
    }
    const locale=url.pathname==='/ka/'?'ge':url.pathname==='/'?'ru':null;
    if(!locale) return env.ASSETS.fetch(request);
    const root=new URL(request.url);
    root.pathname='/';
    const response=await env.ASSETS.fetch(new Request(root.toString(),request));
    if(!response.ok||!(response.headers.get('content-type')||'').includes('text/html')) return response;
    const html=injectSEO(await response.text(),locale);
    const headers=new Headers(response.headers);
    headers.set('content-type','text/html; charset=utf-8');
    headers.set('cache-control','no-store, no-cache, must-revalidate, max-age=0');
    headers.delete('content-length');
    headers.delete('content-encoding');
    return new Response(request.method==='HEAD'?null:html,{status:response.status,headers});
  },
};
