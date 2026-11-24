from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["auth"])

@router.api_route("/api/me", methods=["GET", "POST"])
@router.api_route("/api/me/", methods=["GET", "POST"])
async def api_me():
    return {
        "authenticated": True,
        "dev_mode": True,
        "user": {
            "id": 1,
            "email": "learner@querynova.local",
            "name": "SQL Learner",
            "picture": None,
            "role": "learner"
        },
    }

@router.api_route("/auth/login", methods=["GET", "POST"])
@router.api_route("/auth/login/", methods=["GET", "POST"])
async def auth_login():
    return RedirectResponse(url="/", status_code=302)

@router.api_route("/auth/logout", methods=["GET", "POST"])
@router.api_route("/auth/logout/", methods=["GET", "POST"])
async def auth_logout():
    return RedirectResponse(url="/", status_code=302)

def configure_auth(app) -> None:
    app.include_router(router)
