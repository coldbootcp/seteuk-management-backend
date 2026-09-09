import { sql } from "drizzle-orm";
import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const students = sqliteTable("students", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  grade: integer("grade").notNull(),
  targetCareer: text("target_career").notNull(),
  interests: text("interests").notNull(),
  strengths: text("strengths").notNull(),
  gaps: text("gaps").notNull(),
  color: text("color").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const activities = sqliteTable("activities", {
  id: text("id").primaryKey(),
  studentId: text("student_id")
    .notNull()
    .references(() => students.id, { onDelete: "cascade" }),
  subject: text("subject").notNull(),
  priority: text("priority").notNull().default("core"),
  title: text("title").notNull(),
  description: text("description").notNull().default(""),
  summary: text("summary").notNull(),
  concepts: text("concepts").notNull(),
  completedAt: text("completed_at").notNull(),
});

export const recommendationRuns = sqliteTable("recommendation_runs", {
  id: text("id").primaryKey(),
  studentId: text("student_id").notNull(),
  task: text("task").notNull(),
  inputJson: text("input_json").notNull(),
  outputJson: text("output_json").notNull(),
  provider: text("provider").notNull().default("mock"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const recommendationFeedback = sqliteTable("recommendation_feedback", {
  id: text("id").primaryKey(),
  runId: text("run_id").notNull(),
  studentId: text("student_id").notNull(),
  recommendationId: text("recommendation_id").notNull(),
  action: text("action", { enum: ["saved", "rejected"] }).notNull(),
  reason: text("reason"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const studentWorkspaces = sqliteTable("student_workspaces", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  grade: integer("grade").notNull(),
  semester: integer("semester").notNull(),
  targetCareer: text("target_career").notNull(),
  targetMajorsJson: text("target_majors_json").notNull(),
  interestsJson: text("interests_json").notNull(),
  motivationTrigger: text("motivation_trigger").notNull().default(""),
  careerResolution: text("career_resolution").notNull().default(""),
  currentEngagementJson: text("current_engagement_json").notNull().default("[]"),
  preferredSubjectsJson: text("preferred_subjects_json").notNull(),
  strengthsJson: text("strengths_json").notNull(),
  gapsJson: text("gaps_json").notNull(),
  constraintsJson: text("constraints_json").notNull(),
  outputPreference: text("output_preference").notNull().default(""),
  collaborationStyle: text("collaboration_style").notNull().default(""),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const roadmaps = sqliteTable("roadmaps", {
  id: text("id").primaryKey(),
  studentId: text("student_id").notNull(),
  version: integer("version").notNull(),
  careerTrack: text("career_track").notNull(),
  templateId: text("template_id").notNull(),
  status: text("status").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const roadmapNodes = sqliteTable("roadmap_nodes", {
  id: text("id").primaryKey(),
  roadmapId: text("roadmap_id").notNull(),
  studentId: text("student_id").notNull(),
  orderIndex: integer("order_index").notNull(),
  grade: integer("grade").notNull(),
  semester: integer("semester").notNull(),
  narrativeStage: text("narrative_stage").notNull(),
  title: text("title").notNull(),
  objective: text("objective").notNull(),
  candidateSubjectsJson: text("candidate_subjects_json").notNull(),
  competencyGoalsJson: text("competency_goals_json").notNull(),
  status: text("status").notNull(),
  instantiatedActivityId: text("instantiated_activity_id"),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const roadmapPlanEvents = sqliteTable("roadmap_plan_events", {
  id: text("id").primaryKey(),
  roadmapId: text("roadmap_id").notNull(),
  nodeId: text("node_id").notNull(),
  studentId: text("student_id").notNull(),
  monthDay: text("month_day").notNull(),
  category: text("category").notNull(),
  subject: text("subject").notNull(),
  title: text("title").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const studentActivitiesV2 = sqliteTable("student_activities_v2", {
  id: text("id").primaryKey(),
  studentId: text("student_id").notNull(),
  activityType: text("activity_type").notNull(),
  subject: text("subject").notNull(),
  title: text("title").notNull(),
  summary: text("summary").notNull(),
  reflection: text("reflection").notNull().default(""),
  conceptsJson: text("concepts_json").notNull(),
  outputsJson: text("outputs_json").notNull(),
  status: text("status").notNull(),
  roadmapNodeId: text("roadmap_node_id"),
  planEventId: text("plan_event_id"),
  linkedPlanTitle: text("linked_plan_title"),
  completedAt: text("completed_at").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const studentSemesterCourses = sqliteTable("student_semester_courses", {
  id: text("id").primaryKey(),
  studentId: text("student_id").notNull(),
  roadmapNodeId: text("roadmap_node_id").notNull(),
  grade: integer("grade").notNull(),
  semester: integer("semester").notNull(),
  subject: text("subject").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const studentCourseGrades = sqliteTable("student_course_grades", {
  id: text("id").primaryKey(),
  studentId: text("student_id").notNull(),
  semesterCourseId: text("semester_course_id").notNull(),
  rank: integer("rank"),
  score: integer("score"),
  note: text("note").notNull().default(""),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const reconciliationLogs = sqliteTable("reconciliation_logs", {
  id: text("id").primaryKey(),
  studentId: text("student_id").notNull(),
  activityId: text("activity_id").notNull(),
  roadmapId: text("roadmap_id").notNull(),
  nodeId: text("node_id"),
  matchType: text("match_type").notNull(),
  rationale: text("rationale").notNull(),
  action: text("action").notNull(),
  confidence: integer("confidence").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const activityAttachments = sqliteTable("activity_attachments", {
  id: text("id").primaryKey(), activityId: text("activity_id").notNull(), studentId: text("student_id").notNull(),
  fileName: text("file_name").notNull(), contentType: text("content_type").notNull(), sizeBytes: integer("size_bytes").notNull(),
  storageKey: text("storage_key").notNull(), extractedText: text("extracted_text").notNull().default(""), createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const assignmentAnalyses = sqliteTable("assignment_analyses", {
  id: text("id").primaryKey(),
  studentId: text("student_id").notNull(),
  task: text("task").notNull(),
  resultJson: text("result_json").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const recommendationFeedbackV2 = sqliteTable("recommendation_feedback_v2", {
  id: text("id").primaryKey(),
  studentId: text("student_id").notNull(),
  analysisId: text("analysis_id").notNull(),
  recommendationId: text("recommendation_id").notNull(),
  action: text("action").notNull(),
  reason: text("reason"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const schoolRecordImports = sqliteTable("school_record_imports", {
  id: text("id").primaryKey(),
  studentId: text("student_id").notNull(),
  fileName: text("file_name").notNull(),
  totalPages: integer("total_pages").notNull(),
  courseCount: integer("course_count").notNull(),
  entryCount: integer("entry_count").notNull(),
  status: text("status").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const schoolRecordCourses = sqliteTable("school_record_courses", {
  id: text("id").primaryKey(),
  importId: text("import_id").notNull(),
  studentId: text("student_id").notNull(),
  grade: integer("grade").notNull(),
  semester: integer("semester").notNull(),
  subject: text("subject").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const schoolRecordImportItems = sqliteTable("school_record_import_items", {
  id: text("id").primaryKey(),
  importId: text("import_id").notNull(),
  activityId: text("activity_id").notNull(),
  grade: integer("grade").notNull(),
  semester: integer("semester").notNull(),
  dateBasis: text("date_basis").notNull(),
  confidence: integer("confidence").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});
