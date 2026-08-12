"""
Main Entry Point — Multi-Agent Telegram Crowd Simulator

Initializes and runs all system components:
  1. Database initialization
  2. Config loading & validation
  3. Telethon client startup (5 userbots)
  4. LLM Router initialization
  5. Orchestrator & Scheduler startup
  6. FastAPI IPC server (in background thread)
  7. Asyncio event loop management
  8. Graceful shutdown handling
"""

import os
import sys
import signal
import asyncio
import logging
import threading
from datetime import datetime

import uvicorn
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# ── Logging Setup ───────────────────────────────────────────────────

import logging.handlers

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            os.path.join(os.path.dirname(__file__), "data", "multibot.log"),
            maxBytes=5 * 1024 * 1024,  # 5 MB max per file
            backupCount=5,             # Keep 5 backup logs
            encoding="utf-8",
        ),
    ],
)

# Reduce noise from third-party libraries
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.INFO)

logger = logging.getLogger("main")


# ── Imports (after logging setup) ───────────────────────────────────

from core.database import init_db
from core.config_manager import load_config, register_reload_callback
from core.llm_router import LlmRouter
from core.telegram_client import TelegramClientManager
from core.orchestrator import Orchestrator
from core.scheduler import BurstScheduler
from api.server import app as fastapi_app, set_orchestrator, set_scheduler


# ── Global State ────────────────────────────────────────────────────

telegram_manager: TelegramClientManager = None
orchestrator: Orchestrator = None
scheduler: BurstScheduler = None
llm_router: LlmRouter = None
_shutdown_event = asyncio.Event()


# ── FastAPI Background Thread ──────────────────────────────────────

