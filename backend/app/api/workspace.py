import uuid
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/workspace", tags=["workspace"])

# In-memory user-scoped store to demonstrate and test strict user data isolation
# in Milestone 2 (Replaced by PostgreSQL patient entities in Milestone 3)
_workspace_store: Dict[str, List[dict]] = {}


class WorkspaceItemCreate(BaseModel):
    title: str
    content: str


class WorkspaceItem(BaseModel):
    id: str
    user_id: str
    title: str
    content: str


@router.get("", response_model=List[dict])
async def get_user_workspace(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Retrieve items belonging strictly to the requesting user."""
    return _workspace_store.get(current_user.id, [])


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def create_workspace_item(
    item: WorkspaceItemCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Create an item scoped strictly to the authenticated user's ID."""
    new_item = {
        "id": str(uuid.uuid4()),
        "user_id": current_user.id,
        "title": item.title,
        "content": item.content,
    }
    _workspace_store.setdefault(current_user.id, []).append(new_item)
    return new_item


@router.get("/items/{item_id}")
async def get_workspace_item(
    item_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Retrieve an item, enforcing user isolation."""
    items = _workspace_store.get(current_user.id, [])
    for it in items:
        if it["id"] == item_id:
            return it

    # Check if item exists for someone else to verify isolation
    for uid, uitems in _workspace_store.items():
        if uid != current_user.id:
            for it in uitems:
                if it["id"] == item_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not authorized to access this resource",
                    )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Item not found",
    )
