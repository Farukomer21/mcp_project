"""Gemini tabanli satis danismanizi calistiran ana agent modulu."""

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp.client.sse import sse_client

from mcp_utils import SSE_URL, SanitizedClientSession
from prompts import SYSTEM_INSTRUCTION

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


async def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY tanimli degil. .env dosyasina ekleyin.")

    client = genai.Client(api_key=api_key)

    print(f"MCP HTTP (SSE) sunucusuna baglaniliyor: {SSE_URL} ...")

    try:
        async with sse_client(SSE_URL) as (read, write):

            async with SanitizedClientSession(read, write) as session:

                await session.initialize()

                tools = await session.list_tools()
                print(
                    f"MCP HTTP (SSE) baglandi — {len(tools.tools)} tool: "
                    f"{', '.join(t.name for t in tools.tools)}\n"
                )

                config = {
                    "system_instruction": SYSTEM_INSTRUCTION,
                    "tools": [session],
                    "temperature": 0.3,
                    "automatic_function_calling": {"maximum_remote_calls": 8},
                }

                history: list[types.Content] = []

                # Oturum boyunca harcanan toplam birikimli (cumulative) token sayaçları
                cum_prompt_tokens = 0
                cum_candidate_tokens = 0
                cum_total_tokens = 0

                print("Ada: Merhaba! Ben Ada, satis danismaniniz. Nasil yardimci olabilirim?")
                print("(cikmak icin 'q')\n")

                while True:
                    try:
                        user_input = input("Siz: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if user_input.lower() in {"q", "quit", "exit", "cik"}:
                        break
                    if not user_input:
                        continue

                    history.append(
                        types.Content(role="user", parts=[types.Part(text=user_input)])
                    )

                   
                    response = await client.aio.models.generate_content(
                        model=MODEL,
                        contents=history,
                        config=config,
                    )

                    print("\n" + "=" * 60)
                    print("🔍 [BU TURDA GERÇEKLEŞEN MCP ÇAĞRILARI VE YANITLARI (FULL)]")
                    print("=" * 60)

                    afc_history = response.automatic_function_calling_history or []
                    tool_called = False

                    for content in afc_history:
                        if hasattr(content, "parts") and content.parts:
                            for p in content.parts:
                                if hasattr(p, "function_call") and p.function_call:
                                    tool_called = True
                                    print(f"🔧 [TOOL ÇAĞRILDI]: {p.function_call.name}({p.function_call.args})")
                                elif hasattr(p, "function_response") and p.function_response:
                                    print(f"📦 [MCP DÖNEN FULL CEVAP - {p.function_response.name}]:")
                                    resp_dict = p.function_response.response
                                    try:
                                        print(json.dumps(resp_dict, indent=2, ensure_ascii=False, default=str))
                                    except Exception:
                                        print(resp_dict)

                    if not tool_called:
                        print(" (Bu soru için herhangi bir MCP tool'u çağrılmadı, yanıt doğrudan üretildi)")

                    print("-" * 60)

                    # ================= TOKEN KULLANIM BİLGİSİ =================
                    if hasattr(response, "usage_metadata") and response.usage_metadata:
                        meta = response.usage_metadata
                        prompt_tokens = getattr(meta, "prompt_token_count", 0)
                        candidate_tokens = getattr(meta, "candidates_token_count", 0)
                        total_tokens = getattr(meta, "total_token_count", 0)

                        # Oturum toplamına ekle
                        cum_prompt_tokens += prompt_tokens
                        cum_candidate_tokens += candidate_tokens
                        cum_total_tokens += total_tokens

                        print("📊 [BU İSTEĞİN TOKEN İSTATİSTİĞİ]")
                        print(f"   • Giden (Prompt) Token      : {prompt_tokens}")
                        print(f"   • Gelen (Candidates) Token  : {candidate_tokens}")
                        print(f"   • Bu İstek Toplamı          : {total_tokens}")
                        print("-" * 60)
                        print("📈 [OTURUM TOPLAM HARCANAN TOKEN (CUMULATIVE)]")
                        print(f"   • Toplam Giden (Prompt)     : {cum_prompt_tokens}")
                        print(f"   • Toplam Gelen (Candidates) : {cum_candidate_tokens}")
                        print(f"   • TOPLAM SOHBET MALİYETİ    : {cum_total_tokens} Token")

                    print("=" * 60 + "\n")

                    if response.automatic_function_calling_history:
                        history = list(response.automatic_function_calling_history)
                    if response.candidates and response.candidates[0].content:
                        history.append(response.candidates[0].content)

                    print(f"Ada: {response.text}\n")

        print(f"\nOturum kapatıldı. Sohbet boyunca harcanan TOPLAM MALİYET: {cum_total_tokens} Token.")
        print("Gorusmek uzere!")

    except Exception as e:
        print(f"\nHATA: MCP HTTP sunucusuna bağlanılamadı ({SSE_URL}).")
        print("Lütfen önce MCP sunucusunu veya Docker konteynerini başlatın:")
        print(" -> Docker ile: docker compose up")
        print(" -> Yerel HTTP ile: python3 server.py\n")
        print(f"Detay: {e}")


if __name__ == "__main__":
    asyncio.run(main())
