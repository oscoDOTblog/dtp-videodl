const base = process.env.API_BASE_INTERNAL || "http://api:8000";

export async function POST() {
  try {
    const response = await fetch(`${base}/queue/jobs/clear`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
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
