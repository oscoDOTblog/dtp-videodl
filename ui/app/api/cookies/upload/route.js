export async function POST(request) {
  const base = process.env.API_BASE_INTERNAL || "http://api:8000";

  try {
    const formData = await request.formData();
    const response = await fetch(`${base}/cookies/upload`, {
      method: "POST",
      body: formData,
    });
    const data = await response.text();
    return new Response(data, {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    return new Response(
      JSON.stringify({ detail: error.message || "Internal server error" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
}
