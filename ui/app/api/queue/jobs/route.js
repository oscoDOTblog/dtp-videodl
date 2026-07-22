const base = process.env.API_BASE_INTERNAL || "http://api:8000";

async function proxyJson(request, path, { method, body } = {}) {
  try {
    const init = {
      method: method || request.method,
      headers: { "content-type": "application/json" },
    };
    if (body !== undefined) {
      init.body = typeof body === "string" ? body : JSON.stringify(body);
    } else if (method !== "GET" && method !== "DELETE") {
      init.body = await request.text();
    }
    const response = await fetch(`${base}${path}`, init);
    const data = await response.text();
    return new Response(data || "{}", {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    return new Response(
      JSON.stringify({ detail: error.message || "Internal server error" }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
}

export async function GET() {
  return proxyJson(null, "/queue/jobs", { method: "GET" });
}

export async function POST(request) {
  return proxyJson(request, "/queue/jobs", { method: "POST" });
}

export async function DELETE() {
  return proxyJson(null, "/queue/jobs", { method: "DELETE" });
}
