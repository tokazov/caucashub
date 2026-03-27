const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://api-production-f3ea.up.railway.app";

export interface Load {
  id: number;
  from_city: string;
  to_city: string;
  weight_kg: number;
  truck_type: string;
  price_usd: number | null;
  load_date: string;
  is_urgent: boolean;
  scope: string;
  cargo_desc: string | null;
  payment_type: string | null;
}

export async function getLoads(params?: {
  scope?: string;
  from_city?: string;
  to_city?: string;
  truck_type?: string;
}): Promise<{ loads: Load[]; total: number }> {
  const query = new URLSearchParams();
  if (params?.scope) query.set("scope", params.scope);
  if (params?.from_city) query.set("from_city", params.from_city);
  if (params?.to_city) query.set("to_city", params.to_city);
  if (params?.truck_type) query.set("truck_type", params.truck_type);

  const res = await fetch(`${API_URL}/api/loads?${query}`, { cache: "no-store" });
  if (!res.ok) return { loads: [], total: 0 };
  return res.json();
}

export async function aiChat(message: string): Promise<{ reply: string }> {
  const res = await fetch(`${API_URL}/api/ai/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return res.json();
}
