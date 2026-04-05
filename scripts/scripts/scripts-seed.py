scripts/seed.py

#!/usr/bin/env python3
"""
Seeds demo data into a running student container.

Usage:
    # Against local dev server
    python scripts/seed.py

    # Against Docker container
    docker exec fotnssj-student python scripts/seed.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set env before importing fotnssj
os.environ.setdefault("SECRET_KEY",  "seed-script-key")
os.environ.setdefault("ADMIN_USER",  "admin")
os.environ.setdefault("ADMIN_PASS",  "adminpass123!")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434")
os.environ.setdefault("LLM_MODEL",    "qwen3:1.5b")

import uuid
import fotnssj


def seed():
    print("\n" + "═" * 60)
    print("  FOTNSSJ Demo Seed")
    print("═" * 60)

    students = [
        ("demo_alice",   "addition_basic",  "arithmetic", 2, 95),
        ("demo_bob",     "phonics_basic",   "reading",    1, 60),
        ("demo_carol",   "doubling",        "arithmetic", 3, 80),
    ]

    for sid, topic, domain, streak, pct_correct in students:
        data = fotnssj.session_manager.get_or_create(sid)
        data["current_topic"]  = topic
        data["current_domain"] = domain
        data["streak_tracker"]._streaks[topic] = streak

        # Seed some raw answer events
        n_events  = 20
        n_correct = int(n_events * pct_correct / 100)
        for i in range(n_events):
            is_correct = i < n_correct
            fotnssj.raw_session_store.record(fotnssj.RawAnswerEvent(
                id=str(uuid.uuid4()),
                student_id=sid,
                topic=topic,
                domain=domain,
                question=f"Seeded question {i}",
                student_answer="4" if is_correct else "wrong",
                correct_answer="4",
                is_correct=is_correct,
                streak_before=i % 3,
                source="seed",
                timestamp=time.time() - (n_events - i) * 60,
            ))

        # Seed a crystallization
        crystal = fotnssj.Crystallization(
            id=str(uuid.uuid4()),
            student_id=sid,
            topic=topic,
            question=f"Seed crystal for {topic}?",
            correct_answer="4",
            explanation=f"Core principle of {topic}.",
            times_correct=3,
            position=fotnssj.GeometricPosition(
                alpha=1.0 + streak * 0.1,
                cave_depth=0.5,
                L_net=0.5 + streak * 0.05,
            ),
            tilt=fotnssj.TiltVector(0.3, 0.1, 0.2),
            next_candidates=[],
            bridge=f"You know {topic}. What comes next?",
            reference_count=streak,
            depth_level=fotnssj.knowledge_model.get_depth(topic, domain),
        )
        fotnssj.session_manager.save_crystal(sid, crystal)
        fotnssj.branch_system.fork(sid, topic, domain)
        fotnssj.branch_system.commit(
            sid, topic, crystal.question,
            crystal.correct_answer, crystal.bridge, crystal.depth_level,
        )

        print(f"  ✓ {sid:20} topic={topic:20} streak={streak} accuracy={pct_correct}%")

    print("\n  Demo students seeded.")
    print("\n" + "═" * 60)
    print("  URLs")
    print("═" * 60)
    for sid, _, _, _, _ in students:
        print(f"  Student : http://localhost:5000/student/{sid}")
    print(f"  Admin   : http://localhost:5003/admin/login")
    print(f"  Geometry: http://localhost:5003/admin/geometry")
    print(f"  Health  : http://localhost:5000/health")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    seed()