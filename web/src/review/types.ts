export interface Reply {
  body: string;
  at: string;
}

export interface ReviewThread {
  id: string;
  path: string;
  side: "old" | "new";
  line: number | null;
  start_line: number | null;
  commit: string;
  body: string;
  at: string;
  replies: Reply[];
  resolved: boolean;
  outdated: boolean;
}

/** The tier review gave a unit; absent from an answer for a unit with no verdict. */
export type ReviewTier = "auto" | "light" | "full";

/** One place the reviewer points a person at, or away from, and why. */
export interface BriefEntry {
  place: string;
  reason: string;
}

/** A round's decision, as the review answer and the decision route return it. */
export interface Decision {
  round: number;
  decision: "request_changes" | "approve";
  summary: string;
  at: string;
}

/** Lines `start`..`end` of one side of one file. */
export interface LineRange {
  path: string;
  side: "old" | "new";
  start: number;
  end: number;
  /** The lines are in the uncommitted changes' section, not the branch's diff. */
  working?: boolean;
}
