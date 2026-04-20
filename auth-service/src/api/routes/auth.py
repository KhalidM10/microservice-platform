from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.core.security import decode_token, create_access_token, create_refresh_token
from src.schemas.user import UserRegister, UserLogin, UserResponse, TokenResponse, RefreshRequest
from src.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    user = await auth_service.register_user(db, data)
    if not user:
        raise HTTPException(status_code=409, detail="Email already registered")
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    user = await auth_service.authenticate_user(db, data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return auth_service.issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(data.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = await auth_service.get_user_by_id(db, payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {
        "access_token": create_access_token(user.id, user.role),
        "refresh_token": create_refresh_token(user.id, user.role),
        "token_type": "bearer",
    }


@router.get("/me", response_model=UserResponse)
async def me(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await auth_service.get_user_by_id(db, payload["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    # Token blacklisting via Redis is handled at the api-gateway level.
    # Here we simply acknowledge the logout — stateless JWT invalidation
    # is enforced by the gateway's Redis blacklist check.
    return {"message": "Logged out successfully"}
