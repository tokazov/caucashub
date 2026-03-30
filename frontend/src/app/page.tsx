"use client";
import { useState, useEffect } from "react";
import { T, Lang } from "@/lib/i18n";

const API = "https://api-production-f3ea.up.railway.app";

const TRUCK_TAGS: Record<string, { label: string; color: string; bg: string }> = {
  tent:      { label: "Тент",      bg: "#f3e5f5", color: "#6a1b9a" },
  ref:       { label: "Рефриж.",   bg: "#e3f2fd", color: "#1565c0" },
  bort:      { label: "Борт",      bg: "#e8f5e9", color: "#2e7d32" },
  termos:    { label: "Термос",    bg: "#fff3e0", color: "#bf360c" },
  gazel:     { label: "Фургон",    bg: "#fce4ec", color: "#880e4f" },
  container: { label: "Контейнер", bg: "#f0f2f5", color: "#555"    },
  auto:      { label: "Автовоз",   bg: "#e8eaf6", color: "#283593" },
  other:     { label: "Другой",    bg: "#f0f2f5", color: "#555"    },
};

interface ApiLoad {
  id: number;
  from: string; from2?: string;
  to: string; to2?: string;
  scope: string;
  kg: number;
  type: string; typeLabel?: string;
  price: number; cur?: string;
  desc?: string; pay?: string;
  urgent: boolean;
  status?: string; badge?: string | null;
  date?: string | null;
  co?: string; rat?: string; trips?: number;
  user_id?: number | null;
  views?: number;
  phone?: string;
}


interface Deal {
  id: number;
  deal_number: string;
  status: string;
  load_from: string;
  load_to: string;
  load_desc?: string;
  load_kg: number;
  price: number;
  currency: string;
  created_at: string;
  loaded_at?: string;
  delivered_at?: string;
  shipper_confirmed: boolean;
  carrier_confirmed: boolean;
  shipper: {id: number; name: string; inn?: string; org_type?: string};
  carrier: {id: number; name: string; inn?: string; org_type?: string};
}

interface UserProfile {
  id: number;
  name: string;
  email: string;
  phone?: string;
  role?: string;
  inn?: string;
  org_type?: string;
  city?: string;
  telegram?: string;
}

function decodeJwtUserId(token: string): number | null {
  try {
    const p = token.split(".")[1];
    const d = JSON.parse(atob(p.replace(/-/g, "+").replace(/_/g, "/")));
    const sub = d.sub ?? d.user_id ?? d.id;
    return sub ? Number(sub) : null;
  } catch { return null; }
}

/* ─── helpers ─────────────────────────────────────────────── */

function Tag({ type }: { type: string }) {
  const tag = TRUCK_TAGS[type] || TRUCK_TAGS.other;
  return (
    <span style={{ display:"inline-block", fontSize:11, padding:"2px 8px",
      borderRadius:4, fontWeight:600, background:tag.bg, color:tag.color }}>
      {tag.label}
    </span>
  );
}

/* ─── main component ────────────────────────────────────────── */

