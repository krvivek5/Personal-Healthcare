from fastapi import APIRouter, Depends

from app.core.auth import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthenticatedUser)
async def get_me(current_user: AuthenticatedUser = Depends(get_current_user)):
    """Return identity details of the authenticated (anonymous or permanent) user."""
    return current_user
