export type MistakeType =
  | "pronunciation"
  | "tone"
  | "vocabulary"
  | "grammar"
  | "fluency"
  | "hesitation";

export type WeaknessCategory =
  | "tone_accuracy"
  | "zh_ch_confusion"
  | "sentence_length"
  | "vocabulary_recall"
  | "grammar_structure"
  | "hesitation";

export type WeaknessStatus = "active" | "improving" | "resolved";

export type MistakeAnalysis = {
  type: MistakeType;
  weakness_category: WeaknessCategory;
  target: string;
  severity: number;
  feedback: string;
  example_sentence: string;
  recommended_drill: string;
};

export type AnalysisResponse = {
  mistakes: MistakeAnalysis[];
  fluency_score: number;
  confidence_score: number;
  summary: string;
  next_focus: string;
  next_drill: string;
};

export type ActiveWeaknessResponse = {
  weakness_category: WeaknessCategory;
  weakness_name: string;
  severity_score: number;
  times_failed: number;
  status: WeaknessStatus;
  recommended_drill: string;
  last_seen: string;
};

export type SessionSummaryResponse = {
  id: number;
  scenario: string;
  transcript: string;
  tutor_reply: string;
  summary: string;
  created_at: string;
};

export type LessonPlanResponse = {
  user_id: string;
  focus_area: string;
  recommended_drill: string;
  next_scenario: string;
  target_words: string[];
  created_at: string | null;
};

export type MemoryResponse = {
  user_id: string;
  learner_level: string;
  native_language: string;
  active_weaknesses: ActiveWeaknessResponse[];
  recent_sessions: SessionSummaryResponse[];
  latest_lesson_plan: LessonPlanResponse | null;
};

export type VoiceChatResponse = {
  user_id: string;
  scenario: string;
  level: string;
  transcript: string;
  tutor_reply: string;
  tutor_audio_url: string | null;
  feedback: AnalysisResponse;
  memory_before: MemoryResponse;
  memory_after: MemoryResponse;
  memory_updated: boolean;
};

export type HealthResponse = {
  status: string;
  project_name: string;
  use_fake_qwen: boolean;
  database_type: string;
};