export default function Home() {
  const [lang, setLang]           = useState<Lang>("ru");
  const [scope, setScope]         = useState<"local"|"intl">("local");
  const [token, setToken]         = useState<string|null>(null);
  const [userId, setUserId]       = useState<number|null>(null);
  const [loads, setLoads]         = useState<ApiLoad[]>([]);
  const [loadingData, setLoadingData] = useState(false);

  const [activeTab, setActiveTab]   = useState<"loads"|"trucks"|"rates"|"orders"|"deals">("loads");
  const [deals, setDeals]           = useState<Deal[]>([]);
  const [dealsLoading, setDealsLoading] = useState(false);
  const [profile, setProfile]       = useState<UserProfile|null>(null);
  const [showProfile, setShowProfile] = useState(false);
  const [pName, setPName]           = useState("");
  const [pPhone, setPPhone]         = useState("");
  const [pInn, setPInn]             = useState("");
  const [pOrgType, setPOrgType]     = useState("");
  const [pCity, setPCity]           = useState("");
  const [pTelegram, setPTelegram]   = useState("");
  const [exportFrom, setExportFrom] = useState("");
  const [exportTo, setExportTo]     = useState("");
  const [exportLoading, setExportLoading] = useState(false);

  // Modals
  const [selected, setSelected]     = useState<ApiLoad|null>(null);
  const [showAuth, setShowAuth]     = useState<"login"|"register"|null>(null);
  const [showPost, setShowPost]     = useState(false);
  const [editLoad, setEditLoad]     = useState<ApiLoad|null>(null);

  // Auth form
  const [aEmail, setAEmail]         = useState("");
  const [aPass,  setAPass]          = useState("");
  const [aComp,  setAComp]          = useState("");
  const [aPhone, setAPhone]         = useState("");
  const [aRole,  setARole]          = useState<"carrier"|"shipper">("carrier");
  const [aErr,   setAErr]           = useState("");
  const [aLoading, setALoading]     = useState(false);

  // Load form (create / edit)
  const [fFrom,    setFFrom]        = useState("");
  const [fTo,      setFTo]          = useState("");
  const [fScope,   setFScope]       = useState<"local"|"intl">("local");
  const [fKg,      setFKg]          = useState("");
  const [fType,    setFType]        = useState("tent");
  const [fPrice,   setFPrice]       = useState("");
  const [fDesc,    setFDesc]        = useState("");
  const [fPay,     setFPay]         = useState("Нал");
  const [fUrgent,  setFUrgent]      = useState(false);
  const [fLoading, setFLoading]     = useState(false);
  const [fromSuggests, setFromSuggests] = useState<string[]>([]);
  const [toSuggests,   setToSuggests]   = useState<string[]>([]);
  const [filterFrom,   setFilterFrom]   = useState("");
  const [filterTo,     setFilterTo]     = useState("");

  // AI bar
  const [aiMsg,     setAiMsg]       = useState("");
  const [aiReply,   setAiReply]     = useState("");
  const [aiLoading, setAiLoading]   = useState(false);

  const t = T[lang];

  /* ── init: restore token ── */
  useEffect(() => {
    const saved = localStorage.getItem("ch_token");
    if (saved) { setToken(saved); setUserId(decodeJwtUserId(saved)); }
  }, []);

  /* ── fetch loads on scope/token change ── */
  useEffect(() => { fetchLoads(); }, [scope, token]); // eslint-disable-line

  async function fetchCitySuggests(q: string, setter: (v: string[]) => void) {
    if (q.length < 2) { setter([]); return; }
    try {
      const res = await fetch(`https://suggest-maps.yandex.ru/v1/suggest?apikey=${process.env.NEXT_PUBLIC_YANDEX_KEY||"aef19e33-8ea1-4039-8353-2f0df688664a"}&text=${encodeURIComponent(q)}&types=locality,province&lang=ru_RU&results=5`);
      if (res.ok) {
        const data = await res.json();
        setter((data.results || []).map((r: {title:{text:string}}) => r.title.text));
      }
    } catch { setter([]); }
  }

  async function fetchLoads() {
    setLoadingData(true);
    try {
      const hdrs: Record<string,string> = {};
      if (token) hdrs["Authorization"] = `Bearer ${token}`;
      const res = await fetch(`${API}/api/loads/?scope=${scope}&limit=100`, { headers: hdrs });
      if (res.ok) { const d = await res.json(); setLoads(d.loads || []); }
    } catch { /* keep previous */ }
    setLoadingData(false);
  }

  /* ── respond to load ── */
  async function respondLoad(loadId: number) {
    if (!token) { alert("Войдите, чтобы откликнуться"); return; }
    try {
      const res = await fetch(`${API}/api/responses/load/${loadId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify({ message: "Готов взять груз" })
      });
      if (res.ok) { alert("✅ Заявка отправлена! Грузовладелец получит уведомление."); setSelected(null); }
      else { const d = await res.json(); alert("Ошибка: " + (d.detail || "попробуйте снова")); }
    } catch { alert("Ошибка сети"); }
  }

  /* ── auth ── */
  async function handleAuth() {
    setAErr(""); setALoading(true);
    try {
      const url = showAuth === "login" ? `${API}/api/auth/login/` : `${API}/api/auth/register/`;
      const body = showAuth === "login"
        ? { email: aEmail, password: aPass }
        : { email: aEmail, password: aPass, company_name: aComp, phone: aPhone, role: aRole, lang };
      const res = await fetch(url, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) { setAErr(data.detail || "Ошибка"); setALoading(false); return; }
      localStorage.setItem("ch_token", data.token);
      setToken(data.token);
      setUserId(data.user_id);
      setShowAuth(null);
    } catch { setAErr("Ошибка соединения"); }
    setALoading(false);
  }

  function logout() {
    localStorage.removeItem("ch_token");
    setToken(null); setUserId(null);
  }

  /* ── post / edit load ── */
  function openPostLoad() {
    if (!token) { setShowAuth("login"); return; }
    resetForm(); setFScope(scope); setShowPost(true);
  }

  function openEditLoad(load: ApiLoad) {
    setFFrom(load.from || ""); setFTo(load.to || "");
    setFScope(load.scope as "local"|"intl");
    setFKg(String(load.kg || "")); setFType(load.type || "tent");
    setFPrice(String(load.price || "")); setFDesc(load.desc || "");
    setFPay(load.pay || "Нал"); setFUrgent(load.urgent || false);
    setEditLoad(load); setSelected(null);
  }

  function resetForm() {
    setFFrom(""); setFTo(""); setFKg(""); setFType("tent");
    setFPrice(""); setFDesc(""); setFPay("Нал"); setFUrgent(false);
  }

  async function submitLoad() {
    if (!fFrom || !fTo || !fKg) return;
    setFLoading(true);
    try {
      const body = {
        from_city: fFrom, to_city: fTo, scope: editLoad ? editLoad.scope : fScope,
        weight_kg: parseFloat(fKg), truck_type: fType,
        price_usd: fPrice ? parseFloat(fPrice) : null,
        cargo_desc: fDesc || null, payment_type: fPay, is_urgent: fUrgent,
        load_date: new Date().toISOString(),
      };
      const url = editLoad ? `${API}/api/loads/${editLoad.id}` : `${API}/api/loads/`;
      const method = editLoad ? "PUT" : "POST";
      const res = await fetch(url, {
        method, headers: {"Content-Type":"application/json","Authorization":`Bearer ${token}`},
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const saved = await res.json();
        if (editLoad) setLoads(p => p.map(l => l.id === saved.id ? saved : l));
        else setLoads(p => [saved, ...p]);
        setShowPost(false); setEditLoad(null); resetForm();
      }
    } catch {}
    setFLoading(false);
  }

  async function deleteLoad(id: number) {
    if (!token) return;
    if (!confirm("Удалить груз?")) return;
    try {
      await fetch(`${API}/api/loads/${id}`, {
        method:"DELETE", headers:{"Authorization":`Bearer ${token}`},
      });
      setLoads(p => p.filter(l => l.id !== id));
      setSelected(null);
    } catch {}
  }

  /* ── ai ── */
  async function askAI() {
    if (!aiMsg.trim()) return;
    setAiLoading(true);
    try {
      const res = await fetch(`${API}/api/ai/chat`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ message: aiMsg, lang }),
      });
      const d = await res.json();
      setAiReply(d.reply || "Нет ответа");
    } catch { setAiReply("Ошибка соединения"); }
    setAiLoading(false);
  }


  /* ── deals ── */
  async function fetchDeals() {
    if (!token) return;
    setDealsLoading(true);
    try {
      const res = await fetch(`${API}/api/deals/`, {
        headers: {"Authorization": `Bearer ${token}`}
      });
      if (res.ok) { const d = await res.json(); setDeals(d.deals || d || []); }
    } catch {}
    setDealsLoading(false);
  }

  async function updateDealStatus(dealId: number, status: string) {
    try {
      const res = await fetch(`${API}/api/deals/${dealId}/status`, {
        method: "PUT",
        headers: {"Content-Type":"application/json","Authorization":`Bearer ${token}`},
        body: JSON.stringify({status})
      });
      if (res.ok) fetchDeals();
    } catch {}
  }

  async function confirmDeal(dealId: number) {
    try {
      const res = await fetch(`${API}/api/deals/${dealId}/confirm`, {
        method: "POST",
        headers: {"Authorization": `Bearer ${token}`}
      });
      if (res.ok) fetchDeals();
    } catch {}
  }

  async function downloadPDF(dealId: number, dealNumber: string) {
    try {
      const res = await fetch(`${API}/api/deals/${dealId}/pdf`, {
        headers: {"Authorization": `Bearer ${token}`}
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = `${dealNumber}.pdf`;
        a.click(); URL.revokeObjectURL(url);
      }
    } catch {}
  }

  async function exportDeals(format: "json"|"csv") {
    setExportLoading(true);
    try {
      const params = new URLSearchParams({format});
      if (exportFrom) params.set("date_from", exportFrom);
      if (exportTo) params.set("date_to", exportTo);
      const res = await fetch(`${API}/api/deals/export?${params}`, {
        headers: {"Authorization": `Bearer ${token}`}
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = format === "csv" ? "caucashub_export.csv" : "caucashub_export.json";
        a.click(); URL.revokeObjectURL(url);
      }
    } catch {}
    setExportLoading(false);
  }

  async function loadProfile() {
    if (!token) return;
    try {
      const res = await fetch(`${API}/api/users/me`, {
        headers: {"Authorization": `Bearer ${token}`}
      });
      if (res.ok) {
        const d = await res.json();
        setProfile(d);
        setPName(d.name||""); setPPhone(d.phone||"");
        setPInn(d.inn||""); setPOrgType(d.org_type||"");
        setPCity(d.city||""); setPTelegram(d.telegram||"");
      }
    } catch {}
  }

  async function saveProfile() {
    try {
      const res = await fetch(`${API}/api/users/me`, {
        method: "PUT",
        headers: {"Content-Type":"application/json","Authorization":`Bearer ${token}`},
        body: JSON.stringify({name:pName,phone:pPhone,inn:pInn,org_type:pOrgType,city:pCity,telegram:pTelegram})
      });
      if (res.ok) { alert("✅ Профиль сохранён"); setShowProfile(false); loadProfile(); }
    } catch {}
  }

  const DEAL_STATUS_LABELS: Record<string, {label:string; color:string; bg:string}> = {
    confirmed:  {label:"Подтверждена", color:"#1565c0", bg:"#e3f2fd"},
    loading:    {label:"Загрузка",     color:"#bf360c", bg:"#fff3e0"},
    in_transit: {label:"В пути",       color:"#f57f17", bg:"#fff9c4"},
    delivered:  {label:"Доставлено",   color:"#2e7d32", bg:"#e8f5e9"},
    completed:  {label:"Завершена",    color:"#555",    bg:"#f0f2f5"},
  };

  const DEAL_NEXT_STATUS: Record<string, string> = {
    confirmed: "loading",
    loading: "in_transit",
    in_transit: "delivered",
  };

  useEffect(() => {
    if (token && activeTab === "deals") fetchDeals();
    if (token && activeTab === "deals" && !profile) loadProfile();
  }, [activeTab, token]); // eslint-disable-line

  const isOwner = (l: ApiLoad) => userId !== null && l.user_id === userId;
  const dateColor = (d?: string|null) => d === "today"||d?.includes("сег") ? "#2ecc71" : d === "tomorrow"||d?.includes("завт") ? "#f7b731" : "#777";

  /* ═══════════════════════════════════════════════════════════
     RENDER
  ════════════════════════════════════════════════════════════ */
  return (
    <div style={{minHeight:"100vh",background:"#f0f2f5"}}>

      {/* ── HEADER ── */}
      <header style={{background:"#1a1a2e",height:54,display:"flex",alignItems:"center",
        justifyContent:"space-between",padding:"0 16px",position:"sticky",top:0,zIndex:100,
        boxShadow:"0 2px 8px rgba(0,0,0,.3)"}}>
        <div style={{display:"flex",alignItems:"center",gap:4}}>
          <span style={{color:"#fff",fontWeight:900,fontSize:20}}>Caucas<span style={{color:"#f7b731"}}>Hub</span></span>
          <span style={{color:"#888",fontSize:11,marginLeft:2}}>.ge</span>
        </div>
        <div style={{display:"flex",gap:8,alignItems:"center"}}>
          <div style={{display:"flex",gap:3}}>
            {(["ru","ge","en"] as Lang[]).map(l => (
              <button key={l} onClick={()=>setLang(l)}
                style={{background:lang===l?"#f7b731":"transparent",color:lang===l?"#1a1a2e":"#888",
                  border:"1px solid",borderColor:lang===l?"#f7b731":"#444",padding:"3px 8px",
                  borderRadius:4,fontSize:11,cursor:"pointer",fontWeight:lang===l?700:400}}>
                {l.toUpperCase()}
              </button>
            ))}
          </div>
          {token ? (
            <>
              <span style={{color:"#2ecc71",fontSize:12}}>● Вы вошли</span>
              <button onClick={logout} style={{background:"transparent",color:"#ccc",border:"1px solid #444",padding:"5px 12px",borderRadius:6,fontSize:13,cursor:"pointer"}}>Выйти</button>
            </>
          ) : (
            <>
              <button onClick={()=>setShowAuth("login")} style={{background:"transparent",color:"#ccc",border:"1px solid #444",padding:"5px 12px",borderRadius:6,fontSize:13,cursor:"pointer"}}>{t.login}</button>
              <button onClick={()=>setShowAuth("register")} style={{background:"#f7b731",color:"#1a1a2e",border:"none",padding:"5px 14px",borderRadius:6,fontSize:13,fontWeight:700,cursor:"pointer"}}>{t.reg}</button>
            </>
          )}
        </div>
      </header>

      {/* ── SCOPE TABS ── */}
      <div style={{background:"#16213e",display:"flex",padding:"0 16px",borderBottom:"1px solid #0d1526"}}>
        {(["local","intl"] as const).map(s => (
          <button key={s} onClick={()=>setScope(s)}
            style={{padding:"10px 20px",color:scope===s?"#f7b731":"#888",background:"transparent",
              border:"none",borderBottom:scope===s?"2px solid #f7b731":"2px solid transparent",
              fontSize:13,fontWeight:scope===s?600:400,cursor:"pointer"}}>
            {s==="local"?t.local:t.intl}
          </button>
        ))}
      </div>

      {/* ── NAV TABS ── */}
      <div style={{background:"#1a1a2e",display:"flex",padding:"0 16px",borderBottom:"1px solid #111"}}>
        {([["loads",t.loads],["trucks",t.trucks],["rates",t.rates],["orders",t.orders],["deals","📋 Мои сделки"]] as [string,string][]).map(([key,label]) => (
          <button key={key} onClick={()=>setActiveTab(key as "loads"|"trucks"|"rates"|"orders"|"deals")}
            style={{padding:"9px 14px",color:activeTab===key?"#f7b731":"#555",background:"transparent",
              border:"none",borderBottom:activeTab===key?"2px solid #f7b731":"2px solid transparent",
              fontSize:12,fontWeight:activeTab===key?600:400,cursor:"pointer",whiteSpace:"nowrap"}}>
            {label}
          </button>
        ))}
        {token && (
          <button onClick={()=>{loadProfile();setShowProfile(true);}}
            style={{marginLeft:"auto",padding:"9px 14px",color:"#888",background:"transparent",border:"none",fontSize:12,cursor:"pointer"}}>
            ⚙️
          </button>
        )}
      </div>

      {/* ── STATS ── */}
      <div style={{background:"#0d1526",padding:"7px 16px",display:"flex",gap:20,fontSize:11,color:"#666"}}>
        <span><span style={{color:"#2ecc71",marginRight:4}}>●</span>
          <strong style={{color:"#aaa"}}>{loads.length || (scope==="local"?187:96)}</strong> {t.stats.loads}
        </span>
        <span><strong style={{color:"#aaa"}}>{scope==="local"?634:413}</strong> {t.stats.trucks}</span>
        <span><strong style={{color:"#aaa"}}>2,841</strong> {t.stats.companies}</span>
      </div>

      {(activeTab as string) === "loads" && (<>
      {/* ── FILTERS ── */}
      <div style={{background:"#fff",padding:"10px 16px",borderBottom:"1px solid #eee",
        position:"sticky",top:54,zIndex:98,boxShadow:"0 2px 4px rgba(0,0,0,.06)"}}>
        <div style={{display:"flex",gap:8,flexWrap:"wrap",alignItems:"center",marginBottom:8}}>
          <input value={filterFrom} onChange={e=>setFilterFrom(e.target.value)} placeholder={t.from} name="search-origin-x7k" autoComplete="off" style={{flex:"1 1 120px",minWidth:0,border:"1.5px solid #e0e0e0",borderRadius:8,padding:"7px 10px",fontSize:13,color:"#333",background:"#fff",outline:"none"}}/>
          <input value={filterTo} onChange={e=>setFilterTo(e.target.value)} placeholder={t.to} name="search-dest-x7k" autoComplete="off" style={{flex:"1 1 120px",minWidth:0,border:"1.5px solid #e0e0e0",borderRadius:8,padding:"7px 10px",fontSize:13,color:"#333",background:"#fff",outline:"none"}}/>
          {[t.date, t.truckType, t.tonnage, t.cost].map((ph,i) => (
            <select key={i} style={{flex:"1 1 100px",minWidth:0,border:"1.5px solid #e0e0e0",borderRadius:8,padding:"7px 10px",fontSize:13,color:"#333",background:"#fff",cursor:"pointer",outline:"none"}}>
              <option>{ph}</option>
            </select>
          ))}
          <span style={{background:"#f7b731",color:"#1a1a2e",padding:"6px 12px",borderRadius:8,fontSize:12,fontWeight:700,whiteSpace:"nowrap"}}>
            {loads.length || (scope==="local"?187:96)} {t.stats.loads}
          </span>
        </div>
        <div style={{display:"flex",gap:8}}>
          <button onClick={()=>{ fetchLoads(); }} style={{flex:"0 0 auto",minWidth:160,background:"#1a1a2e",color:"#fff",border:"none",padding:"9px 24px",borderRadius:8,fontSize:14,fontWeight:600,cursor:"pointer"}}>
            {loadingData ? "⏳" : t.search}
          </button>
          <button onClick={openPostLoad} style={{flex:"0 0 auto",minWidth:160,background:"#2ecc71",color:"#fff",border:"none",padding:"9px 24px",borderRadius:8,fontSize:14,fontWeight:600,cursor:"pointer"}}>
            + {t.postLoad}
          </button>
        </div>
      </div>

      {/* ── AI BAR ── */}
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

      {/* ── TABLE HEADER ── */}
      <div style={{display:"grid",gridTemplateColumns:"2.2fr 1.8fr 1fr 1.2fr 1fr 1fr 100px",
        padding:"8px 16px",background:"#e8eaf0",fontSize:10,color:"#777",fontWeight:700,
        textTransform:"uppercase",letterSpacing:".6px",borderBottom:"1px solid #d0d4df"}}>
        {[t.colFrom, t.colCompany, t.colWeight, t.colType, t.colPrice, t.colDate, ""].map((h,i)=><div key={i}>{h}</div>)}
      </div>

      {/* ── ROWS ── */}
      <div>
        {loadingData && loads.length === 0 && (
          <div style={{textAlign:"center",padding:32,color:"#999"}}>Загрузка…</div>
        )}
        {!loadingData && loads.length === 0 && (
          <div style={{textAlign:"center",padding:32,color:"#999"}}>Нет грузов. Разместите первый!</div>
        )}

        {loads.filter(row => {
          const ff = filterFrom.trim().toLowerCase();
          const ft = filterTo.trim().toLowerCase();
          if (ff && !row.from.toLowerCase().includes(ff)) return false;
          if (ft && !row.to.toLowerCase().includes(ft)) return false;
          return true;
        }).map(row => {
          const borderColor = row.badge==="urgent"?"#e74c3c":row.badge==="new"?"#2ecc71":scope==="intl"?"#3498db":"transparent";
          const own = isOwner(row);
          return (
            <div key={row.id} onClick={()=>setSelected(row)}
              style={{display:"grid",gridTemplateColumns:"2.2fr 1.8fr 1fr 1.2fr 1fr 1fr 100px",
                padding:"11px 16px",background:"#fff",borderBottom:"1px solid #f2f2f2",
                borderLeft:`3px solid ${borderColor}`,cursor:"pointer",alignItems:"center",transition:"background .12s"}}
              onMouseEnter={e=>(e.currentTarget.style.background="#fffbf0")}
              onMouseLeave={e=>(e.currentTarget.style.background=own?"#fffde7":"#fff")}>

              <div>
                <div style={{fontWeight:700,fontSize:14}}>
                  {row.from} <span style={{color:"#f7b731"}}>→</span> {row.to}
                </div>
                <div style={{fontSize:11,color:"#999",marginTop:2}}>{row.co} ⭐ {row.rat}</div>
              </div>

              <div>
                <div style={{fontSize:13,fontWeight:600}}>{row.co}</div>
                <div style={{fontSize:11,color:"#f7b731"}}>★ {row.rat} · {row.trips} рейсов</div>
              </div>

              <div style={{fontSize:13,color:"#333"}}>{(row.kg||0).toLocaleString()} кг</div>

              <div><Tag type={row.type}/></div>

              <div style={{fontSize:15,fontWeight:900}}>
                {row.price ? `${row.cur||"$"}${row.price.toLocaleString()}` : "—"}
              </div>

              <div>
                <div style={{fontSize:12,fontWeight:600,color:dateColor(row.date)}}>{row.date||"—"}</div>
                {row.badge==="urgent"&&<span style={{fontSize:10,background:"#e74c3c",color:"#fff",padding:"2px 6px",borderRadius:10,fontWeight:700}}>{t.urgent}</span>}
                {row.badge==="new"&&<span style={{fontSize:10,background:"#2ecc71",color:"#fff",padding:"2px 6px",borderRadius:10,fontWeight:700}}>{t.new}</span>}
              </div>

              {/* ACTION BUTTON */}
              <div onClick={e=>e.stopPropagation()}>
                {own ? (
                  <div style={{display:"flex",gap:4}}>
                    <button onClick={()=>openEditLoad(row)}
                      style={{background:"#e8f5e9",color:"#2e7d32",border:"none",padding:"5px 8px",borderRadius:6,fontSize:11,fontWeight:700,cursor:"pointer"}}>✏️</button>
                    <button onClick={()=>deleteLoad(row.id)}
                      style={{background:"#fce4ec",color:"#c62828",border:"none",padding:"5px 8px",borderRadius:6,fontSize:11,fontWeight:700,cursor:"pointer"}}>🗑️</button>
                  </div>
                ) : (
                  <button onClick={()=>setSelected(row)}
                    style={{background:"#f7b731",color:"#1a1a2e",border:"none",padding:"6px 12px",borderRadius:6,fontSize:12,fontWeight:700,cursor:"pointer"}}>
                    {t.respond}
                  </button>
                )}
              </div>
            </div>
          );
        })}

        <div style={{textAlign:"center",padding:16,background:"#fff",borderTop:"1px solid #f0f0f0"}}>
          <button onClick={fetchLoads} style={{background:"#f0f2f5",border:"none",padding:"10px 24px",borderRadius:8,fontSize:13,color:"#555",cursor:"pointer"}}>
            {t.loadMore} →
          </button>
        </div>
      </div>


      {/* ── DEALS TAB ── */}
      {(activeTab as string) === "deals" && (
        <div style={{maxWidth:800,margin:"0 auto",padding:16}}>
          {!token ? (
            <div style={{textAlign:"center",padding:40,color:"#999"}}>
              <div style={{fontSize:32,marginBottom:8}}>🔒</div>
              <div>Войдите чтобы увидеть сделки</div>
              <button onClick={()=>setShowAuth("login")}
                style={{marginTop:16,background:"#f7b731",color:"#1a1a2e",border:"none",padding:"10px 24px",borderRadius:8,fontSize:14,fontWeight:700,cursor:"pointer"}}>
                Войти
              </button>
            </div>
          ) : (
            <>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:16}}>
                <div style={{fontSize:18,fontWeight:900}}>📋 Мои сделки</div>
                <button onClick={fetchDeals}
                  style={{background:"#f0f2f5",border:"none",padding:"7px 14px",borderRadius:8,fontSize:13,cursor:"pointer"}}>
                  🔄 Обновить
                </button>
              </div>

              {dealsLoading && <div style={{textAlign:"center",padding:32,color:"#999"}}>Загрузка...</div>}

              {!dealsLoading && deals.length === 0 && (
                <div style={{textAlign:"center",padding:40,background:"#fff",borderRadius:12,color:"#999"}}>
                  <div style={{fontSize:32,marginBottom:8}}>📂</div>
                  <div>Сделок пока нет</div>
                  <div style={{fontSize:13,marginTop:4}}>Примите отклик на груз чтобы создать сделку</div>
                </div>
              )}

              {deals.map(deal => {
                const st = DEAL_STATUS_LABELS[deal.status] || {label:deal.status, color:"#555", bg:"#f0f2f5"};
                const nextStatus = DEAL_NEXT_STATUS[deal.status];
                const iAmShipper = userId === deal.shipper?.id;
                const iAmCarrier = userId === deal.carrier?.id;
                const myConfirmed = iAmShipper ? deal.shipper_confirmed : iAmCarrier ? deal.carrier_confirmed : false;

                return (
                  <div key={deal.id} style={{background:"#fff",borderRadius:12,padding:16,marginBottom:12,boxShadow:"0 2px 8px rgba(0,0,0,.06)"}}>
                    <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10}}>
                      <div>
                        <div style={{fontSize:16,fontWeight:900}}>{deal.load_from} → {deal.load_to}</div>
                        <div style={{fontSize:12,color:"#999",marginTop:2}}>
                          {deal.deal_number} · {new Date(deal.created_at).toLocaleDateString("ru")}
                        </div>
                      </div>
                      <span style={{background:st.bg,color:st.color,padding:"4px 10px",borderRadius:20,fontSize:12,fontWeight:700}}>
                        {st.label}
                      </span>
                    </div>

                    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:12,fontSize:13}}>
                      <div><span style={{color:"#aaa"}}>Груз: </span>{(deal.load_kg||0).toLocaleString()} кг</div>
                      <div><span style={{color:"#aaa"}}>Сумма: </span><strong>{deal.currency}{(deal.price||0).toLocaleString()}</strong></div>
                      <div><span style={{color:"#aaa"}}>Грузоотправитель: </span>{deal.shipper?.name}</div>
                      <div><span style={{color:"#aaa"}}>Перевозчик: </span>{deal.carrier?.name}</div>
                    </div>

                    <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
                      {nextStatus && (
                        <button onClick={()=>updateDealStatus(deal.id, nextStatus)}
                          style={{background:"#1a1a2e",color:"#fff",border:"none",padding:"8px 14px",borderRadius:8,fontSize:13,fontWeight:600,cursor:"pointer"}}>
                          → {DEAL_STATUS_LABELS[nextStatus]?.label||nextStatus}
                        </button>
                      )}
                      {deal.status === "delivered" && !myConfirmed && (
                        <button onClick={()=>confirmDeal(deal.id)}
                          style={{background:"#2ecc71",color:"#fff",border:"none",padding:"8px 14px",borderRadius:8,fontSize:13,fontWeight:600,cursor:"pointer"}}>
                          ✅ Подтвердить завершение
                        </button>
                      )}
                      <button onClick={()=>downloadPDF(deal.id, deal.deal_number)}
                        style={{background:"#f0f2f5",color:"#333",border:"none",padding:"8px 14px",borderRadius:8,fontSize:13,cursor:"pointer"}}>
                        📄 Скачать акт
                      </button>
                    </div>
                  </div>
                );
              })}

              {/* rs.ge Export Panel */}
              <div style={{background:"#fff",borderRadius:12,padding:16,marginTop:24,border:"2px solid #e3f2fd"}}>
                <div style={{fontSize:15,fontWeight:700,marginBottom:12,color:"#1565c0"}}>
                  📊 Экспорт для rs.ge
                </div>
                <div style={{display:"flex",gap:8,flexWrap:"wrap",marginBottom:12}}>
                  <div>
                    <div style={{fontSize:11,color:"#aaa",marginBottom:4}}>Дата с</div>
                    <input type="date" value={exportFrom} onChange={e=>setExportFrom(e.target.value)}
                      style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"7px 10px",fontSize:13,outline:"none"}}/>
                  </div>
                  <div>
                    <div style={{fontSize:11,color:"#aaa",marginBottom:4}}>Дата по</div>
                    <input type="date" value={exportTo} onChange={e=>setExportTo(e.target.value)}
                      style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"7px 10px",fontSize:13,outline:"none"}}/>
                  </div>
                </div>
                <div style={{display:"flex",gap:8}}>
                  <button onClick={()=>exportDeals("json")} disabled={exportLoading}
                    style={{background:"#1565c0",color:"#fff",border:"none",padding:"10px 20px",borderRadius:8,fontSize:14,fontWeight:700,cursor:"pointer"}}>
                    📥 JSON
                  </button>
                  <button onClick={()=>exportDeals("csv")} disabled={exportLoading}
                    style={{background:"#2e7d32",color:"#fff",border:"none",padding:"10px 20px",borderRadius:8,fontSize:14,fontWeight:700,cursor:"pointer"}}>
                    📊 CSV (Excel)
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════
          MODAL: PROFILE / SETTINGS
      ════════════════════════════════════ */}
      {showProfile && (
        <div onClick={()=>setShowProfile(false)}
          style={{position:"fixed",inset:0,background:"rgba(0,0,0,.6)",zIndex:1000,display:"flex",alignItems:"center",justifyContent:"center",padding:16}}>
          <div onClick={e=>e.stopPropagation()}
            style={{background:"#fff",width:"100%",maxWidth:440,borderRadius:16,padding:24,maxHeight:"90vh",overflowY:"auto"}}>
            <div style={{fontSize:20,fontWeight:900,marginBottom:16,textAlign:"center"}}>⚙️ Настройки аккаунта</div>

            <div style={{display:"flex",flexDirection:"column",gap:10}}>
              <input value={pName} onChange={e=>setPName(e.target.value)}
                placeholder="Имя / Название компании"
                style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none"}}/>
              <input value={pPhone} onChange={e=>setPPhone(e.target.value)}
                placeholder="Телефон"
                style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none"}}/>
              <input value={pTelegram} onChange={e=>setPTelegram(e.target.value)}
                placeholder="Telegram (@username)"
                style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none"}}/>

              {/* Реквизиты компании */}
              <div style={{borderTop:"1px solid #eee",paddingTop:12,marginTop:4}}>
                <div style={{fontSize:13,fontWeight:700,color:"#1a1a2e",marginBottom:8}}>📋 Реквизиты компании</div>
                <div style={{display:"flex",flexDirection:"column",gap:8}}>
                  <input value={pInn} onChange={e=>setPInn(e.target.value)}
                    placeholder="ИНН / ID код (Грузия)"
                    style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none"}}/>
                  <select value={pOrgType} onChange={e=>setPOrgType(e.target.value)}
                    style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none",cursor:"pointer",color:pOrgType?"#333":"#aaa"}}>
                    <option value="">Форма организации</option>
                    {["ООО","ИП","АО","შპს","ს/ს","Частное лицо"].map(o=>(
                      <option key={o} value={o}>{o}</option>
                    ))}
                  </select>
                  <input value={pCity} onChange={e=>setPCity(e.target.value)}
                    placeholder="Город / регион работы"
                    style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none"}}/>
                </div>
              </div>
            </div>

            <div style={{display:"flex",gap:8,marginTop:16}}>
              <button onClick={saveProfile}
                style={{flex:1,background:"#f7b731",color:"#1a1a2e",border:"none",padding:"13px",borderRadius:10,fontSize:15,fontWeight:800,cursor:"pointer"}}>
                💾 Сохранить
              </button>
              <button onClick={()=>setShowProfile(false)}
                style={{background:"#f0f2f5",color:"#555",border:"none",padding:"13px 20px",borderRadius:10,fontSize:14,cursor:"pointer"}}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}

      </>)}

      {/* ═══════════════════════════════════
          MODAL: LOAD DETAIL
      ════════════════════════════════════ */}
      {selected && (
        <div onClick={()=>setSelected(null)}
          style={{position:"fixed",inset:0,background:"rgba(0,0,0,.6)",zIndex:1000,display:"flex",alignItems:"flex-end",justifyContent:"center"}}>
          <div onClick={e=>e.stopPropagation()}
            style={{background:"#fff",width:"100%",maxWidth:560,borderRadius:"16px 16px 0 0",padding:20,maxHeight:"90vh",overflowY:"auto"}}>
            <div style={{width:40,height:4,background:"#ddd",borderRadius:2,margin:"0 auto 14px"}}/>

            <div style={{fontSize:19,fontWeight:900,marginBottom:4}}>
              {selected.from} → {selected.to}
            </div>
            <div style={{fontSize:12,color:"#999",marginBottom:14}}>
              #{selected.scope?.toUpperCase()}-{String(selected.id).padStart(5,"0")} · {selected.co}
            </div>

            {/* Company card */}
            <div style={{display:"flex",alignItems:"center",gap:10,background:"#f8f9fa",borderRadius:10,padding:11,marginBottom:14}}>
              <div style={{width:42,height:42,background:"#1a1a2e",borderRadius:8,display:"flex",alignItems:"center",justifyContent:"center",color:"#f7b731",fontWeight:900,fontSize:14,flexShrink:0}}>
                {(selected.co||"CH").slice(0,2).toUpperCase()}
              </div>
              <div>
                <div style={{fontWeight:700,fontSize:14}}>{selected.co}</div>
                <div style={{fontSize:12,color:"#888"}}>★ {selected.rat} · {selected.trips} рейсов</div>
              </div>
            </div>

            {/* Details grid */}
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:14}}>
              {[
                [t.fromLabel, selected.from],
                [t.toLabel,   selected.to],
                [t.dateLabel, selected.date||"—"],
                [t.weightLabel, `${(selected.kg||0).toLocaleString()} кг`],
                [t.typeLabel,  TRUCK_TAGS[selected.type]?.label||selected.type],
                [t.payLabel,   selected.pay||"—"],
              ].map(([label,val],i)=>(
                <div key={i}>
                  <div style={{fontSize:10,color:"#aaa",textTransform:"uppercase",letterSpacing:.5,marginBottom:2}}>{label}</div>
                  <div style={{fontSize:14,fontWeight:700,color:i===2?"#2ecc71":"#1a1a2e"}}>{val}</div>
                </div>
              ))}
            </div>

            {selected.desc && (
              <div style={{fontSize:13,color:"#444",lineHeight:1.5,marginBottom:14,padding:10,background:"#f8f9fa",borderRadius:8}}>
                {selected.desc}
              </div>
            )}

            {/* Price */}
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:14}}>
              <div>
                <div style={{fontSize:10,color:"#aaa",textTransform:"uppercase",letterSpacing:.5}}>{t.rateLabel}</div>
                <div style={{fontSize:28,fontWeight:900}}>
                  {selected.price ? `${selected.cur||"$"}${selected.price.toLocaleString()}` : "Договорная"}
                </div>
              </div>
              {isOwner(selected) && (
                <span style={{fontSize:11,background:"#e8f5e9",color:"#2e7d32",padding:"4px 10px",borderRadius:6,fontWeight:700}}>
                  ✓ Мой груз
                </span>
              )}
            </div>

            {/* Action buttons */}
            <div style={{display:"flex",gap:10}}>
              {isOwner(selected) ? (
                <>
                  <button onClick={()=>openEditLoad(selected)}
                    style={{flex:1,background:"#1a1a2e",color:"#fff",border:"none",padding:14,borderRadius:10,fontSize:15,fontWeight:800,cursor:"pointer"}}>
                    ✏️ Редактировать
                  </button>
                  <button onClick={()=>deleteLoad(selected.id)}
                    style={{background:"#e74c3c",color:"#fff",border:"none",padding:14,borderRadius:10,fontSize:18,cursor:"pointer",width:54}}>
                    🗑️
                  </button>
                </>
              ) : (
                <>
                  <button onClick={()=>respondLoad(selected!.id)}
                    style={{flex:1,background:"#f7b731",color:"#1a1a2e",border:"none",padding:14,borderRadius:10,fontSize:15,fontWeight:800,cursor:"pointer"}}>
                    {t.respond}
                  </button>
                  <button onClick={()=>{ if(token && selected?.phone) alert("📞 " + selected.phone); else alert("📞 Контакт доступен после регистрации"); }}
                    style={{background:"#f0f2f5",border:"none",padding:14,borderRadius:10,fontSize:18,cursor:"pointer",width:54}}>
                    📞
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════
          MODAL: AUTH (login / register)
      ════════════════════════════════════ */}
      {showAuth && (
        <div onClick={()=>setShowAuth(null)}
          style={{position:"fixed",inset:0,background:"rgba(0,0,0,.6)",zIndex:1000,display:"flex",alignItems:"center",justifyContent:"center",padding:16}}>
          <div onClick={e=>e.stopPropagation()}
            style={{background:"#fff",width:"100%",maxWidth:400,borderRadius:16,padding:24}}>

            <div style={{fontSize:20,fontWeight:900,marginBottom:4,textAlign:"center"}}>
              {showAuth==="login"?"Войти":"Регистрация"}
            </div>

            {/* Toggle */}
            <div style={{display:"flex",justifyContent:"center",gap:8,marginBottom:20}}>
              <button onClick={()=>setShowAuth("login")}
                style={{padding:"6px 16px",borderRadius:6,border:"none",fontSize:13,fontWeight:700,cursor:"pointer",
                  background:showAuth==="login"?"#1a1a2e":"#f0f2f5",color:showAuth==="login"?"#fff":"#555"}}>
                Войти
              </button>
              <button onClick={()=>setShowAuth("register")}
                style={{padding:"6px 16px",borderRadius:6,border:"none",fontSize:13,fontWeight:700,cursor:"pointer",
                  background:showAuth==="register"?"#1a1a2e":"#f0f2f5",color:showAuth==="register"?"#fff":"#555"}}>
                Регистрация
              </button>
            </div>

            {/* Fields */}
            <div style={{display:"flex",flexDirection:"column",gap:10}}>
              <input value={aEmail} onChange={e=>setAEmail(e.target.value)}
                placeholder="Email" type="email"
                style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none"}}/>
              <input value={aPass} onChange={e=>setAPass(e.target.value)}
                placeholder="Пароль" type="password"
                style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none"}}/>

              {showAuth==="register" && (
                <>
                  <input value={aComp} onChange={e=>setAComp(e.target.value)}
                    placeholder="Название компании"
                    style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none"}}/>
                  <input value={aPhone} onChange={e=>setAPhone(e.target.value)}
                    placeholder="Телефон (+995...)"
                    style={{border:"1.5px solid #e0e0e0",borderRadius:8,padding:"10px 12px",fontSize:14,outline:"none"}}/>
                  <div style={{display:"flex",gap:8}}>
                    {(["carrier","shipper"] as const).map(r=>(
                      <button key={r} onClick={()=>setARole(r)}
                        style={{flex:1,padding:"9px",borderRadius:8,fontSize:13,fontWeight:600,cursor:"pointer",border:"2px solid",
                          borderColor:aRole===r?"#1a1a2e":"#e0e0e0",background:aRole===r?"#1a1a2e":"#fff",
                          color:aRole===r?"#fff":"#555"}}>
                        {r==="carrier"?"🚛 Перевозчик":"📦 Грузоотправитель"}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>

            {aErr && <div style={{color:"#e74c3c",fontSize:13,marginTop:8,textAlign:"center"}}>{aErr}</div>}

            <button onClick={handleAuth} disabled={aLoading}
              style={{width:"100%",marginTop:16,background:"#f7b731",color:"#1a1a2e",border:"none",
                padding:"13px",borderRadius:10,fontSize:16,fontWeight:800,cursor:"pointer"}}>
              {aLoading ? "⏳..." : showAuth==="login" ? "Войти" : "Создать аккаунт"}
            </button>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════
          MODAL: POST / EDIT LOAD
      ════════════════════════════════════ */}
      {(showPost || editLoad) && (
        <div onClick={()=>{setShowPost(false);setEditLoad(null);}}
          style={{position:"fixed",inset:0,background:"rgba(0,0,0,.6)",zIndex:1000,display:"flex",alignItems:"flex-end",justifyContent:"center"}}>
          <div onClick={e=>e.stopPropagation()}
            style={{background:"#fff",width:"100%",maxWidth:560,borderRadius:"16px 16px 0 0",padding:20,maxHeight:"90vh",overflowY:"auto"}}>
            <div style={{width:40,height:4,background:"#ddd",borderRadius:2,margin:"0 auto 14px"}}/>
            <div style={{fontSize:18,fontWeight:900,marginBottom:16,textAlign:"center"}}>
              {editLoad ? "✏️ Редактировать груз" : "📦 Разместить груз"}
            </div>

            <div style={{display:"flex",flexDirection:"column",gap:10}}>
              <div style={{display:"flex",gap:8}}>
                <div style={{position:"relative",flex:1}}>
                  <input value={fFrom} onChange={e=>{setFFrom(e.target.value);fetchCitySuggests(e.target.value,setFromSuggests);}}
                    onBlur={()=>setTimeout(()=>setFromSuggests([]),150)}
                    placeholder="Откуда (город)" autoComplete="new-password" style={{...inputStyle,width:"100%",boxSizing:"border-box"}}/>
                  {fromSuggests.length>0&&<div style={{position:"absolute",top:"100%",left:0,right:0,background:"#fff",border:"1.5px solid #e0e0e0",borderRadius:8,zIndex:999,boxShadow:"0 4px 12px rgba(0,0,0,.1)"}}>
                    {fromSuggests.map((s,i)=><div key={i} onMouseDown={()=>{setFFrom(s);setFromSuggests([]);}} style={{padding:"8px 12px",cursor:"pointer",fontSize:13,borderBottom:i<fromSuggests.length-1?"1px solid #f0f0f0":"none"}} onMouseEnter={e=>(e.currentTarget.style.background="#f5f5f5")} onMouseLeave={e=>(e.currentTarget.style.background="#fff")}>{s}</div>)}
                  </div>}
                </div>
                <div style={{position:"relative",flex:1}}>
                  <input value={fTo} onChange={e=>{setFTo(e.target.value);fetchCitySuggests(e.target.value,setToSuggests);}}
                    onBlur={()=>setTimeout(()=>setToSuggests([]),150)}
                    placeholder="Куда (город)" autoComplete="new-password" style={{...inputStyle,width:"100%",boxSizing:"border-box"}}/>
                  {toSuggests.length>0&&<div style={{position:"absolute",top:"100%",left:0,right:0,background:"#fff",border:"1.5px solid #e0e0e0",borderRadius:8,zIndex:999,boxShadow:"0 4px 12px rgba(0,0,0,.1)"}}>
                    {toSuggests.map((s,i)=><div key={i} onMouseDown={()=>{setFTo(s);setToSuggests([]);}} style={{padding:"8px 12px",cursor:"pointer",fontSize:13,borderBottom:i<toSuggests.length-1?"1px solid #f0f0f0":"none"}} onMouseEnter={e=>(e.currentTarget.style.background="#f5f5f5")} onMouseLeave={e=>(e.currentTarget.style.background="#fff")}>{s}</div>)}
                  </div>}
                </div>
              </div>

              {!editLoad && (
                <div style={{display:"flex",gap:8}}>
                  {(["local","intl"] as const).map(s=>(
                    <button key={s} onClick={()=>setFScope(s)}
                      style={{flex:1,padding:"9px",borderRadius:8,fontSize:13,fontWeight:600,cursor:"pointer",border:"2px solid",
                        borderColor:fScope===s?"#1a1a2e":"#e0e0e0",background:fScope===s?"#1a1a2e":"#fff",
                        color:fScope===s?"#fff":"#555"}}>
                      {s==="local"?"🇬🇪 Локальный":"🌍 Международный"}
                    </button>
                  ))}
                </div>
              )}

              <div style={{display:"flex",gap:8}}>
                <input value={fKg} onChange={e=>setFKg(e.target.value)}
                  placeholder="Вес, кг" type="number" style={inputStyle}/>
                <input value={fPrice} onChange={e=>setFPrice(e.target.value)}
                  placeholder="Цена, $" type="number" style={inputStyle}/>
              </div>

              <select value={fType} onChange={e=>setFType(e.target.value)} style={{...inputStyle,cursor:"pointer"}}>
                {Object.entries(TRUCK_TAGS).map(([k,v])=>(
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>

              <select value={fPay} onChange={e=>setFPay(e.target.value)} style={{...inputStyle,cursor:"pointer"}}>
                {["Нал","Нал при разгрузке","Безнал","Безнал 3 дня","Безнал 5 дней","Безнал 50%"].map(p=>(
                  <option key={p}>{p}</option>
                ))}
              </select>

              <textarea value={fDesc} onChange={e=>setFDesc(e.target.value)}
                placeholder="Описание груза (необязательно)"
                style={{...inputStyle,height:80,resize:"vertical"}}/>

              <label style={{display:"flex",alignItems:"center",gap:8,cursor:"pointer",fontSize:14}}>
                <input type="checkbox" checked={fUrgent} onChange={e=>setFUrgent(e.target.checked)}
                  style={{width:16,height:16}}/>
                🔴 Срочный груз
              </label>
            </div>

            <button onClick={submitLoad} disabled={fLoading||!fFrom||!fTo||!fKg}
              style={{width:"100%",marginTop:16,background:fFrom&&fTo&&fKg?"#2ecc71":"#ccc",
                color:"#fff",border:"none",padding:"13px",borderRadius:10,fontSize:16,fontWeight:800,
                cursor:fFrom&&fTo&&fKg?"pointer":"not-allowed"}}>
              {fLoading ? "⏳ Сохраняем..." : editLoad ? "💾 Сохранить изменения" : "📤 Разместить груз"}
            </button>
          </div>
        </div>
      )}

    </div>
  );
}

const inputStyle: React.CSSProperties = {
  flex:1, border:"1.5px solid #e0e0e0", borderRadius:8,
  padding:"10px 12px", fontSize:13, outline:"none", color:"#333", background:"#fff",
};