def run_fastapi_server(port: int = 8100):
    """Run the FastAPI IPC server in a separate thread."""
    config = uvicorn.Config(
        fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


# ── Initialization ──────────────────────────────────────────────────

async def initialize_system():
    """
    Initialize all system components in order.
    Returns True if successful, False otherwise.
    """
    global telegram_manager, orchestrator, scheduler, llm_router

    logger.info("=" * 60)
    logger.info("  MultiBotTele — Multi-Agent Telegram Crowd Simulator")
    logger.info("=" * 60)
    logger.info(f"  Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Step 1: Create data directory
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    logger.info("Step 1/7: Data directory ready")

    # Step 2: Initialize database
    try:
        await init_db()
        logger.info("Step 2/7: Database initialized ✓")
    except Exception as e:
        logger.error(f"Step 2/7: Database initialization failed: {e}")
        return False

    # Step 3: Load config
    try:
        config = load_config()
        logger.info(f"Step 3/7: Config loaded — {len(config.agents)} agents configured ✓")
    except Exception as e:
        logger.error(f"Step 3/7: Config loading failed: {e}")
        return False

    # Step 4: Initialize LLM Router
    try:
        llm_router = LlmRouter(
            primary=config.llm_providers.primary.name,
            primary_model=config.llm_providers.primary.model,
            fallback=config.llm_providers.fallback.name,
            fallback_model=config.llm_providers.fallback.model,
        )
        logger.info(
            f"Step 4/7: LLM Router initialized — "
            f"Primary: {config.llm_providers.primary.name}/{config.llm_providers.primary.model}, "
            f"Fallback: {config.llm_providers.fallback.name}/{config.llm_providers.fallback.model} ✓"
        )
    except Exception as e:
        logger.error(f"Step 4/7: LLM Router initialization failed: {e}")
        return False

    # Step 5: Initialize Telegram clients
    try:
        telegram_manager = TelegramClientManager()
        await telegram_manager.initialize(config)
        logger.info(
            f"Step 5/7: Telegram clients initialized — "
            f"{len(telegram_manager.clients)} clients ready ✓"
        )
    except Exception as e:
        logger.error(f"Step 5/7: Telegram client initialization failed: {e}")
        logger.warning("Continuing without Telegram clients (dashboard-only mode)")
        telegram_manager = TelegramClientManager()

    # Step 6: Initialize Orchestrator
    try:
        orchestrator = Orchestrator(
            telegram_manager=telegram_manager,
            llm_router=llm_router,
        )
        set_orchestrator(orchestrator)
        logger.info("Step 6/7: Orchestrator initialized ✓")
    except Exception as e:
        logger.error(f"Step 6/7: Orchestrator initialization failed: {e}")
        return False

    # Step 7: Initialize Scheduler
    try:
        scheduler = BurstScheduler()
        scheduler.set_burst_callback(orchestrator.run_scheduled_burst)
        set_scheduler(scheduler)
        logger.info("Step 7/7: Scheduler initialized ✓")
    except Exception as e:
        logger.error(f"Step 7/7: Scheduler initialization failed: {e}")
        return False

    # Register config reload callback
    async def on_config_reload(new_config):
        logger.info("Config reloaded — updating components...")
        if scheduler:
            await scheduler.reschedule(new_config)

    register_reload_callback(on_config_reload)

    logger.info("=" * 60)
    logger.info("  All components initialized successfully! 🚀")
    logger.info("=" * 60)
    return True


async def start_services(config):
    """Start all runtime services (Telegram clients, scheduler, etc.)."""
    global telegram_manager, orchestrator, scheduler

    # Start Telegram clients (if any are configured)
    if telegram_manager.clients:
        try:
            logger.info("Starting Telegram clients...")
            await telegram_manager.start_all()
            logger.info(f"Telegram clients started — {len(telegram_manager.clients)} active")
        except Exception as e:
            logger.error(f"Error starting Telegram clients: {e}")
            logger.warning("Continuing in dashboard-only mode")

    # Start orchestrator
    await orchestrator.start()
    logger.info("Orchestrator started")

    # Start scheduler (only if not kill-switched)
    if not config.global_settings.kill_switch:
        await scheduler.start(config)
        logger.info("Scheduler started")
    else:
        logger.warning("Kill switch is active — scheduler NOT started")


async def shutdown():
    """Graceful shutdown of all components."""
    logger.info("Initiating graceful shutdown...")

    global telegram_manager, orchestrator, scheduler, llm_router

    # Stop scheduler
    if scheduler:
        await scheduler.stop()
        logger.info("Scheduler stopped")

    # Stop orchestrator
    if orchestrator:
        await orchestrator.stop()
        logger.info("Orchestrator stopped")

    # Stop Telegram clients
    if telegram_manager:
        await telegram_manager.stop_all()
        logger.info("Telegram clients stopped")

    # Close LLM router
    if llm_router:
        await llm_router.close()
        logger.info("LLM Router closed")

    logger.info("Shutdown complete. Goodbye! 👋")


# ── Main Loop ───────────────────────────────────────────────────────

async def main():
    """Main async entry point."""

    # Initialize all components
    success = await initialize_system()
    if not success:
        logger.error("System initialization failed! Exiting.")
        sys.exit(1)

    config = load_config()

    # Start FastAPI server in background thread
    api_port = int(os.getenv("API_PORT", "8100"))
    api_thread = threading.Thread(
        target=run_fastapi_server,
        args=(api_port,),
        daemon=True,
    )
    api_thread.start()
    logger.info(f"FastAPI IPC server started on http://127.0.0.1:{api_port}")

    # Start all services
    await start_services(config)

    target_chat = config.global_settings.target_chat_id
    streamlit_port = os.getenv("STREAMLIT_PORT", "8501")

    logger.info("=" * 60)
    logger.info(f"  🎮 Dashboard: http://localhost:{streamlit_port}")
    logger.info(f"  🔌 API:       http://127.0.0.1:{api_port}/docs")
    logger.info(f"  🎯 Target:    Chat ID {target_chat}")
    logger.info(f"  👥 Agents:    {len(config.agents)} configured")
    logger.info("=" * 60)
    logger.info("System is running. Press Ctrl+C to stop.")

    # Keep the event loop running
    try:
        # If we have Telegram clients, keep them running
        if telegram_manager.clients:
            # Run until disconnected
            clients = list(telegram_manager.clients.values())
            if clients:
                await clients[0].run_until_disconnected()
            else:
                await _shutdown_event.wait()
        else:
            # No Telegram clients — just wait
            logger.info("Running in dashboard-only mode (no Telegram clients)")
            await _shutdown_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await shutdown()


# ── Entry Point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        # Handle Windows event loop policy
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C)")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
