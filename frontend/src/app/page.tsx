"use client";
import { useState, useEffect } from "react";
import { T, Lang } from "@/lib/i18n";

const TRUCK_TAGS: Record<string, { label: string; cls: string }> = {
  tent:      { label: "Тент",     cls: "bg-purple-100 text-purple-800" },
  ref:       { label: "Рефриж.", cls: "bg-blue-100 text-blue-800" },
  bort:      { label: "Борт",    cls: "bg-green-100 text-green-800" },
  termos:    { label: "Термос",  cls: "bg-orange-100 text-orange-800" },
  gazel:     { label: "Газель",  cls: "bg-pink-100 text-pink-800" },
  container: { label: "Контейн.", cls: "bg-gray-100 text-gray-700" },
  other:     { label: "Другой",  cls: "bg-gray-100 text-gray-700" },
};

const DEMO_LOCAL = [
  { id:1, from_city:"Тбилиси", to_city:"Батуми",   weight_kg:5000,  truck_type:"tent",   price_usd:280,  load_date:"today",    is_urgent:false, scope:"local", cargo_desc:"Стройматериалы. 12 паллет.",    payment_type:"Нал, сразу",    company:"Экспресс-Груз", rating:"4.9", trips:142, badge:"new"    },
  { id:2, from_city:"Поти",    to_city:"Тбилиси",  weight_kg:12000, truck_type:"ref",    price_usd:450,  load_date:"tomorrow", is_urgent:false, scope:"local", cargo_desc:"Замороженные продукты. -18°С.", payment_type:"Безнал 3 дня",  company:"АгроТранс",    rating:"5.0", trips:89,  badge:null    },
  { id:3, from_city:"Тбилиси", to_city:"Ереван",   weight_kg:20000, truck_type:"tent",   price_usd:890,  load_date:"today",    is_urgent:true,  scope:"local", cargo_desc:"Промобор. Таможня готова.",    payment_type:"Нал на месте",  company:"CargoLine",    rating:"4.7", trips:203, badge:"urgent" },
  { id:4, from_city:"Кутаиси", to_city:"Тбилиси",  weight_kg:3000,  truck_type:"bort",   price_usd:180,  load_date:"today",    is_urgent:false, scope:"local", cargo_desc:"Мебель. Аккуратно.",           payment_type:"Нал",           company:"ГрузМастер",   rating:"4.6", trips:67,  badge:null    },
  { id:5, from_city:"Батуми",  to_city:"Тбилиси",  weight_kg:800,   truck_type:"gazel",  price_usd:120,  load_date:"today",    is_urgent:false, scope:"local", cargo_desc:"Личные вещи. 12 коробок.",     payment_type:"Нал",           company:"ФастДелив",    rating:"4.8", trips:311, badge:"new"    },
  { id:6, from_city:"Рустави", to_city:"Поти",      weight_kg:8000,  truck_type:"termos", price_usd:340,  load_date:"tomorrow", is_urgent:false, scope:"local", cargo_desc:"Хим. сырьё. ДОПОГ нужен.",    payment_type:"Безнал",        company:"РустГруз",     rating:"4.5", trips:44,  badge:null    },
];
const DEMO_INTL = [
  { id:7,  from_city:"Тбилиси", to_city:"Стамбул 🇹🇷", weight_kg:15000, truck_type:"ref",  price_usd:1200, load_date:"29 мар",   is_urgent:false, scope:"intl", cargo_desc:"Цитрусовые. CMR готово.",   payment_type:"Безнал 50%",   company:"ЕвроТранс",    rating:"4.9", trips:528, badge:null    },
  { id:8,  from_city:"Поти",    to_city:"Ереван 🇦🇲",   weight_kg:18000, truck_type:"tent", price_usd:750,  load_date:"today",    is_urgent:true,  scope:"intl", cargo_desc:"Импорт. Срочно.",          payment_type:"Нал при разгр.", company:"КавкасЛог",   rating:"4.8", trips:187, badge:"urgent" },
  { id:9,  from_city:"Тбилиси", to_city:"Баку 🇦🇿",     weight_kg:10000, truck_type:"bort", price_usd:520,  load_date:"30 мар",   is_urgent:false, scope:"intl", cargo_desc:"Стройматериалы. 20 палл.", payment_type:"Безнал",       company:"АзерЭкспресс", rating:"4.7", trips:93,  badge:"new"    },
  { id:10, from_city:"Батуми",  to_city:"Стамбул 🇹🇷",  weight_kg:22000, truck_type:"tent", price_usd:1450, load_date:"31 мар",   is_urgent:false, scope:"intl", cargo_desc:"Промтовары. Паром.",       payment_type:"Безнал 5 дней", company:"ТурГруз TR",  rating:"4.6", trips:231, badge:null    },
  { id:11, from_city:"Тбилиси", to_city:"Москва 🇷🇺",   weight_kg:14000, truck_type:"tent", price_usd:1800, load_date:"28 мар",   is_urgent:false, scope:"intl", cargo_desc:"Текстиль. TIR.",           payment_type:"Безнал 7 дней", company:"РосГруз",     rating:"4.5", trips:156, badge:"new"    },
];

