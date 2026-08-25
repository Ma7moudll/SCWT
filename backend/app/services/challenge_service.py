from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Challenge, User, UserChallenge, WasteEvent

logger = logging.getLogger("recycle.challenges")


class ChallengeService:
    def list_for_user(self, db: Session, user: User) -> list[dict]:
        progress = self._progress(db, user)
        completed_ids = self._completed_ids(db, user)
        rows = list(db.execute(select(Challenge)).scalars())
        return [
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "theme_emoji": c.theme_emoji,
                "target_kg": c.target_kg,
                # Classes with no confirmed deposits simply have zero progress.
                "current_kg": round(progress.get(c.waste_class, 0.0), 3),
                "reward_points": c.reward_points,
                "completed": c.id in completed_ids
                or progress.get(c.waste_class, 0.0) >= c.target_kg,
                "active": bool(c.active),
            }
            for c in rows
        ]

    def list_for_user_paged(
        self, db: Session, user: User, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        items = self.list_for_user(db, user)
        return items[offset : offset + limit], len(items)

    def on_deposit_confirmed(self, db: Session, user: User, waste_class: str) -> int:
        """Called from the validated deposit path AFTER base points are awarded.

        Completes every active challenge for this waste class whose target the
        user's confirmed tonnage has now reached. Completion and reward are
        persisted atomically; the unique (user_id, challenge_id) constraint
        makes a duplicate reward impossible even under concurrent events.

        A concurrent deposit that completes the SAME challenge in a parallel
        transaction wins the unique row; the loser catches the IntegrityError
        and treats the challenge as already claimed — the caller's base-point
        award is never rolled back because of a bonus race.

        Returns the total bonus points awarded by THIS call (0 when nothing
        newly completed)."""
        progress = self._progress(db, user)
        already = self._completed_ids(db, user)
        bonus = 0
        challenges = db.execute(
            select(Challenge).where(
                Challenge.waste_class == waste_class,
                Challenge.active.is_(True),
            )
        ).scalars()
        for challenge in challenges:
            if challenge.id in already:
                continue
            if progress.get(waste_class, 0.0) < challenge.target_kg:
                continue
            reward_points = challenge.reward_points
            try:
                # Savepoint: a unique-constraint loss rolls back ONLY the
                # bonus insert, never the deposit's base points already
                # written by the caller.
                with db.begin_nested():
                    db.add(
                        UserChallenge(
                            id=UserChallenge.new_id(),
                            user_id=user.id,
                            challenge_id=challenge.id,
                            reward_points=0 if reward_points <= 0 else reward_points,
                        )
                    )
                    db.flush()
            except IntegrityError:
                logger.info(
                    "[CHALLENGE] already claimed concurrently challenge=%s user=%s",
                    challenge.id, user.id,
                )
                continue
            if reward_points <= 0:
                # Nothing to award; completion still persisted for the UI.
                logger.info(
                    "[CHALLENGE] completed (no reward) challenge=%s user=%s",
                    challenge.id, user.id,
                )
                continue
            user.points += reward_points
            bonus += reward_points
            logger.info(
                "[CHALLENGE] completed challenge=%s user=%s reward=%s",
                challenge.id, user.id, reward_points,
            )
        return bonus

    def _completed_ids(self, db: Session, user: User) -> set[str]:
        rows = db.execute(
            select(UserChallenge.challenge_id).where(UserChallenge.user_id == user.id)
        ).scalars()
        return set(rows)

    def _progress(self, db: Session, user: User) -> dict[str, float]:
        """Aggregates confirmed deposit weight per waste class in a single SQL
        GROUP BY query — O(1) regardless of how many deposits the user has."""
        from sqlalchemy import func

        rows = db.execute(
            select(
                WasteEvent.predicted_class,
                func.sum(WasteEvent.weight_grams / 1000.0).label("total_kg"),
            )
            .where(
                WasteEvent.user_id == user.id,
                WasteEvent.status == "confirmed",
            )
            .group_by(WasteEvent.predicted_class)
        ).all()
        return {row.predicted_class: float(row.total_kg or 0.0) for row in rows}
