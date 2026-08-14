import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import router
from api.websocket import ws_router

app = FastAPI(title="Stock Auto Trader", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(ws_router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.on_event("startup")
async def auto_start_bot():
    from api.routes import engine
    if not engine.running:
        await engine.start()
    # 텔레그램 폴링 시작 (봇 명령어 수신)
    try:
        from notifications.telegram_bot import run_polling
        import asyncio
        asyncio.create_task(run_polling())
    except Exception as e:
        from loguru import logger
        logger.warning(f"[Main] 텔레그램 폴링 시작 실패: {e}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
