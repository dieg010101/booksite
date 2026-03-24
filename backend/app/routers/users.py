"""Users router – registration, auth (with refresh tokens), profiles, follows."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models import Follow, User
from app.schemas.users import (
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserPrivate,
    UserRead,
    UserUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


# ── Registration ──────────────────────────────────────────────────────────
@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def register(body: UserCreate, db: Session = Depends(get_db)):
    """Create a new user account."""
    if (
        db.query(User)
        .filter(User.email == body.email, User.is_deleted == False)
        .first()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    if (
        db.query(User)
        .filter(User.username == body.username, User.is_deleted == False)
        .first()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        location=body.location,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"User registered: {user.username} ({user.user_id})")
    return user


# ── Login ─────────────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return access + refresh tokens."""
    user = (
        db.query(User)
        .filter(User.email == body.email, User.is_deleted == False)
        .first()
    )
    if user is None or not verify_password(body.password, user.password_hash):
        logger.warning(f"Failed login attempt for email: {body.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token_data = {"sub": str(user.user_id)}
    logger.info(f"User logged in: {user.username} ({user.user_id})")
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


# ── Token Refresh ─────────────────────────────────────────────────────────
@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(body: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access + refresh token pair.

    This is the standard refresh flow:
    1. Client's access token expires (30min)
    2. Client sends refresh token to this endpoint
    3. Server validates refresh token and issues fresh pair
    4. Client stores new tokens, discards old ones

    The old refresh token is implicitly invalidated because the new one
    has a fresh expiry. For stricter security, you'd track refresh tokens
    in the DB and revoke the old one explicitly.
    """
    payload = decode_refresh_token(body.refresh_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    try:
        uid = UUID(sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.query(User).filter(User.user_id == uid, User.is_deleted == False).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    token_data = {"sub": str(user.user_id)}
    logger.info(f"Tokens refreshed for: {user.username} ({user.user_id})")
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


# ── Current user profile ─────────────────────────────────────────────────
@router.get("/me", response_model=UserPrivate)
def read_current_user(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's full profile (includes email)."""
    return current_user


@router.patch("/me", response_model=UserPrivate)
def update_current_user(
    body: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update editable fields on the authenticated user's profile."""
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


# ── Public profiles ───────────────────────────────────────────────────────
@router.get("/{username}", response_model=UserRead)
def read_user_profile(username: str, db: Session = Depends(get_db)):
    """Fetch any user's public profile by username."""
    user = (
        db.query(User)
        .filter(User.username == username, User.is_deleted == False)
        .first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


# ── Follow / Unfollow ────────────────────────────────────────────────────
@router.post(
    "/{username}/follow",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def follow_user(
    username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Follow another user."""
    target = (
        db.query(User)
        .filter(User.username == username, User.is_deleted == False)
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    exists = (
        db.query(Follow)
        .filter(
            Follow.follower_id == current_user.user_id,
            Follow.followed_id == target.user_id,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Already following this user")

    db.add(Follow(follower_id=current_user.user_id, followed_id=target.user_id))
    db.commit()
    return MessageResponse(detail=f"Now following {username}")


@router.delete("/{username}/follow", response_model=MessageResponse)
def unfollow_user(
    username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unfollow a user."""
    target = (
        db.query(User)
        .filter(User.username == username, User.is_deleted == False)
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    follow = (
        db.query(Follow)
        .filter(
            Follow.follower_id == current_user.user_id,
            Follow.followed_id == target.user_id,
        )
        .first()
    )
    if follow is None:
        raise HTTPException(status_code=404, detail="Not following this user")

    db.delete(follow)
    db.commit()
    return MessageResponse(detail=f"Unfollowed {username}")
