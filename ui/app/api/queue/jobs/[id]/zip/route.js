const base = process.env.API_BASE_INTERNAL || "http://api:8000";

export async function POST(request, { params }) {
  const { id } = await params;
  try {
    const text = await request.text();
    const response = await fetch(`${base}/queue/jobs/${id}/zip`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: text || "{}",
    });
    if (!response.ok) {
      const data = await response.text();
      return new Response(data || "{}", {
        status: response.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    const buffer = await response.arrayBuffer();
    return new Response(buffer, {
      status: 200,
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition":
          response.headers.get("Content-Disposition") ||
          "attachment; filename=\"album.zip\"",
      },
    });
  } catch (error) {
    return new Response(
      JSON.stringify({ detail: error.message || "Internal server error" }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
}
