export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const jobId = searchParams.get("jobId");
  
  if (!jobId) {
    return new Response(JSON.stringify({ detail: "jobId parameter required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const base = process.env.API_BASE_INTERNAL || "http://api:8000";

  try {
    const response = await fetch(`${base}/progress/${jobId}`);
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

