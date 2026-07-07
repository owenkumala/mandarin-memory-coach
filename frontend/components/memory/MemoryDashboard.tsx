"use client";

import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingState } from "@/components/ui/LoadingState";
import { useMemory } from "@/hooks/useMemory";
import { NextLessonCard } from "./NextLessonCard";
import { SessionHistoryList } from "./SessionHistoryList";
import { WeaknessList } from "./WeaknessList";

const DEFAULT_USER_ID = "demo-user-asr-test-2";

export function MemoryDashboard() {
  const [userId, setUserId] = useState(DEFAULT_USER_ID);
  const { data, error, isLoading, loadMemory } = useMemory();

  useEffect(() => {
    void loadMemory(DEFAULT_USER_ID);
  }, [loadMemory]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadMemory(userId);
  }

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-jade">
          Learner memory
        </p>
        <h1 className="mt-2 text-3xl font-semibold text-ink">Review what SpeakHan remembers</h1>
      </div>

      <Card>
        <form className="grid gap-3 sm:grid-cols-[1fr_auto]" onSubmit={handleSubmit}>
          <label className="grid gap-2 text-sm font-medium text-ink">
            User ID
            <input
              className="min-h-11 rounded-md border border-ink/15 bg-white px-3 text-ink outline-none focus:border-jade"
              onChange={(event) => setUserId(event.target.value)}
              value={userId}
            />
          </label>
          <Button className="self-end" disabled={isLoading} type="submit">
            Load memory
          </Button>
        </form>
      </Card>

      {error ? <ErrorMessage message={error} /> : null}
      {isLoading ? <LoadingState label="Loading learner memory..." /> : null}

      {data ? (
        <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <Card>
            <div className="mb-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">
                {data.user_id}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-ink">{data.learner_level}</h2>
              <p className="mt-1 text-sm text-ink/60">{data.native_language} speaker</p>
            </div>
            <WeaknessList weaknesses={data.active_weaknesses} />
          </Card>
          <div className="grid gap-6">
            <Card>
              <h2 className="mb-4 text-xl font-semibold text-ink">Latest lesson plan</h2>
              <NextLessonCard lessonPlan={data.latest_lesson_plan} />
            </Card>
            <Card>
              <h2 className="mb-4 text-xl font-semibold text-ink">Recent sessions</h2>
              <SessionHistoryList sessions={data.recent_sessions} />
            </Card>
          </div>
        </div>
      ) : null}
    </div>
  );
}
