export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization, model",
    };
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }
    if (request.method === "POST") {
      if (url.pathname === "/chat") {
        const body = await request.text();
        const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
          method: "POST",
          headers: {
            "Authorization": `Bearer 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`,
            "Content-Type": "application/json"
          },
          body: body
        });
        const data = await res.text();
        return new Response(data, { headers: { ...corsHeaders, "Content-Type": "application/json" } });
      }
      if (url.pathname === "/tts") {
        const body = await request.text();
        const res = await fetch("https://api.fish.audio/v1/tts", {
          method: "POST",
          headers: {
            "Authorization": `Bearer sk-fish-3yi4hHVra26xr292ktj4fh9ILZ4aFog72gMRR-DNkoI`,
            "Content-Type": "application/json",
            "model": "s2.1-pro-free"
          },
          body: body
        });
        const audio = await res.arrayBuffer();
        return new Response(audio, { headers: { ...corsHeaders, "Content-Type": "audio/mpeg" } });
      }
    }
    return new Response("Not found", { status: 404, headers: corsHeaders });
  }
}
