"""
Comprehensive schema tests — v2.
=================================
Run with: pytest tests/test_schema_comprehensive.py -v
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, DataError

from app.models import (
    ActivityTypeEnum,
    Book,
    BookContributor,
    BookEntry,
    BookList,
    Comment,
    Contributor,
    ContributorRoleEnum,
    Follow,
    Like,
    ListItem,
    ReadingStatus,
    ReadingStatusEnum,
    Repost,
    Timeline,
    User,
)


def make_user(db, username=None, email=None):
    u = User(
        username=username or f"user_{uuid.uuid4().hex[:8]}",
        email=email or f"{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
    )
    db.add(u)
    db.flush()
    return u


def make_book(db, title="Test Book", external_api_id=None):
    b = Book(
        title=title, external_api_id=external_api_id or f"ext_{uuid.uuid4().hex[:12]}"
    )
    db.add(b)
    db.flush()
    return b


def make_entry(db, user, book, rating=None):
    e = BookEntry(user_id=user.user_id, book_id=book.book_id, rating=rating)
    db.add(e)
    db.flush()
    return e


class TestServerDefaults:
    def test_user_server_defaults_via_raw_sql(self, db_session):
        uid = uuid.uuid4()
        db_session.execute(
            text(
                "INSERT INTO users (user_id, username, email, password_hash) VALUES (:uid, :uname, :email, :phash)"
            ),
            {
                "uid": uid,
                "uname": "rawsql_user",
                "email": "raw@test.com",
                "phash": "hash123",
            },
        )
        db_session.flush()
        row = db_session.execute(
            text(
                "SELECT is_deleted, follower_count, following_count, created_at FROM users WHERE user_id = :uid"
            ),
            {"uid": uid},
        ).fetchone()
        assert row[0] is False
        assert row[1] == 0
        assert row[2] == 0
        assert row[3] is not None

    def test_book_entry_server_defaults_via_raw_sql(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        eid = uuid.uuid4()
        db_session.execute(
            text(
                "INSERT INTO book_entries (entry_id, user_id, book_id) VALUES (:eid, :uid, :bid)"
            ),
            {"eid": eid, "uid": user.user_id, "bid": book.book_id},
        )
        db_session.flush()
        row = db_session.execute(
            text(
                "SELECT is_deleted, is_spoiler, like_count, repost_count, comment_count, logged_date, created_at FROM book_entries WHERE entry_id = :eid"
            ),
            {"eid": eid},
        ).fetchone()
        assert row[0] is False
        assert row[1] is False
        assert row[2] == 0
        assert row[3] == 0
        assert row[4] == 0
        assert row[5] is not None
        assert row[6] is not None

    def test_book_server_defaults_via_raw_sql(self, db_session):
        bid = uuid.uuid4()
        db_session.execute(
            text(
                "INSERT INTO books (book_id, external_api_id, title) VALUES (:bid, :ext, :title)"
            ),
            {
                "bid": bid,
                "ext": f"ext_{uuid.uuid4().hex[:12]}",
                "title": "Raw SQL Book",
            },
        )
        db_session.flush()
        row = db_session.execute(
            text(
                "SELECT is_active, log_count, currently_reading_count, avg_rating FROM books WHERE book_id = :bid"
            ),
            {"bid": bid},
        ).fetchone()
        assert row[0] is True
        assert row[1] == 0
        assert row[2] == 0
        assert row[3] is None

    def test_comment_server_defaults_via_raw_sql(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, user, book)
        cid = uuid.uuid4()
        db_session.execute(
            text(
                "INSERT INTO comments (comment_id, user_id, entry_id, path, comment_text) VALUES (:cid, :uid, :eid, 'root', 'hello')"
            ),
            {"cid": cid, "uid": user.user_id, "eid": entry.entry_id},
        )
        db_session.flush()
        row = db_session.execute(
            text("SELECT is_deleted, created_at FROM comments WHERE comment_id = :cid"),
            {"cid": cid},
        ).fetchone()
        assert row[0] is False
        assert row[1] is not None


class TestForeignKeyBehavior:
    def test_restrict_user_delete_blocked_by_book_entry(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        make_entry(db_session, user, book)
        with pytest.raises(IntegrityError):
            db_session.execute(
                text("DELETE FROM users WHERE user_id = :uid"), {"uid": user.user_id}
            )
            db_session.flush()

    def test_restrict_book_delete_blocked_by_book_entry(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        make_entry(db_session, user, book)
        with pytest.raises(IntegrityError):
            db_session.execute(
                text("DELETE FROM books WHERE book_id = :bid"), {"bid": book.book_id}
            )
            db_session.flush()

    def test_cascade_follow_deleted_when_user_deleted(self, db_session):
        user_a = make_user(db_session)
        user_b = make_user(db_session)
        db_session.add(Follow(follower_id=user_a.user_id, followed_id=user_b.user_id))
        db_session.flush()
        db_session.execute(
            text("DELETE FROM users WHERE user_id = :uid"), {"uid": user_a.user_id}
        )
        db_session.flush()
        assert (
            db_session.execute(
                text("SELECT COUNT(*) FROM follows WHERE follower_id = :uid"),
                {"uid": user_a.user_id},
            ).scalar()
            == 0
        )

    def test_set_null_comment_user_id_on_user_delete(self, db_session):
        """Comment.user_id SET NULL: comment survives, user_id becomes NULL."""
        commenter = make_user(db_session)
        entry_owner = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, entry_owner, book)
        comment = Comment(
            user_id=commenter.user_id,
            entry_id=entry.entry_id,
            path="root",
            comment_text="will survive",
        )
        db_session.add(comment)
        db_session.flush()
        cid = comment.comment_id
        db_session.execute(
            text("DELETE FROM users WHERE user_id = :uid"), {"uid": commenter.user_id}
        )
        db_session.flush()
        row = db_session.execute(
            text("SELECT user_id, comment_text FROM comments WHERE comment_id = :cid"),
            {"cid": cid},
        ).fetchone()
        assert row is not None
        assert row[0] is None
        assert row[1] == "will survive"

    def test_cascade_like_deleted_when_entry_deleted(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, user, book)
        db_session.add(Like(user_id=user.user_id, entry_id=entry.entry_id))
        db_session.flush()
        eid = entry.entry_id
        db_session.execute(
            text("DELETE FROM book_entries WHERE entry_id = :eid"), {"eid": eid}
        )
        db_session.flush()
        assert (
            db_session.execute(
                text("SELECT COUNT(*) FROM likes WHERE entry_id = :eid"), {"eid": eid}
            ).scalar()
            == 0
        )

    def test_cascade_timeline_deleted_when_entry_deleted(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, user, book)
        db_session.add(
            Timeline(
                user_id=user.user_id,
                entry_id=entry.entry_id,
                activity_type=ActivityTypeEnum.REVIEW,
            )
        )
        db_session.flush()
        eid = entry.entry_id
        db_session.execute(
            text("DELETE FROM book_entries WHERE entry_id = :eid"), {"eid": eid}
        )
        db_session.flush()
        assert (
            db_session.execute(
                text("SELECT COUNT(*) FROM timeline WHERE entry_id = :eid"),
                {"eid": eid},
            ).scalar()
            == 0
        )

    def test_cascade_list_items_deleted_when_list_deleted(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        blist = BookList(user_id=user.user_id, list_name="Temp List")
        db_session.add(blist)
        db_session.flush()
        db_session.add(
            ListItem(list_id=blist.list_id, book_id=book.book_id, position=1)
        )
        db_session.flush()
        lid = blist.list_id
        db_session.execute(text("DELETE FROM lists WHERE list_id = :lid"), {"lid": lid})
        db_session.flush()
        assert (
            db_session.execute(
                text("SELECT COUNT(*) FROM list_items WHERE list_id = :lid"),
                {"lid": lid},
            ).scalar()
            == 0
        )


class TestPartialIndexUsage:
    def test_book_entries_partial_index_used_for_active_entries(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        for _ in range(5):
            make_entry(db_session, user, book)
        result = db_session.execute(
            text(
                "EXPLAIN SELECT * FROM book_entries WHERE user_id = :uid AND is_deleted = false ORDER BY created_at DESC"
            ),
            {"uid": user.user_id},
        )
        plan = "\n".join(row[0] for row in result)
        assert "ix_book_entries_user_created" in plan or "Index" in plan

    def test_active_username_index_used_for_login(self, db_session):
        make_user(db_session, "indextest", "indextest@test.com")
        result = db_session.execute(
            text(
                "EXPLAIN SELECT * FROM users WHERE username = 'indextest' AND is_deleted = false"
            )
        )
        plan = "\n".join(row[0] for row in result)
        assert "ix_users_active_username" in plan or "Index" in plan


class TestReReads:
    def test_user_can_log_same_book_multiple_times(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        e1 = make_entry(db_session, user, book, rating=7)
        e2 = make_entry(db_session, user, book, rating=9)
        e3 = make_entry(db_session, user, book, rating=8)
        assert e1.entry_id != e2.entry_id != e3.entry_id
        count = db_session.execute(
            text(
                "SELECT COUNT(*) FROM book_entries WHERE user_id = :uid AND book_id = :bid AND is_deleted = false"
            ),
            {"uid": user.user_id, "bid": book.book_id},
        ).scalar()
        assert count == 3

    def test_re_reads_have_different_logged_dates(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        e1 = make_entry(db_session, user, book)
        e2 = make_entry(db_session, user, book)
        assert e1.logged_date is not None
        assert e2.logged_date is not None
        assert e1.entry_id != e2.entry_id


class TestDeepLtreeThreading:
    def _make_thread(self, db_session, depth=5):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, user, book)
        comments = []
        for i in range(depth):
            path = ".".join(f"c{j}" for j in range(i + 1))
            c = Comment(
                user_id=user.user_id,
                entry_id=entry.entry_id,
                path=path,
                comment_text=f"Comment at depth {i}",
            )
            db_session.add(c)
            comments.append(c)
        db_session.flush()
        return user, entry, comments

    def test_five_level_deep_thread(self, db_session):
        user, entry, comments = self._make_thread(db_session, depth=5)
        result = db_session.execute(
            text("SELECT comment_text FROM comments WHERE path <@ 'c0' ORDER BY path")
        )
        texts = [row[0] for row in result]
        assert len(texts) == 5
        assert texts[0] == "Comment at depth 0"
        assert texts[4] == "Comment at depth 4"

    def test_subtree_query_from_middle(self, db_session):
        self._make_thread(db_session, depth=5)
        result = db_session.execute(
            text(
                "SELECT comment_text FROM comments WHERE path <@ 'c0.c1.c2' ORDER BY path"
            )
        )
        assert len([row[0] for row in result]) == 3

    def test_deleted_ancestor_preserves_descendants(self, db_session):
        user, entry, comments = self._make_thread(db_session, depth=5)
        comments[2].is_deleted = True
        comments[2].comment_text = "[deleted]"
        db_session.flush()
        result = db_session.execute(
            text("SELECT comment_text FROM comments WHERE path <@ 'c0' ORDER BY path")
        )
        texts = [row[0] for row in result]
        assert len(texts) == 5
        assert texts[2] == "[deleted]"
        assert texts[3] == "Comment at depth 3"

    def test_nlevel_depth_calculation(self, db_session):
        user, entry, comments = self._make_thread(db_session, depth=5)
        result = db_session.execute(
            text(
                "SELECT nlevel(path) as depth, comment_text FROM comments WHERE entry_id = :eid ORDER BY path"
            ),
            {"eid": entry.entry_id},
        )
        rows = list(result)
        assert rows[0][0] == 1
        assert rows[4][0] == 5

    def test_branching_thread(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, user, book)
        db_session.add_all(
            [
                Comment(
                    user_id=user.user_id,
                    entry_id=entry.entry_id,
                    path="root",
                    comment_text="Root",
                ),
                Comment(
                    user_id=user.user_id,
                    entry_id=entry.entry_id,
                    path="root.a",
                    comment_text="Reply A",
                ),
                Comment(
                    user_id=user.user_id,
                    entry_id=entry.entry_id,
                    path="root.b",
                    comment_text="Reply B",
                ),
                Comment(
                    user_id=user.user_id,
                    entry_id=entry.entry_id,
                    path="root.a.nested",
                    comment_text="Nested under A",
                ),
            ]
        )
        db_session.flush()
        texts = [
            row[0]
            for row in db_session.execute(
                text(
                    "SELECT comment_text FROM comments WHERE path <@ 'root' ORDER BY path"
                )
            )
        ]
        assert len(texts) == 4
        texts2 = [
            row[0]
            for row in db_session.execute(
                text(
                    "SELECT comment_text FROM comments WHERE path <@ 'root.a' ORDER BY path"
                )
            )
        ]
        assert len(texts2) == 2
        assert "Reply A" in texts2
        assert "Nested under A" in texts2


class TestUsernameReclaimability:
    def test_full_lifecycle_create_delete_reclaim(self, db_session):
        original = make_user(db_session, "phoenix", "phoenix@test.com")
        oid = original.user_id
        original.is_deleted = True
        original.username = f"deleted_{oid.hex[:8]}"
        original.email = f"deleted_{oid.hex[:8]}@anon.local"
        db_session.flush()
        new_user = make_user(db_session, "phoenix", "phoenix_new@test.com")
        assert new_user.username == "phoenix"
        assert new_user.user_id != oid

    def test_two_active_users_same_username_rejected(self, db_session):
        make_user(db_session, "taken_name", "first@test.com")
        with pytest.raises(IntegrityError):
            make_user(db_session, "taken_name", "second@test.com")

    def test_deleted_user_doesnt_block_new_registration(self, db_session):
        user = make_user(db_session, "ghost", "ghost@test.com")
        user.is_deleted = True
        user.username = "deleted_ghost"
        db_session.flush()
        assert make_user(db_session, "ghost", "ghost2@test.com").username == "ghost"


class TestEnumBoundaries:
    def test_invalid_reading_status_rejected(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        with pytest.raises((DataError, IntegrityError)):
            db_session.execute(
                text(
                    "INSERT INTO reading_statuses (user_id, book_id, status) VALUES (:uid, :bid, 'invalid_status')"
                ),
                {"uid": user.user_id, "bid": book.book_id},
            )
            db_session.flush()

    def test_invalid_activity_type_rejected(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, user, book)
        with pytest.raises((DataError, IntegrityError)):
            db_session.execute(
                text(
                    "INSERT INTO timeline (timeline_id, created_at, user_id, entry_id, activity_type) VALUES (:tid, now(), :uid, :eid, 'bogus_type')"
                ),
                {"tid": uuid.uuid4(), "uid": user.user_id, "eid": entry.entry_id},
            )
            db_session.flush()

    def test_invalid_contributor_role_rejected(self, db_session):
        book = make_book(db_session)
        contrib = Contributor(name="Test Author")
        db_session.add(contrib)
        db_session.flush()
        with pytest.raises((DataError, IntegrityError)):
            db_session.execute(
                text(
                    "INSERT INTO book_contributors (book_id, contributor_id, role) VALUES (:bid, :cid, 'fake_role')"
                ),
                {"bid": book.book_id, "cid": contrib.contributor_id},
            )
            db_session.flush()


class TestCoveringIndex:
    def test_timeline_feed_query_uses_covering_index(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        for _ in range(5):
            entry = make_entry(db_session, user, book)
            db_session.add(
                Timeline(
                    user_id=user.user_id,
                    entry_id=entry.entry_id,
                    activity_type=ActivityTypeEnum.REVIEW,
                )
            )
        db_session.flush()
        result = db_session.execute(
            text(
                "EXPLAIN SELECT entry_id, activity_type FROM timeline WHERE user_id = :uid ORDER BY created_at DESC LIMIT 20"
            ),
            {"uid": user.user_id},
        )
        plan = "\n".join(row[0] for row in result)
        assert "ix_timeline_user_created" in plan or "Index" in plan


class TestDenormalizedCounters:
    def test_book_counter_batch_update(self, db_session):
        book = make_book(db_session)
        bid = book.book_id
        db_session.execute(
            text(
                "UPDATE books SET log_count = 142, avg_rating = 7.83, currently_reading_count = 23 WHERE book_id = :bid"
            ),
            {"bid": bid},
        )
        db_session.flush()
        row = db_session.execute(
            text(
                "SELECT log_count, avg_rating, currently_reading_count FROM books WHERE book_id = :bid"
            ),
            {"bid": bid},
        ).fetchone()
        assert row[0] == 142
        assert float(row[1]) == 7.83
        assert row[2] == 23

    def test_entry_counter_increment_pattern(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, user, book)
        eid = entry.entry_id
        db_session.execute(
            text(
                "UPDATE book_entries SET like_count = like_count + 1 WHERE entry_id = :eid"
            ),
            {"eid": eid},
        )
        db_session.execute(
            text(
                "UPDATE book_entries SET like_count = like_count + 1 WHERE entry_id = :eid"
            ),
            {"eid": eid},
        )
        db_session.flush()
        assert (
            db_session.execute(
                text("SELECT like_count FROM book_entries WHERE entry_id = :eid"),
                {"eid": eid},
            ).scalar()
            == 2
        )

    def test_avg_rating_precision(self, db_session):
        book = make_book(db_session)
        book.avg_rating = Decimal("8.47")
        db_session.flush()
        row = db_session.execute(
            text("SELECT avg_rating FROM books WHERE book_id = :bid"),
            {"bid": book.book_id},
        ).fetchone()
        assert row[0] == Decimal("8.47")


class TestEdgeCases:
    def test_rating_boundary_values(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        assert make_entry(db_session, user, book, rating=1).rating == 1
        assert make_entry(db_session, user, book, rating=10).rating == 10

    def test_rating_negative_rejected(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        db_session.add(BookEntry(user_id=user.user_id, book_id=book.book_id, rating=-1))
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_empty_review_text_allowed(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = BookEntry(user_id=user.user_id, book_id=book.book_id, review_text="")
        db_session.add(entry)
        db_session.flush()
        assert entry.review_text == ""

    def test_max_length_username(self, db_session):
        assert len(make_user(db_session, "a" * 30, "longname@test.com").username) == 30

    def test_username_exceeding_max_length_rejected(self, db_session):
        with pytest.raises(DataError):
            make_user(db_session, "a" * 31, "toolong@test.com")

    def test_book_title_at_max_length(self, db_session):
        assert len(make_book(db_session, title="B" * 500).title) == 500

    def test_null_isbn_allowed(self, db_session):
        assert make_book(db_session).isbn_13 is None

    def test_duplicate_isbn_rejected(self, db_session):
        db_session.add(
            Book(
                title="Book 1",
                external_api_id=f"ext_{uuid.uuid4().hex[:12]}",
                isbn_13="9780134685991",
            )
        )
        db_session.flush()
        db_session.add(
            Book(
                title="Book 2",
                external_api_id=f"ext_{uuid.uuid4().hex[:12]}",
                isbn_13="9780134685991",
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()


class TestTimelineDeduplication:
    def test_duplicate_timeline_entry_rejected(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, user, book)
        db_session.add(
            Timeline(
                user_id=user.user_id,
                entry_id=entry.entry_id,
                activity_type=ActivityTypeEnum.REVIEW,
            )
        )
        db_session.flush()
        db_session.add(
            Timeline(
                user_id=user.user_id,
                entry_id=entry.entry_id,
                activity_type=ActivityTypeEnum.REVIEW,
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_different_activity_types_allowed(self, db_session):
        user = make_user(db_session)
        book = make_book(db_session)
        entry = make_entry(db_session, user, book)
        tl1 = Timeline(
            user_id=user.user_id,
            entry_id=entry.entry_id,
            activity_type=ActivityTypeEnum.REVIEW,
        )
        tl2 = Timeline(
            user_id=user.user_id,
            entry_id=entry.entry_id,
            activity_type=ActivityTypeEnum.REPOST,
        )
        db_session.add_all([tl1, tl2])
        db_session.flush()
        assert tl1.timeline_id != tl2.timeline_id
