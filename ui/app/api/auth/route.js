import { NextResponse } from 'next/server';

function authConfig() {
  const sitePassword = process.env.SITE_PASSWORD?.trim();
  return {
    required: Boolean(sitePassword),
    sitePassword: sitePassword || '',
  };
}

export async function GET() {
  const { required } = authConfig();
  return NextResponse.json({ required });
}

export async function POST(request) {
  try {
    const { password } = await request.json();
    const { required, sitePassword } = authConfig();

    if (!required) {
      return NextResponse.json({ success: true });
    }

    if (password === sitePassword) {
      return NextResponse.json({ success: true });
    }

    return NextResponse.json({ error: 'Invalid password' }, { status: 401 });
  } catch {
    return NextResponse.json({ error: 'Invalid request' }, { status: 400 });
  }
}
