export const runtime = "nodejs";
export const maxDuration = 300;

export async function POST(request) {
  const base = process.env.API_BASE_INTERNAL || "http://api:8000";
  const headers = {};
  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers["content-type"] = contentType;
  }
  const contentLength = request.headers.get("content-length");
  if (contentLength) {
    headers["content-length"] = contentLength;
  }

  try {
    const response = await fetch(`${base}/library/upload`, {
      method: "POST",
      headers,
      body: request.body,
      duplex: "half",
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
