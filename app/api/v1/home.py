from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models import User
from app.schemas.user import UserRead

router = APIRouter(tags=["home"])


@router.get("/home")
async def home(current_user: User = Depends(get_current_user)) -> dict[str, object]:
    return {
        "message": f"Welcome home, {current_user.email}",
        "user": UserRead.model_validate(current_user),
    }
