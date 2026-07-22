const base = process.env.API_BASE_INTERNAL || "http://api:8000";

async function proxy(path, init = {}) {
  try {
    const response = await fetch(`${base}${path}`, {
      headers: { "content-type": "application/json", ...(init.headers || {}) },
      ...init,
    });
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

export async function GET(_request, { params }) {
  const { id } = await params;
  return proxy(`/queue/jobs/${id}`, { method: "GET" });
}

export async function DELETE(_request, { params }) {
  const { id } = await params;
  return proxy(`/queue/jobs/${id}`, { method: "DELETE" });
}
