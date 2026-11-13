import { NextResponse } from "next/server";

const BACKEND = process.env.JARVIS_BACKEND_URL || "http://127.0.0.1:8000";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/api/speak/status`, { cache: "no-store" });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      {
        voice_engine: "local",
        local: false,
        edge: false,
        fish_api_ready: false,
      },
      { status: 200 },
    );
  }
}