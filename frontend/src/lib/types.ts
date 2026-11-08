export type User = { id: string; email: string; name: string; onboarded: boolean };

export type MemoryItem = {
  id: string;
  content: string;
  category: string;
  memory_type: "confirmed" | "assumption" | "temporary";
  status: "active" | "pending" | "archived";
  importance: number;
  sensitive: boolean;
  source: string;
  source_ref?: string | null;
  event_date?: string | null;
  expires_at?: string | null;
  created_at?: string;
  updated_at?: string;
  score?: number;
};

export type PendingAction = { id: string; tool: string; args: any; summary: string; status: string; result?: string; conversation_id?: string };

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  mode?: string | null;
  meta?: any;
  created_at?: string;
  // client-only
  streaming?: boolean;
  tools?: { name: string; status: string; error?: string }[];
  memories?: MemoryItem[];
  pending?: PendingAction[];
};

export type Conversation = { id: string; title: string; mode: string; source: string; pinned: boolean; updated_at: string; summary?: string };

export type Task = { id: string; title: string; notes: string; status: "todo" | "doing" | "done"; priority: "low" | "medium" | "high"; due_at: string | null; project_id: string | null };
export type Reminder = { id: string; text: string; remind_at: string; done: boolean };
export type Project = {
  id: string; name: string; description: string; tech_stack: string[]; status: string; progress: number;
  repo_url: string; deadline: string | null; docs: string; updated_at: string; tasks?: Task[];
};
export type CareerItem = { id: string; kind: string; title: string; organization: string; status: string; level: number; date: string | null; notes: string; link: string };

export const MODES = [
  { id: "auto", label: "Auto", hint: "JARVIS picks the best mode" },
  { id: "companion", label: "Companion", hint: "Casual talk, humour, life" },
  { id: "professor", label: "Professor", hint: "Teach me anything" },
  { id: "mentor", label: "Career Mentor", hint: "Internships, placements, growth" },
  { id: "developer", label: "Developer", hint: "Code, debug, architecture" },
  { id: "research", label: "Research", hint: "Web research & analysis" },
  { id: "executive", label: "Executive", hint: "Plans, tasks, reminders" },
  { id: "reality", label: "Reality Check", hint: "Honest, critical feedback" },
] as const;

export const MODE_COLORS: Record<string, string> = {
  companion: "from-sky-400 to-indigo-400",
  professor: "from-amber-300 to-orange-400",
  mentor: "from-emerald-300 to-teal-400",
  developer: "from-cyan-300 to-blue-500",
  research: "from-fuchsia-400 to-violet-500",
  executive: "from-blue-300 to-violet-400",
  reality: "from-rose-400 to-red-500",
};

export const CATEGORIES = [
  "personal", "education", "career", "skills", "learning", "projects", "internships", "achievements",
  "hackathons", "people", "preferences", "goals", "routines", "decisions", "challenges", "health", "other",
];
