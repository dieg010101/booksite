"""Feed router — likes, reposts, fan-out-on-write timeline, feed reading."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import (
    ActivityTypeEnum,
    BookEntry,
    Follow,
    Like,
    Repost,
    Timeline,
    User,
)
from app.schemas.feed import (
    FeedResponse,
    LikeRead,
    MessageResponse,
    RepostRead,
    TimelineRead,
)

router = APIRouter(prefix="/api/v1", tags=["feed"])


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: fan-out on write
# ═══════════════════════════════════════════════════════════════════════════


def _fan_out_to_followers(
    db: Session,
    actor: User,
    entry_id: UUID,
    activity_type: ActivityTypeEnum,
):
    """
    Push a timeline entry to all of the actor's followers.

    This is the simple "fan-out on write" approach from DDIA ch. 1.
    For users with huge follower counts, you'd switch to pull-based
    (fan-out on read) — but for now, push is fine.

    Also adds the entry to the actor's own timeline so they see
    their own activity in their feed.
    """
    # Get all follower user_ids
    follower_ids = (
        db.query(Follow.follower_id).filter(Follow.followed_id == actor.user_id).all()
    )
    # Collect recipient ids: all followers + the actor themselves
    recipient_ids = [fid for (fid,) in follower_ids]
    recipient_ids.append(actor.user_id)

    now = datetime.now(timezone.utc)
    for uid in recipient_ids:
        # Skip duplicates (idempotent — matches uq_timeline_no_dupes)
        existing = (
            db.query(Timeline)
            .filter(
                Timeline.user_id == uid,
                Timeline.entry_id == entry_id,
                Timeline.activity_type == activity_type,
            )
            .first()
        )
        if existing is None:
            db.add(
                Timeline(
                    user_id=uid,
                    entry_id=entry_id,
                    activity_type=activity_type,
                    created_at=now,
                )
            )


# ═══════════════════════════════════════════════════════════════════════════
# LIKES
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/entries/{entry_id}/like",
    response_model=LikeRead,
    status_code=status.HTTP_201_CREATED,
)
def like_entry(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Like a book entry."""
    entry = (
        db.query(BookEntry)
        .filter(BookEntry.entry_id == entry_id, BookEntry.is_deleted == False)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    existing = (
        db.query(Like)
        .filter(Like.user_id == current_user.user_id, Like.entry_id == entry_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already liked")

    like = Like(user_id=current_user.user_id, entry_id=entry_id)
    db.add(like)
    db.commit()
    db.refresh(like)
    return like


@router.delete("/entries/{entry_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def unlike_entry(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a like from a book entry."""
    like = (
        db.query(Like)
        .filter(Like.user_id == current_user.user_id, Like.entry_id == entry_id)
        .first()
    )
    if like is None:
        raise HTTPException(status_code=404, detail="Like not found")

    db.delete(like)
    db.commit()


@router.get("/entries/{entry_id}/likes", response_model=list[LikeRead])
def list_entry_likes(
    entry_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List users who liked an entry."""
    likes = (
        db.query(Like)
        .filter(Like.entry_id == entry_id)
        .order_by(Like.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return likes


# ═══════════════════════════════════════════════════════════════════════════
# REPOSTS
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/entries/{entry_id}/repost",
    response_model=RepostRead,
    status_code=status.HTTP_201_CREATED,
)
def repost_entry(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Repost a book entry. Fans out to followers' timelines."""
    entry = (
        db.query(BookEntry)
        .filter(BookEntry.entry_id == entry_id, BookEntry.is_deleted == False)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    existing = (
        db.query(Repost)
        .filter(Repost.user_id == current_user.user_id, Repost.entry_id == entry_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already reposted")

    repost = Repost(user_id=current_user.user_id, entry_id=entry_id)
    db.add(repost)

    # Fan-out: push repost to followers' timelines
    _fan_out_to_followers(db, current_user, entry_id, ActivityTypeEnum.REPOST)

    db.commit()
    db.refresh(repost)
    return repost


@router.delete("/entries/{entry_id}/repost", status_code=status.HTTP_204_NO_CONTENT)
def unrepost_entry(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a repost."""
    repost = (
        db.query(Repost)
        .filter(Repost.user_id == current_user.user_id, Repost.entry_id == entry_id)
        .first()
    )
    if repost is None:
        raise HTTPException(status_code=404, detail="Repost not found")

    db.delete(repost)
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════
# FEED (following timeline)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    cursor: datetime | None = Query(
        default=None, description="created_at cursor for pagination"
    ),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the authenticated user's following timeline.

    Uses cursor-based pagination (seek method) on created_at DESC.
    Pass the `created_at` of the last item as `cursor` to get the next page.

    Reference: SPE ch. 7 — cursor/seek is O(1) vs OFFSET which is O(N).
    """
    query = db.query(Timeline).filter(Timeline.user_id == current_user.user_id)

    if cursor is not None:
        query = query.filter(Timeline.created_at < cursor)

    items = (
        query.order_by(Timeline.created_at.desc())
        .limit(limit + 1)  # fetch one extra to determine has_more
        .all()
    )

    has_more = len(items) > limit
    if has_more:
        items = items[:limit]

    return FeedResponse(items=items, has_more=has_more)
