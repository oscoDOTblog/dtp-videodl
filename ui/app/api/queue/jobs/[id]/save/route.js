const base = process.env.API_BASE_INTERNAL || "http://api:8000";

async function proxyAction(request, id, action) {
  try {
    const text = await request.text();
    const response = await fetch(`${base}/queue/jobs/${id}/${action}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: text || "{}",
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

export async function POST(request, { params }) {
  const { id } = await params;
  return proxyAction(request, id, "save");
}
