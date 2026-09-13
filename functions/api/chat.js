// Cloudflare Pages demo endpoint for the same four panel models used by the harness.
// Vendor keys stay server-side in context.env.

import { SYSTEM_PROMPT } from "../_shared/health_prompt.js";

const BUDGET_ENV_BY_MODEL = {
  "sarvam-105b-conversations":        "BUDGET_CENTS_PER_DAY_SARVAM_CONVERSATIONS",
  "sarvam-105b":       "BUDGET_CENTS_PER_DAY_SARVAM_105B",
  "claude-sonnet-4-6": "BUDGET_CENTS_PER_DAY_CLAUDE_SONNET_46",
  "gemini-2.5-pro":    "BUDGET_CENTS_PER_DAY_GEMINI_25_PRO",
};
const ALLOWED_MODELS = new Set(Object.keys(BUDGET_ENV_BY_MODEL));

const TRIAGE_LABELS = new Set(["RED", "AMBER", "GREEN"]);
const REFERRAL_ACTIONS = new Set(["continue", "refer_health_worker", "refer_phc", "refer_emergency"]);

function extractTriageJson(text) {
  if (!text) return null;
  // Prefer the final valid JSON object because models often explain before emitting schema.
  const matches = [...text.matchAll(/\{[\s\S]*?\}/g)];
  for (let i = matches.length - 1; i >= 0; i--) {
    let obj;
    try { obj = JSON.parse(matches[i][0]); } catch { continue; }
    if (!obj || typeof obj !== "object") continue;
    if (!TRIAGE_LABELS.has(obj.triage_label)) continue;
    if (!REFERRAL_ACTIONS.has(obj.referral_action)) continue;
    if (!Array.isArray(obj.red_flags_detected) || !obj.red_flags_detected.every(x => typeof x === "string")) continue;
    return {
      triage_label: obj.triage_label,
      referral_action: obj.referral_action,
      red_flags_detected: obj.red_flags_detected,
      triage_reason: obj.triage_reason || null,
    };
  }
  return null;
}

// Worker memory is best-effort; vendor dashboards enforce the real spend cap.
const today = () => new Date().toISOString().slice(0, 10);
const DAILY = Object.fromEntries(
  Object.keys(BUDGET_ENV_BY_MODEL).map(m => [m, { used: 0, cap: 500, date: today() }]),
);
function checkAndIncrement(model, env, cents = 1) {
  const slot = DAILY[model];
  slot.cap = parseInt(env[BUDGET_ENV_BY_MODEL[model]] || "500", 10);
  const d = today();
  if (slot.date !== d) { slot.date = d; slot.used = 0; }
  if (slot.used + cents > slot.cap) return false;
  slot.used += cents;
  return true;
}

async function callSarvam(modelId, system, user, env) {
  const r = await fetch("https://api.sarvam.ai/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json", "api-subscription-key": env.SARVAM_API_KEY },
    body: JSON.stringify({
      model: modelId, temperature: 0.0, reasoning_effort: null, max_tokens: 2048,
      messages: [{ role: "system", content: system }, { role: "user", content: user }],
    }),
  });
  if (!r.ok) throw new Error(`sarvam ${r.status}: ${await r.text()}`);
  const j = await r.json();
  return j.choices?.[0]?.message?.content || "";
}

async function callAnthropic(system, user, env) {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: "claude-sonnet-4-6", max_tokens: 2048, temperature: 0.0,
      system, messages: [{ role: "user", content: user }],
    }),
  });
  if (!r.ok) throw new Error(`anthropic ${r.status}: ${await r.text()}`);
  const j = await r.json();
  return j.content?.[0]?.text || "";
}

async function callGoogle(system, user, env) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key=${env.GOOGLE_API_KEY || env.GEMINI_API_KEY}`;
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      systemInstruction: { parts: [{ text: system }] },
      contents: [{ role: "user", parts: [{ text: user }] }],
      generationConfig: { temperature: 0.0, maxOutputTokens: 4096, thinkingConfig: { thinkingBudget: 512, includeThoughts: false } },
    }),
  });
  if (!r.ok) throw new Error(`google ${r.status}: ${await r.text()}`);
  const j = await r.json();
  return (j.candidates?.[0]?.content?.parts || []).filter(p => !p.thought).map(p => p.text || "").join("");
}

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method !== "POST") {
    return new Response(JSON.stringify({ error: "POST only" }), {
      status: 405,
      headers: { "Content-Type": "application/json", "Allow": "POST" },
    });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "request body must be valid JSON" }, { status: 400 });
  }

  const { model, message } = body || {};
  if (!model || !ALLOWED_MODELS.has(model)) {
    return Response.json(
      { error: `model must be one of ${[...ALLOWED_MODELS].join(", ")}` },
      { status: 400 },
    );
  }
  if (!message || typeof message !== "string" || !message.trim() || message.length > 4000) {
    return Response.json(
      { error: "message must be a non-empty string ≤4000 chars" },
      { status: 400 },
    );
  }

  if (!checkAndIncrement(model, env, 1)) {
    return Response.json({ error: "demo daily budget exhausted, retry tomorrow" }, { status: 429 });
  }

  const t0 = Date.now();
  let text = "";
  try {
    switch (model) {
      case "sarvam-105b-conversations":        text = await callSarvam("sarvam-105b-conversations",  SYSTEM_PROMPT, message, env); break;
      case "sarvam-105b":       text = await callSarvam("sarvam-105b", SYSTEM_PROMPT, message, env); break;
      case "claude-sonnet-4-6": text = await callAnthropic(SYSTEM_PROMPT, message, env);           break;
      case "gemini-2.5-pro":    text = await callGoogle(SYSTEM_PROMPT, message, env);              break;
    }
  } catch (e) {
    return Response.json({ error: "The selected provider could not complete the request. Check its API credentials and billing." }, { status: 500 });
  }
  const latency_ms = Date.now() - t0;
  const triage_json = extractTriageJson(text);
  const parse_succeeded = triage_json !== null;

  return Response.json({
    response: text,
    triage_json,
    model_id: model,
    latency_ms,
    parse_succeeded,
  });
}
