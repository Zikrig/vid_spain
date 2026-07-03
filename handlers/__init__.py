from aiogram import Router

from handlers.admin import router as admin_router
from handlers.admin_channels import router as admin_channels_router
from handlers.funnel import router as funnel_router
from handlers.start import router as start_router

router = Router()
router.include_router(start_router)
router.include_router(funnel_router)
router.include_router(admin_router)
router.include_router(admin_channels_router)