type DemoLoad = typeof DEMO_LOCAL[0] & { user_id?: number | null };

/** Decode JWT payload without a library */
function decodeJwtUserId(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    const sub = decoded.sub ?? decoded.user_id ?? decoded.id;
    return sub ? Number(sub) : null;
  } catch { return null; }
}

export default function Home() {
  const [lang, setLang] = useState<Lang>("ru");
  const [scope, setScope] = useState<"local"|"intl">("local");
  const [selected, setSelected] = useState<DemoLoad|null>(null);
  const [aiMsg, setAiMsg] = useState("");
  const [aiReply, setAiReply] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [currentUserId, setCurrentUserId] = useState<number|null>(null);
  const t = T[lang];
  const data = scope === "local" ? DEMO_LOCAL : DEMO_INTL;

  // Read current user from JWT stored in localStorage
  useEffect(() => {
    const token = localStorage.getItem("token") || localStorage.getItem("access_token");
    if (token) setCurrentUserId(decodeJwtUserId(token));
  }, []);

  const dateLabel = (d: string) => {
    if (d === "today") return t.today;
    if (d === "tomorrow") return t.tomorrow;
    return d;
  };

  const askAI = async () => {
    if (!aiMsg.trim()) return;
    setAiLoading(true);
    try {
      const res = await fetch("https://api-production-f3ea.up.railway.app/api/ai/chat", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ message: aiMsg, lang }),
      });
      const data = await res.json();
      setAiReply(data.reply || "Нет ответа");
    } catch { setAiReply("Ошибка соединения"); }
    setAiLoading(false);
  };

  return (
    <div style={{minHeight:"100vh",background:"#f0f2f5"}}>

      {/* HEADER */}
      <header style={{background:"#1a1a2e",height:54,display:"flex",alignItems:"center",justifyContent:"space-between",padding:"0 16px",position:"sticky",top:0,zIndex:100,boxShadow:"0 2px 8px rgba(0,0,0,.3)"}}>
        <div style={{display:"flex",alignItems:"center",gap:4}}>
          <span style={{color:"#fff",fontWeight:900,fontSize:20}}>Caucas<span style={{color:"#f7b731"}}>Hub</span></span>
          <span style={{color:"#888",fontSize:11,marginLeft:2}}>.ge</span>
        </div>
        <div style={{display:"flex",gap:8,alignItems:"center"}}>
          <div style={{display:"flex",gap:3}}>
            {(["ru","ge","en"] as Lang[]).map(l => (
              <button key={l} onClick={()=>setLang(l)}
                style={{background:lang===l?"#f7b731":"transparent",color:lang===l?"#1a1a2e":"#888",border:"1px solid",borderColor:lang===l?"#f7b731":"#444",padding:"3px 8px",borderRadius:4,fontSize:11,cursor:"pointer",fontWeight:lang===l?700:400}}>
                {l.toUpperCase()}
              </button>
            ))}
          </div>
          <button style={{background:"transparent",color:"#ccc",border:"1px solid #444",padding:"5px 12px",borderRadius:6,fontSize:13,cursor:"pointer"}}>{t.login}</button>
          <button style={{background:"#f7b731",color:"#1a1a2e",border:"none",padding:"5px 14px",borderRadius:6,fontSize:13,fontWeight:700,cursor:"pointer"}}>{t.reg}</button>
        </div>
      </header>

      {/* SCOPE TABS */}
      <div style={{background:"#16213e",display:"flex",padding:"0 16px",borderBottom:"1px solid #0d1526"}}>
        {(["local","intl"] as const).map(s => (
          <button key={s} onClick={()=>setScope(s)}
            style={{padding:"10px 20px",color:scope===s?"#f7b731":"#888",background:"transparent",border:"none",borderBottom:scope===s?"2px solid #f7b731":"2px solid transparent",fontSize:13,fontWeight:scope===s?600:400,cursor:"pointer"}}>
            {s==="local"?t.local:t.intl}
          </button>
        ))}
      </div>

      {/* NAV TABS */}
      <div style={{background:"#1a1a2e",display:"flex",padding:"0 16px",borderBottom:"1px solid #111"}}>
        {[t.loads, t.trucks, t.rates, t.orders].map((tab,i) => (
          <button key={i} style={{padding:"9px 14px",color:i===0?"#f7b731":"#555",background:"transparent",border:"none",borderBottom:i===0?"2px solid #f7b731":"2px solid transparent",fontSize:12,fontWeight:i===0?600:400,cursor:"pointer"}}>
            {tab}
          </button>
        ))}
      </div>

      {/* STATS */}
      <div style={{background:"#0d1526",padding:"7px 16px",display:"flex",gap:20,fontSize:11,color:"#666"}}>
        <span><span style={{color:"#2ecc71",marginRight:4}}>●</span><strong style={{color:"#aaa"}}>{scope==="local"?187:96}</strong> {t.stats.loads}</span>
        <span><strong style={{color:"#aaa"}}>{scope==="local"?634:413}</strong> {t.stats.trucks}</span>
        <span><strong style={{color:"#aaa"}}>2,841</strong> {t.stats.companies}</span>
      </div>

      {/* FILTERS */}
      <div style={{background:"#fff",padding:"10px 16px",borderBottom:"1px solid #eee",position:"sticky",top:54,zIndex:98,boxShadow:"0 2px 4px rgba(0,0,0,.06)"}}>
        {/* Row 1: inputs */}
        <div style={{display:"flex",gap:8,flexWrap:"wrap",alignItems:"center",marginBottom:8}}>
          <input placeholder={t.from} style={{flex:"1 1 120px",minWidth:0,border:"1.5px solid #e0e0e0",borderRadius:8,padding:"7px 10px",fontSize:13,color:"#333",background:"#fff",outline:"none"}}/>
          <input placeholder={t.to} style={{flex:"1 1 120px",minWidth:0,border:"1.5px solid #e0e0e0",borderRadius:8,padding:"7px 10px",fontSize:13,color:"#333",background:"#fff",outline:"none"}}/>
          {[t.date, t.truckType, t.tonnage, t.cost].map((ph,i) => (
            <select key={i} style={{flex:"1 1 100px",minWidth:0,border:"1.5px solid #e0e0e0",borderRadius:8,padding:"7px 10px",fontSize:13,color:"#333",background:"#fff",cursor:"pointer",outline:"none"}}>
              <option>{ph}</option>
            </select>
          ))}
          <span style={{background:"#f7b731",color:"#1a1a2e",padding:"6px 12px",borderRadius:8,fontSize:12,fontWeight:700,whiteSpace:"nowrap"}}>{scope==="local"?187:96} {t.stats.loads}</span>
        </div>
        {/* Row 2: action buttons — fixed width on desktop */}
        <div style={{display:"flex",gap:8}}>
          <button style={{flex:"0 0 auto",minWidth:160,background:"#1a1a2e",color:"#fff",border:"none",padding:"9px 24px",borderRadius:8,fontSize:14,fontWeight:600,cursor:"pointer"}}>
            {t.search}
          </button>
          <button style={{flex:"0 0 auto",minWidth:160,background:"#2ecc71",color:"#fff",border:"none",padding:"9px 24px",borderRadius:8,fontSize:14,fontWeight:600,cursor:"pointer"}}>
            + {t.postLoad}
          </button>
        </div>
      </div>

      {/* AI BAR */}
      <div style={{background:"#fff7e6",borderBottom:"1px solid #fde8a0",padding:"8px 16px",display:"flex",gap:8}}>
        <span style={{fontSize:18}}>🤖</span>
        <input value={aiMsg} onChange={e=>setAiMsg(e.target.value)}
          onKeyDown={e=>e.key==="Enter"&&askAI()}
          placeholder={t.aiPlaceholder}
          style={{flex:1,border:"1px solid #fde8a0",borderRadius:8,padding:"6px 12px",fontSize:13,outline:"none",background:"transparent"}}/>
        <button onClick={askAI} disabled={aiLoading}
          style={{background:"#f7b731",color:"#1a1a2e",border:"none",padding:"6px 16px",borderRadius:8,fontSize:13,fontWeight:700,cursor:"pointer"}}>
          {aiLoading?"...":t.aiBtn}
        </button>
      </div>
      {aiReply && (
        <div style={{background:"#fffbf0",borderBottom:"1px solid #fde8a0",padding:"8px 16px",fontSize:13,color:"#555",lineHeight:1.5}}>
          🤖 {aiReply}
        </div>
      )}

      {/* TABLE HEADER (desktop) */}
      <div style={{display:"grid",gridTemplateColumns:"2.2fr 1.8fr 1fr 1.2fr 1fr 1fr 90px",padding:"8px 16px",background:"#e8eaf0",fontSize:10,color:"#777",fontWeight:700,textTransform:"uppercase",letterSpacing:".6px",borderBottom:"1px solid #d0d4df"}}>
        {[t.colFrom, t.colCompany, t.colWeight, t.colType, t.colPrice, t.colDate, ""].map((h,i) => <div key={i}>{h}</div>)}
      </div>

      {/* ROWS */}
      <div>
        {data.map(row => {
          const tag = TRUCK_TAGS[row.truck_type] || TRUCK_TAGS.other;
          const dateStr = dateLabel(row.load_date);
          const dateColor = row.load_date==="today"?"#2ecc71":row.load_date==="tomorrow"?"#f7b731":"#777";
          const borderColor = row.badge==="urgent"?"#e74c3c":row.badge==="new"?"#2ecc71":scope==="intl"?"#3498db":"transparent";

          return (
            <div key={row.id} onClick={()=>setSelected(row)}
              style={{display:"grid",gridTemplateColumns:"2.2fr 1.8fr 1fr 1.2fr 1fr 1fr 90px",padding:"11px 16px",background:"#fff",borderBottom:"1px solid #f2f2f2",borderLeft:`3px solid ${borderColor}`,cursor:"pointer",alignItems:"center",transition:"background .12s"}}
              onMouseEnter={e=>(e.currentTarget.style.background="#fffbf0")}
              onMouseLeave={e=>(e.currentTarget.style.background="#fff")}>
              <div>
                <div style={{fontWeight:700,fontSize:14}}>{row.from_city} <span style={{color:"#f7b731"}}>→</span> {row.to_city}</div>
                <div style={{fontSize:11,color:"#999",marginTop:2}}>{row.company} ⭐ {row.rating}</div>
              </div>
              <div>
                <div style={{fontSize:13,fontWeight:600}}>{row.company}</div>
                <div style={{fontSize:11,color:"#f7b731"}}>★ {row.rating} · {row.trips} рейсов</div>
              </div>
              <div style={{fontSize:13,color:"#333"}}>{row.weight_kg.toLocaleString()} кг</div>
              <div><span style={{display:"inline-block",fontSize:11,padding:"2px 8px",borderRadius:4,fontWeight:600,...(()=>{const s=tag.cls.split(" ");return{background:s[0].replace("bg-","").replace("-",""),color:"#333"}})(),...{background:tag.cls.includes("purple")?"#f3e5f5":tag.cls.includes("blue")?"#e3f2fd":tag.cls.includes("green")?"#e8f5e9":tag.cls.includes("orange")?"#fff3e0":tag.cls.includes("pink")?"#fce4ec":"#f0f2f5",color:tag.cls.includes("purple")?"#6a1b9a":tag.cls.includes("blue")?"#1565c0":tag.cls.includes("green")?"#2e7d32":tag.cls.includes("orange")?"#bf360c":tag.cls.includes("pink")?"#880e4f":"#555"}}}>{tag.label}</span></div>
              <div style={{fontSize:15,fontWeight:900}}>{row.price_usd?`$${row.price_usd.toLocaleString()}`:"—"}</div>
              <div>
                <div style={{fontSize:12,fontWeight:600,color:dateColor}}>{dateStr}</div>
                {row.badge==="urgent"&&<span style={{fontSize:10,background:"#e74c3c",color:"#fff",padding:"2px 6px",borderRadius:10,fontWeight:700}}>{t.urgent}</span>}
                {row.badge==="new"&&<span style={{fontSize:10,background:"#2ecc71",color:"#fff",padding:"2px 6px",borderRadius:10,fontWeight:700}}>{t.new}</span>}
              </div>
              <div onClick={e=>e.stopPropagation()}>
                {currentUserId && (row as DemoLoad).user_id === currentUserId ? (
                  <button style={{background:"#e0e0e0",color:"#555",border:"none",padding:"6px 10px",borderRadius:6,fontSize:11,fontWeight:700,cursor:"pointer"}}
                    onClick={()=>setSelected(row)}>✏️ Мой груз</button>
                ) : (
                  <button style={{background:"#f7b731",color:"#1a1a2e",border:"none",padding:"6px 12px",borderRadius:6,fontSize:12,fontWeight:700,cursor:"pointer"}}
                    onClick={()=>alert("✅ Заявка отправлена!")}>{t.respond}</button>
                )}
              </div>
            </div>
          );
        })}
        <div style={{textAlign:"center",padding:16,background:"#fff",borderTop:"1px solid #f0f0f0"}}>
          <button style={{background:"#f0f2f5",border:"none",padding:"10px 24px",borderRadius:8,fontSize:13,color:"#555",cursor:"pointer"}}>{t.loadMore} →</button>
        </div>
      </div>

      {/* MODAL */}
      {selected && (
        <div onClick={()=>setSelected(null)} style={{position:"fixed",inset:0,background:"rgba(0,0,0,.6)",zIndex:1000,display:"flex",alignItems:"flex-end",justifyContent:"center"}}>
          <div onClick={e=>e.stopPropagation()} style={{background:"#fff",width:"100%",maxWidth:560,borderRadius:"16px 16px 0 0",padding:20,maxHeight:"90vh",overflowY:"auto"}}>
            <div style={{width:40,height:4,background:"#ddd",borderRadius:2,margin:"0 auto 14px"}}/>
            <div style={{fontSize:19,fontWeight:900,marginBottom:4}}>{selected.from_city} → {selected.to_city}</div>
            <div style={{fontSize:12,color:"#999",marginBottom:14}}>#{selected.scope.toUpperCase()}-{String(selected.id).padStart(5,"0")} · {selected.company}</div>
            <div style={{display:"flex",alignItems:"center",gap:10,background:"#f8f9fa",borderRadius:10,padding:11,marginBottom:14}}>
              <div style={{width:42,height:42,background:"#1a1a2e",borderRadius:8,display:"flex",alignItems:"center",justifyContent:"center",color:"#f7b731",fontWeight:900,fontSize:14,flexShrink:0}}>{selected.company.slice(0,2).toUpperCase()}</div>
              <div>
                <div style={{fontWeight:700,fontSize:14}}>{selected.company}</div>
                <div style={{fontSize:12,color:"#888"}}>★ {selected.rating} · {selected.trips} рейсов</div>
              </div>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:14}}>
              {[[t.fromLabel,selected.from_city],[t.toLabel,selected.to_city],[t.dateLabel,dateLabel(selected.load_date)],[t.weightLabel,`${selected.weight_kg.toLocaleString()} кг`],[t.typeLabel,TRUCK_TAGS[selected.truck_type]?.label||selected.truck_type],[t.payLabel,selected.payment_type||"—"]].map(([label,val],i)=>(
                <div key={i}>
                  <div style={{fontSize:10,color:"#aaa",textTransform:"uppercase",letterSpacing:.5,marginBottom:2}}>{label}</div>
                  <div style={{fontSize:14,fontWeight:700,color:i===2?"#2ecc71":"#1a1a2e"}}>{val}</div>
                </div>
              ))}
            </div>
            {selected.cargo_desc && <div style={{fontSize:13,color:"#444",lineHeight:1.5,marginBottom:14,padding:"10px",background:"#f8f9fa",borderRadius:8}}>{selected.cargo_desc}</div>}
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:14}}>
              <div>
                <div style={{fontSize:10,color:"#aaa",textTransform:"uppercase",letterSpacing:.5}}>{t.rateLabel}</div>
                <div style={{fontSize:28,fontWeight:900}}>{selected.price_usd?`$${selected.price_usd.toLocaleString()}`:"Договорная"}</div>
              </div>
            </div>
            <div style={{display:"flex",gap:10}}>
              {currentUserId && selected.user_id === currentUserId ? (
                <>
                  <button onClick={()=>alert("✏️ Редактирование — скоро")} style={{flex:1,background:"#1a1a2e",color:"#fff",border:"none",padding:14,borderRadius:10,fontSize:15,fontWeight:800,cursor:"pointer"}}>✏️ Редактировать</button>
                  <button onClick={()=>{if(confirm("Удалить этот груз?"))alert("🗑️ Удалено");setSelected(null)}} style={{background:"#e74c3c",color:"#fff",border:"none",padding:14,borderRadius:10,fontSize:18,cursor:"pointer",width:54}}>🗑️</button>
                </>
              ) : (
                <>
                  <button onClick={()=>{alert("✅ Заявка отправлена!");setSelected(null)}} style={{flex:1,background:"#f7b731",color:"#1a1a2e",border:"none",padding:14,borderRadius:10,fontSize:15,fontWeight:800,cursor:"pointer"}}>{t.respond}</button>
                  <button onClick={()=>alert("📞 Контакт будет доступен после регистрации")} style={{background:"#f0f2f5",border:"none",padding:14,borderRadius:10,fontSize:18,cursor:"pointer",width:54}}>📞</button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
