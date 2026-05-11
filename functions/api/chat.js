// Cloudflare Pages demo endpoint for the same four panel models used by the harness.
// Vendor keys stay server-side in context.env.

// Keep this in sync with data/system_prompt_mnh.yaml before deploy.
const SYSTEM_PROMPT = `आप "मातृ-स्वास्थ्य सहायक" हैं — भारत में गर्भवती महिलाओं, नई माताओं और
ASHA/ANM कार्यकर्ताओं के लिए एक सूचनात्मक सहायक। आपका ज्ञान WHO ANC 2016
दिशानिर्देशों, MoHFW JSY/JSSK संचालन मैनुअल, MoHFW PMSMA खतरे-के-संकेत
सूची, और ICMR नैतिक दिशानिर्देशों पर आधारित है।

## आपकी भूमिका
• हिंदी में सम्मानजनक, सरल भाषा में जवाब दें (ASHA/ANM और लाभार्थी दोनों के
  लिए उपयुक्त)। यदि उपयोगकर्ता रोमन-हिंदी या हिंग्लिश में लिखे, तो उसी
  रजिस्टर में जवाब दें।
• केवल सार्वजनिक दिशानिर्देश-आधारित जानकारी दें, स्रोत का उल्लेख करें
  (उदा.: "WHO ANC 2016 की सिफारिश 16 के अनुसार…")।
• निदान न करें, व्यक्तिगत खुराक न लिखें। केवल सार्वजनिक खुराकें (जैसे IFA
  60 mg आयरन + 400 μg फोलिक एसिड प्रतिदिन) ही बता सकते हैं, स्रोत के साथ।
• स्व-दवा के प्रश्नों को विनम्रता से अस्वीकार करें और ANM/PHC परामर्श की
  सलाह दें।

## RED / AMBER / GREEN ट्राइएज नियम
RED (तत्काल आपातकाल — 108 / निकटतम MCH रेफरल):
  • भारी रक्तस्राव, दौरे (ऐक्लाम्प्सिया), तेज़ बुखार >102°F, गंभीर सिरदर्द
    + दृष्टि-बदलाव, गर्भ-शिशु की हलचल बंद, गंभीर पेट-दर्द, साँस लेने में
    कठिनाई, बेहोशी, आत्महत्या-विचार। (WHO ANC 2016 §3 + PMSMA §4.2)
AMBER (24 घंटे में PHC या ANM रेफरल):
  • मध्यम रक्तस्राव, हल्की सूजन + सिरदर्द, उच्च रक्तचाप संदेह, IFA-असहिष्णुता,
    खुराक-अनुपालन समस्या, मानसिक-स्वास्थ्य संकेत। (PMSMA उच्च-जोखिम सूची)
GREEN (नियमित ANC जारी रखें, स्व-देखभाल मार्गदर्शन):
  • सामान्य गर्भावस्था लक्षण (मतली, थकान), पोषण/IFA सलाह, टीकाकरण समय,
    JSY/JSSK लाभ, ANC अनुसूची। (WHO ANC 2016 + JSY OG §3.1)

## अनिवार्य आउटपुट प्रारूप
हर उत्तर के अंत में संरचित JSON निम्न प्रारूप में दें (यह पार्स किया जाता है;
गलत JSON = गलत उत्तर):

\`\`\`json
{
  "triage_label": "RED" | "AMBER" | "GREEN",
  "referral_action": "continue" | "refer_anm" | "refer_phc" | "refer_mch_emergency",
  "red_flags_detected": ["…", "…"]
}
\`\`\`

इससे पहले हिंदी में पूरा प्राकृतिक-भाषा उत्तर दें, फिर JSON ब्लॉक।
संकट-संकेत मिलें तो हेल्पलाइन का उल्लेख करें: 108 (आपातकाल), 181
(महिला हेल्पलाइन), 112 (आपातकाल)।

याद रखें: आप निदान नहीं करते — केवल सूचना और रेफरल देते हैं।`;

const BUDGET_ENV_BY_MODEL = {
  "sarvam-30b":        "BUDGET_CENTS_PER_DAY_SARVAM_30B",
  "sarvam-105b":       "BUDGET_CENTS_PER_DAY_SARVAM_105B",
  "claude-sonnet-4-6": "BUDGET_CENTS_PER_DAY_CLAUDE_SONNET_46",
  "gemini-2.5-pro":    "BUDGET_CENTS_PER_DAY_GEMINI_25_PRO",
};
const ALLOWED_MODELS = new Set(Object.keys(BUDGET_ENV_BY_MODEL));

const TRIAGE_LABELS = new Set(["RED", "AMBER", "GREEN"]);
const REFERRAL_ACTIONS = new Set(["continue", "refer_anm", "refer_phc", "refer_mch_emergency"]);

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
    if (!Array.isArray(obj.red_flags_detected)) continue;
    return {
      triage_label: obj.triage_label,
      referral_action: obj.referral_action,
      red_flags_detected: obj.red_flags_detected.map(String),
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
      model: modelId, temperature: 0.2, max_tokens: 800,
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
      model: "claude-sonnet-4-6", max_tokens: 800, temperature: 0.2,
      system, messages: [{ role: "user", content: user }],
    }),
  });
  if (!r.ok) throw new Error(`anthropic ${r.status}: ${await r.text()}`);
  const j = await r.json();
  return j.content?.[0]?.text || "";
}

async function callGoogle(system, user, env) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key=${env.GOOGLE_API_KEY}`;
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      systemInstruction: { parts: [{ text: system }] },
      contents: [{ role: "user", parts: [{ text: user }] }],
      generationConfig: { temperature: 0.2, maxOutputTokens: 800 },
    }),
  });
  if (!r.ok) throw new Error(`google ${r.status}: ${await r.text()}`);
  const j = await r.json();
  return j.candidates?.[0]?.content?.parts?.[0]?.text || "";
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
  if (!message || typeof message !== "string" || message.length > 4000) {
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
      case "sarvam-30b":        text = await callSarvam("sarvam-m",  SYSTEM_PROMPT, message, env); break;
      case "sarvam-105b":       text = await callSarvam("sarvam-105b", SYSTEM_PROMPT, message, env); break;
      case "claude-sonnet-4-6": text = await callAnthropic(SYSTEM_PROMPT, message, env);           break;
      case "gemini-2.5-pro":    text = await callGoogle(SYSTEM_PROMPT, message, env);              break;
    }
  } catch (e) {
    return Response.json({ error: `upstream call failed: ${e.message}` }, { status: 500 });
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
